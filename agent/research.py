"""Research module — finds and enriches leads.

Plan (not implemented yet):
    - Pull candidate businesses per segment + city via Google Maps Places API.
    - Visit each candidate's website (Playwright / httpx + BS4) and extract
      contact email, owner name, signals of activity (recent events, blog).
    - Optionally pull Instagram / Facebook signals (followers, post cadence).
    - Score each lead 1-10 using Claude based on a rubric (activity,
      relevance, contact quality, segment fit).
    - Persist to leads table with status=researched and full research_data
      JSON for use by the draft generator.
"""

from core.kill_switch import is_stopped
from core.logger import logger, setup_logging


def main() -> None:
    setup_logging()
    if is_stopped():
        logger.bind(source="research").warning("STOP.txt present — research aborted.")
        return
    logger.bind(source="research").info(
        "Research module not implemented yet. See module docstring for the plan."
    )


if __name__ == "__main__":
    main()
