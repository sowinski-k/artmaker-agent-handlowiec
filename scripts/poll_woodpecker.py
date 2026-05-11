"""Polling Woodpeckera w poszukiwaniu zmian statusu prospects.

Po wysłaniu draftu (push_to_sender.py) lead ma status SENT. Co X czasu
pytamy Woodpecker o aktualny stan każdego sent leada - jeśli odpisał,
odbiło się od skrzynki albo trafił do blacklisty, aktualizujemy lokalnie.

Mapowanie statusów Woodpecker -> nasz LeadStatus:
    REPLIED               -> LeadStatus.REPLIED  (🔥 dashboard alert)
    BOUNCED / bounced=True -> LeadStatus.BOUNCED
    BLACKLISTED           -> LeadStatus.BLACKLISTED
    INTERESTED            -> LeadStatus.REPLIED  (Woodpecker tag manualny)
    NOT_INTERESTED        -> LeadStatus.REPLIED  (też reply, tylko nie potwierdzony)

Run:
    python -m scripts.poll_woodpecker
    python -m scripts.poll_woodpecker --max 50   # ile leadów sprawdzić max
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from agent.woodpecker import (
    WoodpeckerError,
    get_prospects_by_email,
    has_woodpecker_key,
)
from core.db import (
    Event,
    Lead,
    LeadStatus,
    SessionLocal,
    init_db,
)
from core.kill_switch import is_stopped
from core.logger import logger, setup_logging


# Statusy które leadom zostają na placu boju - po REPLIED/BOUNCED nie ma sensu
# dalej polling'ować bo Woodpecker już ich nie sequencuje.
_POLL_TARGET_STATUSES = {LeadStatus.SENT.value}


def _map_status(woodpecker_status: str, bounced: bool) -> str | None:
    """Mapuj status z Woodpeckera na nasz LeadStatus. None = nic nie zmieniaj."""
    if bounced:
        return LeadStatus.BOUNCED.value
    upper = (woodpecker_status or "").upper()
    if upper in {"REPLIED", "INTERESTED", "NOT_INTERESTED", "MAYBE_LATER"}:
        return LeadStatus.REPLIED.value
    if upper in {"BOUNCED"}:
        return LeadStatus.BOUNCED.value
    if upper in {"BLACKLISTED"}:
        return LeadStatus.BLACKLISTED.value
    # ACTIVE / FINISHED / PAUSED - nadal w toku, nie zmieniamy
    return None


def poll_statuses(max_leads: int = 100) -> dict[str, int]:
    """Sprawdź statusy dla SENT leadów. Returns counts: checked/replied/bounced/unchanged."""
    log = logger.bind(source="poll")

    if not has_woodpecker_key():
        log.warning("Brak WOODPECKER_API_KEY - skipping poll.")
        return {"checked": 0, "replied": 0, "bounced": 0, "blacklisted": 0, "unchanged": 0, "errors": 0}

    with SessionLocal() as session:
        target_leads = session.execute(
            select(Lead.id, Lead.email)
            .where(
                Lead.status.in_(_POLL_TARGET_STATUSES),
                Lead.email.isnot(None),
                Lead.email != "",
            )
            .order_by(Lead.updated_at.desc())
            .limit(max_leads)
        ).all()

    if not target_leads:
        log.info("Brak leadów do polling'u (żaden nie ma statusu SENT z emailem).")
        return {"checked": 0, "replied": 0, "bounced": 0, "blacklisted": 0, "unchanged": 0, "errors": 0}

    log.info(f"Polling Woodpecker for {len(target_leads)} leads...")

    counts = {"checked": 0, "replied": 0, "bounced": 0, "blacklisted": 0, "unchanged": 0, "errors": 0}
    emails_to_lead = {(email or "").lower(): lead_id for lead_id, email in target_leads if email}

    try:
        statuses = get_prospects_by_email(emails_to_lead.keys())
    except WoodpeckerError as exc:
        log.exception(f"Polling padł całkowicie: {exc}")
        counts["errors"] = len(target_leads)
        return counts

    counts["checked"] = len(statuses)

    with SessionLocal() as session:
        for status in statuses:
            if is_stopped():
                log.warning("STOP.txt detected - halting poll.")
                break
            lead_id = emails_to_lead.get(status.email.lower())
            if lead_id is None:
                continue

            new_status = _map_status(status.status, status.bounced)
            if new_status is None:
                counts["unchanged"] += 1
                continue

            lead = session.get(Lead, lead_id)
            if lead is None or lead.status == new_status:
                counts["unchanged"] += 1
                continue

            old_status = lead.status
            lead.status = new_status
            session.add(
                Event(
                    level="INFO",
                    source="poll",
                    type="status_change",
                    message=(
                        f"Lead #{lead_id} ({status.email}): {old_status} -> {new_status} "
                        f"(woodpecker: {status.status})"
                    ),
                )
            )
            counts[new_status] = counts.get(new_status, 0) + 1
            log.info(
                f"Lead #{lead_id} ({status.email}): {old_status} -> {new_status}"
            )

        session.commit()

    log.info(f"Poll done: {counts}")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll Woodpecker for lead status updates.")
    parser.add_argument("--max", type=int, default=100, help="Max leadów do sprawdzenia w jednym runie.")
    args = parser.parse_args()

    setup_logging()
    init_db()

    if is_stopped():
        logger.bind(source="poll").warning("STOP.txt present - poll aborted.")
        return

    counts = poll_statuses(max_leads=args.max)
    print(
        f"Checked: {counts['checked']}, "
        f"replied: {counts['replied']}, "
        f"bounced: {counts['bounced']}, "
        f"blacklisted: {counts['blacklisted']}, "
        f"unchanged: {counts['unchanged']}, "
        f"errors: {counts['errors']}"
    )


if __name__ == "__main__":
    main()
