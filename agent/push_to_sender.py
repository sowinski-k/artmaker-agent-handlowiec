"""Push approved drafts to Woodpecker as prospects with snippets.

Reads:
    - email_drafts with status=approved (lub manual draft id przez API)
    - WOODPECKER_API_KEY (env / Streamlit secret)

Writes (to Woodpecker, then mirrors locally):
    - POST /rest/v1/add_prospects_campaign with email + snippet1..N
    - Po sukcesie: draft.status -> sent, draft.sent_at, draft.woodpecker_prospect_id
    - Po sukcesie: lead.status -> sent

Guards:
    - Respects STOP.txt i DRY_RUN.
    - Cap dziennych pushów po DAILY_EMAIL_LIMIT.
    - Skipuje drafty bez lead.email (Woodpecker wymaga adresu).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from sqlalchemy import func, select

from agent.woodpecker import (
    WoodpeckerError,
    WoodpeckerProspect,
    add_prospects,
    has_woodpecker_key,
)
from core.config import settings
from core.db import (
    DraftStatus,
    EmailDraft,
    Event,
    Lead,
    LeadStatus,
    SessionLocal,
    init_db,
)
from core.kill_switch import is_stopped
from core.logger import logger, setup_logging


def _split_name(full_name: str | None) -> tuple[str | None, str | None]:
    """Z 'Anna Kowalska' robi ('Anna', 'Kowalska'). Z 'Anna' robi ('Anna', None)."""
    if not full_name or not full_name.strip():
        return None, None
    parts = full_name.strip().split(maxsplit=1)
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1]


def _build_prospect(lead: Lead, draft: EmailDraft) -> WoodpeckerProspect:
    """Zmapuj nasz Lead+EmailDraft na payload Woodpecker'a.

    Snippets 1-5 = body drafta. Snippet6 = subject (do override'u w template
    kampanii: subject może mieć `{{SNIPPET6}}` jeśli chcesz per-prospect subject).
    Snippet7 = company city (do personalizacji 'jak z Warszawy do Warszawy').
    """
    first_name, last_name = _split_name(lead.contact_name)
    return WoodpeckerProspect(
        email=(lead.email or "").strip(),
        first_name=first_name,
        last_name=last_name,
        company=lead.company_name,
        city=lead.city,
        website=lead.website,
        phone=lead.phone,
        snippet1=draft.snippet1,
        snippet2=draft.snippet2,
        snippet3=draft.snippet3,
        snippet4=draft.snippet4,
        snippet5=draft.snippet5,
        snippet6=draft.subject,
        snippet7=lead.city or None,
    )


def _count_sent_today() -> int:
    """Ile draftów ostatnio poszło - do cap'a DAILY_EMAIL_LIMIT."""
    start_of_day = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    with SessionLocal() as session:
        return session.scalar(
            select(func.count(EmailDraft.id)).where(
                EmailDraft.status == DraftStatus.SENT.value,
                EmailDraft.sent_at >= start_of_day,
            )
        ) or 0


def push_draft(draft_id: int, campaign_id: int) -> str:
    """Wyślij jeden draft do kampanii Woodpecker. Returns prospect_id z Woodpeckera.

    Skipuje + raise jeśli:
      - DRY_RUN=true (nic nie wyjdzie)
      - STOP.txt obecny
      - draft.status nie jest APPROVED ani DRAFT (już wysłany lub odrzucony)
      - lead.email jest pusty
      - dzienny limit już osiągnięty
    """
    log = logger.bind(source="push", draft_id=draft_id)

    if is_stopped():
        raise RuntimeError("STOP.txt present - push aborted.")
    if settings.dry_run:
        raise RuntimeError(
            "DRY_RUN=true - push pominięty. Ustaw DRY_RUN=false w env żeby wysyłać."
        )
    if not has_woodpecker_key():
        raise RuntimeError("Brak WOODPECKER_API_KEY w env / Streamlit secrets.")

    sent_today = _count_sent_today()
    if sent_today >= settings.daily_email_limit:
        raise RuntimeError(
            f"Dzienny limit wysyłki osiągnięty: {sent_today}/{settings.daily_email_limit}. "
            f"Zwiększ DAILY_EMAIL_LIMIT albo poczekaj do jutra."
        )

    with SessionLocal() as session:
        draft = session.get(EmailDraft, draft_id)
        if draft is None:
            raise ValueError(f"Draft #{draft_id} nie istnieje.")
        if draft.status not in {DraftStatus.APPROVED.value, DraftStatus.DRAFT.value}:
            raise RuntimeError(
                f"Draft #{draft_id} ma status '{draft.status}', oczekuję 'draft' lub 'approved'."
            )
        # Twardo wymagamy subject (snippet6 w Woodpeckerze). Nasze prompty zawsze
        # generuja indywidualny subject - pusty to bug, NIE okazja do fallbacka
        # w template kampanii. Lepiej zatrzymac wysylke niz puscic generic temat.
        if not (draft.subject or "").strip():
            raise RuntimeError(
                f"Draft #{draft_id} ma pusty temat - nie wysylamy. "
                "Wygeneruj nowy draft albo dopisz temat recznie w edycji."
            )
        lead = session.get(Lead, draft.lead_id)
        if lead is None or not (lead.email or "").strip():
            raise RuntimeError(
                f"Lead #{draft.lead_id if lead else '?'} bez emaila - nie da się wysłać. "
                "Dodaj email do leada albo odrzuć tego drafta."
            )

        prospect = _build_prospect(lead, draft)
        try:
            response = add_prospects(campaign_id, [prospect])
        except WoodpeckerError as exc:
            log.exception(f"Woodpecker odrzucił push: {exc}")
            raise RuntimeError(f"Woodpecker error: {exc}") from exc

        prospect_id = ""
        prospects = response.get("prospects") if isinstance(response, dict) else None
        if isinstance(prospects, list) and prospects:
            prospect_id = str(prospects[0].get("id") or "")

        draft.status = DraftStatus.SENT.value
        draft.sent_at = datetime.now(timezone.utc)
        draft.woodpecker_prospect_id = prospect_id or None
        lead.status = LeadStatus.SENT.value

        session.add(
            Event(
                level="INFO",
                source="push",
                type="email_sent",
                message=(
                    f"Draft #{draft_id} -> Woodpecker campaign #{campaign_id} "
                    f"(prospect_id={prospect_id or 'unknown'}), to={lead.email}"
                ),
            )
        )
        session.commit()

    log.info(
        f"Pushed draft #{draft_id} to campaign {campaign_id} "
        f"(prospect_id={prospect_id or 'unknown'})"
    )
    return prospect_id


def push_all_approved(campaign_id: int) -> tuple[int, int]:
    """Bulk push wszystkich drafftów ze statusem APPROVED do kampanii.
    Returns (sent, failed)."""
    with SessionLocal() as session:
        approved_ids = session.execute(
            select(EmailDraft.id).where(EmailDraft.status == DraftStatus.APPROVED.value)
        ).scalars().all()

    sent, failed = 0, 0
    for draft_id in approved_ids:
        if is_stopped():
            logger.bind(source="push").warning("STOP.txt detected - halting push.")
            break
        try:
            push_draft(draft_id, campaign_id)
            sent += 1
        except Exception as exc:
            failed += 1
            logger.bind(source="push").exception(
                f"Draft #{draft_id} push failed: {exc}"
            )
    return sent, failed


def main() -> None:
    parser = argparse.ArgumentParser(description="Push approved drafts to Woodpecker.")
    parser.add_argument(
        "--draft-id", type=int, default=None,
        help="Jeden draft po id. Wymaga --campaign-id.",
    )
    parser.add_argument(
        "--all-approved", action="store_true",
        help="Wszystkie drafty ze statusem APPROVED. Wymaga --campaign-id.",
    )
    parser.add_argument(
        "--campaign-id", type=int, required=True,
        help="ID kampanii Woodpecker do której wpychamy prospects.",
    )
    args = parser.parse_args()

    setup_logging()
    init_db()

    if args.draft_id is not None:
        prospect_id = push_draft(args.draft_id, args.campaign_id)
        print(f"Pushed draft #{args.draft_id} -> woodpecker prospect_id={prospect_id}")
        return
    if args.all_approved:
        sent, failed = push_all_approved(args.campaign_id)
        print(f"Bulk push: {sent} sent, {failed} failed.")
        return
    parser.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
