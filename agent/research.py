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
from core.llm import estimate_cost_usd, parse_structured
from core.logger import logger, setup_logging

SYSTEM_PROMPT_PATH = PROJECT_ROOT / "prompts" / "research_prompt.md"
MAX_TOKENS = 4096


@lru_cache(maxsize=1)
def _load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def _resolve_provider_model(
    provider: str | None, model: str | None
) -> tuple[str, str]:
    provider = (provider or settings.llm_provider).lower()
    if model:
        return provider, model
    if provider == "anthropic":
        return provider, settings.anthropic_model
    if provider == "gemini":
        return provider, settings.gemini_model
    raise ValueError(f"Unknown LLM provider: {provider!r}")


def research_url(
    url: str,
    *,
    segment_hint: str | None = None,
    city_hint: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> ResearchResult:
    """Pure research: fetch pages → call LLM → return parsed result."""
    provider, model = _resolve_provider_model(provider, model)

    gathered = gather_pages(url)
    user_message = build_user_message(
        target_url=url,
        gathered=gathered,
        segment_hint=segment_hint,
        city_hint=city_hint,
    )

    result, usage = parse_structured(
        provider=provider,
        model=model,
        system=_load_system_prompt(),
        user=user_message,
        output_schema=ResearchResult,
        max_tokens=MAX_TOKENS,
    )

    cost_usd = estimate_cost_usd(provider, model, usage)
    logger.bind(
        source="research",
        payload={
            "url": url,
            "provider": provider,
            "model": model,
            "score_total": result.score.total,
            "segment": result.segment,
            "usage": usage,
            "cost_usd": cost_usd,
        },
    ).info(
        f"Researched {url}: {result.company_name} "
        f"(score={result.score.total}, model={provider}/{model}, cost~${cost_usd or '?'})"
    )
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
    provider: str | None = None,
    model: str | None = None,
) -> tuple[int, ResearchResult]:
    """Research a URL and persist the result. Returns (lead_id, result)."""
    result = research_url(
        url,
        segment_hint=segment_hint,
        city_hint=city_hint,
        provider=provider,
        model=model,
    )
    lead_id = save_lead(url, result)
    return lead_id, result


def main() -> None:
    parser = argparse.ArgumentParser(description="Research a single lead URL.")
    parser.add_argument("--url", required=True, help="URL strony do oceny")
    parser.add_argument("--segment", default=None, help="Hint segmentu (opcjonalny)")
    parser.add_argument("--city", default=None, help="Hint miasta (opcjonalny)")
    parser.add_argument("--provider", default=None, help="anthropic | gemini (default: z .env)")
    parser.add_argument("--model", default=None, help="ID modelu (default: z .env)")
    args = parser.parse_args()

    setup_logging()
    init_db()

    if is_stopped():
        logger.bind(source="research").warning("STOP.txt present — research aborted.")
        return

    try:
        lead_id, result = research_and_save(
            args.url,
            segment_hint=args.segment,
            city_hint=args.city,
            provider=args.provider,
            model=args.model,
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
