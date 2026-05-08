"""Push approved drafts to Woodpecker as prospects with snippets.

Reads:
    - email_drafts with status=approved
    - WOODPECKER_API_KEY + WOODPECKER_CAMPAIGN_ID from env

Writes (to Woodpecker, then mirrors locally):
    - POST /api/v1/add_prospects_campaign with email + snippet1..15
    - On success: draft.status -> sent, draft.sent_at, draft.woodpecker_prospect_id
    - On success: lead.status -> sent

Guards:
    - Respects STOP.txt and DRY_RUN.
    - Caps daily pushes at DAILY_EMAIL_LIMIT.
"""

from core.config import settings
from core.kill_switch import is_stopped
from core.logger import logger, setup_logging


def main() -> None:
    setup_logging()
    log = logger.bind(source="push")
    if is_stopped():
        log.warning("STOP.txt present — push aborted.")
        return
    if settings.dry_run:
        log.info("DRY_RUN=true — would push to Woodpecker but skipping.")
        return
    log.info("Push module not implemented yet. See module docstring for the plan.")


if __name__ == "__main__":
    main()
