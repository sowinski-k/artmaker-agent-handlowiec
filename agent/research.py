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

from sqlalchemy import select

from agent.enrichment import build_user_message, gather_pages
from agent.scoring import ResearchResult
from core.config import PROJECT_ROOT, settings
from core.db import Lead, LeadStatus, SessionLocal, init_db
from core.kill_switch import is_stopped
from core.llm import estimate_cost_usd, parse_structured
from core.logger import logger, setup_logging
from core.urls import host_only, normalize_url

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


def find_existing_lead(url: str, workspace_id: int | None = None) -> int | None:
    """Return the id of an existing Lead whose website normalizes to the same
    key as `url`, or None.

    SECURITY (multi-tenant): JEZELI workspace_id != None, filtruje TYLKO leady
    z tego workspace'u. Bez filtru istniało ryzyko data leak - workspace A's
    research_and_save mogl matchnac lead workspace B i go nadpisac.

    Caller (research_and_save) MUSI przekazac workspace_id z job context.
    """
    target = normalize_url(url)
    if not target:
        return None
    host = host_only(url)
    if not host:
        return None
    with SessionLocal() as session:
        # Pomijaj soft-deleted (kosz). User usunal lead -> chce go pozyskac
        # ponownie -> nowy lead. Stary zostaje w trash do auto-purge.
        q = select(Lead.id, Lead.website).where(
            Lead.website.ilike(f"%{host}%"),
            Lead.deleted_at.is_(None),
        )
        if workspace_id is not None:
            q = q.where(Lead.workspace_id == workspace_id)
        rows = session.execute(q).all()
    for lead_id, website in rows:
        if normalize_url(website) == target:
            return lead_id
    return None


def save_lead(
    url: str,
    result: ResearchResult,
    *,
    source: str = "manual_url",
    workspace_id: int | None = None,
) -> tuple[int, bool]:
    """Persist or update a Lead based on URL match. Returns (lead_id, created).

    `created=False` means an existing lead was found and refreshed instead of
    a new row inserted.
    """
    target_url = result.website or url
    # Normalizacja pustych stringow do None. LLM czasem zwraca "" / " " /
    # "-" zamiast None dla brakujacych pol; SQL ORDER BY (email IS NULL)
    # nie lapie wtedy pustych = chaos w sortowaniu/filtrach.
    def _clean(v: str | None) -> str | None:
        if v is None: return None
        s = v.strip()
        if not s or s in ("-", "n/a", "N/A", "brak", "Brak"): return None
        return s

    email = _clean(result.email)
    phone = _clean(result.phone)
    instagram = _clean(result.instagram)
    contact_name = _clean(result.contact_name)
    city = _clean(result.city)

    existing_id = find_existing_lead(target_url, workspace_id=workspace_id)
    with SessionLocal() as session:
        if existing_id is not None:
            lead = session.get(Lead, existing_id)
            # SAFETY: jak workspace_id przekazany ALE wczytany lead jest w innym
            # workspace, NIE nadpisuj. Cross-workspace boundary protection.
            if workspace_id is not None and lead is not None \
                    and lead.workspace_id is not None \
                    and lead.workspace_id != workspace_id:
                logger.bind(source="research").error(
                    f"Cross-workspace save_lead attempt blocked: target ws={workspace_id} "
                    f"vs lead ws={lead.workspace_id}. Falling back to create new."
                )
                existing_id = None
                lead = None
        if existing_id is not None and lead is not None:
            lead.segment = result.segment
            lead.company_name = result.company_name
            lead.contact_name = contact_name
            lead.email = email
            lead.phone = phone
            lead.website = target_url
            lead.instagram = instagram
            lead.city = city
            lead.source = source
            lead.score = result.score.total
            lead.status = LeadStatus.RESEARCHED.value
            lead.research_data = result.model_dump()
            session.commit()
            return lead.id, False
        lead = Lead(
            workspace_id=workspace_id,
            segment=result.segment,
            company_name=result.company_name,
            contact_name=contact_name,
            email=email,
            phone=phone,
            website=target_url,
            instagram=instagram,
            city=city,
            source=source,
            score=result.score.total,
            status=LeadStatus.RESEARCHED.value,
            research_data=result.model_dump(),
        )
        session.add(lead)
        session.commit()
        return lead.id, True


def research_and_save(
    url: str,
    *,
    segment_hint: str | None = None,
    city_hint: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    force_refresh: bool = False,
    workspace_id: int | None = None,
) -> tuple[int, ResearchResult | None, bool]:
    """Research a URL and persist the result.

    Returns ``(lead_id, result, was_researched)``:
      - ``was_researched=True``  → fresh LLM research happened (new lead OR forced refresh).
      - ``was_researched=False`` → existing lead found, no LLM tokens spent. ``result`` is None.

    Set ``force_refresh=True`` to re-research and update an existing lead
    instead of skipping it.
    """
    if not force_refresh:
        existing_id = find_existing_lead(url, workspace_id=workspace_id)
        if existing_id is not None:
            logger.bind(source="research").info(
                f"Skipping research for {url}: lead #{existing_id} already exists."
            )
            return existing_id, None, False

    # Daily limit guard - prevent runaway costs gdy ktoś zostawi auto-pipeline.
    # MULTI-TENANT: cap PER WORKSPACE. Bez workspace filter jeden tenant po
    # hicie limitu blokowal pozostalych - kazdy tenant musi miec swoj counter.
    # workspace_id=None (np. CLI bez kontekstu) -> count globalny (legacy).
    if settings.daily_research_limit > 0:
        from datetime import datetime, timezone
        from sqlalchemy import select as _select, func as _func

        start_of_day = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        with SessionLocal() as session:
            q = _select(_func.count(Lead.id)).where(
                Lead.created_at >= start_of_day,
                Lead.status != LeadStatus.NEW.value,
            )
            if workspace_id is not None:
                q = q.where(Lead.workspace_id == workspace_id)
            researched_today = session.scalar(q) or 0
        if researched_today >= settings.daily_research_limit:
            msg = (
                f"Dzienny limit researchy osiągnięty: {researched_today}/"
                f"{settings.daily_research_limit}. Podnieś DAILY_RESEARCH_LIMIT "
                "albo poczekaj do jutra (limit resetuje się o północy UTC)."
            )
            logger.bind(source="research").warning(msg)
            raise RuntimeError(msg)

    if force_refresh:
        logger.bind(source="research").info(
            f"Force refresh dla {url} - re-research mimo że może być w bazie."
        )

    result = research_url(
        url,
        segment_hint=segment_hint,
        city_hint=city_hint,
        provider=provider,
        model=model,
    )
    lead_id, _created = save_lead(url, result, workspace_id=workspace_id)

    # Auto-enrich jesli LLM przegapil email LUB phone (czeste przy stronach z
    # kontaktem na osobnej podstronie - LLM dostaje subset HTML i czesto bierze
    # tylko jeden z dwoch kanalow kontaktu). Tani fallback - regex po homepage
    # + /kontakt. Jak dalej puste oba -> DEAD_END.
    # OR zamiast AND: nawet jak mamy phone, sprobujmy dorzucic email - to
    # najwiekszy single signal w cold-email outreach.
    if not result.email or not result.phone:
        try:
            from agent.contact_finder import enrich_lead_in_db
            enrich_result = enrich_lead_in_db(lead_id, workspace_id=workspace_id)
            if enrich_result.email or enrich_result.phone:
                logger.bind(source="research").info(
                    f"Lead #{lead_id} auto-enriched: email={enrich_result.email} "
                    f"phone={enrich_result.phone} (src={enrich_result.source})"
                )
        except Exception as exc:
            logger.bind(source="research").warning(
                f"Auto-enrich for lead #{lead_id} failed (non-critical): {exc}"
            )

    return lead_id, result, True


def main() -> None:
    parser = argparse.ArgumentParser(description="Research a single lead URL.")
    parser.add_argument("--url", required=True, help="URL strony do oceny")
    parser.add_argument("--segment", default=None, help="Hint segmentu (opcjonalny)")
    parser.add_argument("--city", default=None, help="Hint miasta (opcjonalny)")
    parser.add_argument("--provider", default=None, help="anthropic | gemini (default: z .env)")
    parser.add_argument("--model", default=None, help="ID modelu (default: z .env)")
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Re-research even if URL already in DB (default: skip duplicates).",
    )
    args = parser.parse_args()

    setup_logging()
    init_db()

    if is_stopped():
        logger.bind(source="research").warning("STOP.txt present — research aborted.")
        return

    try:
        lead_id, result, was_researched = research_and_save(
            args.url,
            segment_hint=args.segment,
            city_hint=args.city,
            provider=args.provider,
            model=args.model,
            force_refresh=args.force_refresh,
        )
    except Exception as exc:
        logger.bind(source="research").exception(f"Research failed for {args.url}: {exc}")
        sys.exit(1)

    if not was_researched:
        print(f"Skipped: lead id={lead_id} already exists for {args.url}.")
        print("Use --force-refresh to re-research and update.")
        return

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
