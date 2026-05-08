"""Research a single lead URL → enriched + scored ResearchResult → DB.

Flow:
    fetch website pages (httpx + BS4)
    → build user prompt
    → call Claude with cached system prompt + Pydantic structured output
    → persist Lead row with status=researched
    → return lead id and parsed result

The system prompt lives in prompts/research_prompt.md and is cached
(`cache_control: ephemeral`) so the cost amortises across many leads.

CLI usage:
    python -m agent.research --url https://example.com
    python -m agent.research --url https://example.com --segment paint_and_sip --city Warszawa
"""
from __future__ import annotations

import argparse
import sys
from functools import lru_cache
from pathlib import Path

from agent.enrichment import build_user_message, gather_pages
from agent.scoring import ResearchResult
from core.config import PROJECT_ROOT, settings
from core.db import Lead, LeadStatus, SessionLocal, init_db
from core.kill_switch import is_stopped
from core.llm import get_client
from core.logger import logger, setup_logging

SYSTEM_PROMPT_PATH = PROJECT_ROOT / "prompts" / "research_prompt.md"
MAX_TOKENS = 4096


@lru_cache(maxsize=1)
def _load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def research_url(
    url: str,
    *,
    segment_hint: str | None = None,
    city_hint: str | None = None,
) -> ResearchResult:
    """Pure research: fetch pages → call Claude → return parsed result."""
    gathered = gather_pages(url)
    user_message = build_user_message(
        target_url=url,
        gathered=gathered,
        segment_hint=segment_hint,
        city_hint=city_hint,
    )

    client = get_client()
    response = client.messages.parse(
        model=settings.anthropic_model,
        max_tokens=MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": _load_system_prompt(),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_message}],
        output_format=ResearchResult,
    )
    result: ResearchResult = response.parsed_output
    logger.bind(
        source="research",
        payload={
            "url": url,
            "score_total": result.score.total,
            "segment": result.segment,
            "cache_read_tokens": getattr(response.usage, "cache_read_input_tokens", 0),
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    ).info(f"Researched {url}: {result.company_name} (score={result.score.total})")
    return result


def save_lead(url: str, result: ResearchResult, *, source: str = "manual_url") -> int:
    """Persist a ResearchResult to the leads table. Returns lead id."""
    with SessionLocal() as session:
        lead = Lead(
            segment=result.segment,
            company_name=result.company_name,
            contact_name=result.contact_name,
            email=result.email,
            phone=result.phone,
            website=result.website or url,
            instagram=result.instagram,
            city=result.city,
            source=source,
            score=result.score.total,
            status=LeadStatus.RESEARCHED.value,
            research_data=result.model_dump(),
        )
        session.add(lead)
        session.commit()
        return lead.id


def research_and_save(
    url: str,
    *,
    segment_hint: str | None = None,
    city_hint: str | None = None,
) -> tuple[int, ResearchResult]:
    """Research a URL and persist the result. Returns (lead_id, result)."""
    result = research_url(url, segment_hint=segment_hint, city_hint=city_hint)
    lead_id = save_lead(url, result)
    return lead_id, result


def main() -> None:
    parser = argparse.ArgumentParser(description="Research a single lead URL.")
    parser.add_argument("--url", required=True, help="URL strony do oceny")
    parser.add_argument("--segment", default=None, help="Hint segmentu (opcjonalny)")
    parser.add_argument("--city", default=None, help="Hint miasta (opcjonalny)")
    args = parser.parse_args()

    setup_logging()
    init_db()

    if is_stopped():
        logger.bind(source="research").warning("STOP.txt present — research aborted.")
        return

    try:
        lead_id, result = research_and_save(
            args.url, segment_hint=args.segment, city_hint=args.city
        )
    except Exception as exc:
        logger.bind(source="research").exception(f"Research failed for {args.url}: {exc}")
        sys.exit(1)

    print(f"Saved lead id={lead_id}")
    print(f"  company: {result.company_name}")
    print(f"  segment: {result.segment}")
    print(f"  score:   {result.score.total}/10  "
          f"(activity={result.score.activity}, scale={result.score.scale}, "
          f"fit={result.score.fit}, bulk={result.score.bulk_potential}, "
          f"contact={result.score.contact_quality})")
    print(f"  email:   {result.email or '-'}")
    print(f"  contact: {result.contact_name or '-'}")
    print(f"  rationale: {result.rationale}")
    if result.warning_flags:
        print(f"  WARNINGS: {', '.join(result.warning_flags)}")


if __name__ == "__main__":
    main()
