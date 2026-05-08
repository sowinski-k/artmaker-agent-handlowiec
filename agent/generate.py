"""Generate cold email drafts from researched leads.

Reads:
    - leads with status=researched
    - prompts/few_shot_examples/*.md (owner's real writing — voice anchor)
    - prompts/generate_prompt.md (system prompt, per segment)

Writes:
    - email_drafts rows with status=draft
        - subject + snippet1..snippet5 (Woodpecker-compatible)
        - full_preview = subject + assembled body for human review
    - leads.status -> drafted

Personalization rule: each snippet must reference at least one concrete
detail from research_data. Generic openings ("hope this finds you well")
are not allowed. See prompts/generate_prompt.md for the full rubric.
"""

from core.kill_switch import is_stopped
from core.logger import logger, setup_logging


def main() -> None:
    setup_logging()
    if is_stopped():
        logger.bind(source="generate").warning("STOP.txt present — generate aborted.")
        return
    logger.bind(source="generate").info(
        "Generate module not implemented yet. See module docstring for the plan."
    )


if __name__ == "__main__":
    main()
