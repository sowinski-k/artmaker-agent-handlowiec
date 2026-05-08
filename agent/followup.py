"""Custom follow-up generation.

Most follow-ups should be handled natively by Woodpecker's sequence engine.
Use this module only when a follow-up needs fresh research (e.g. referencing
something the lead posted after the first mail).

TODO: design once the Woodpecker integration is up and we see real data.
"""

from core.kill_switch import is_stopped
from core.logger import logger, setup_logging


def main() -> None:
    setup_logging()
    if is_stopped():
        logger.bind(source="followup").warning("STOP.txt present — follow-up aborted.")
        return
    logger.bind(source="followup").info(
        "Follow-up module not implemented yet. See module docstring."
    )


if __name__ == "__main__":
    main()
