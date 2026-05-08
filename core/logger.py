import sys

from loguru import logger

from core.config import settings
from core.db import Event, SessionLocal, init_db

_configured = False


def _to_db_sink(message) -> None:
    record = message.record
    extra = record["extra"]
    try:
        with SessionLocal() as session:
            session.add(
                Event(
                    type=extra.get("event_type", "log"),
                    level=record["level"].name,
                    source=extra.get("source"),
                    message=record["message"],
                    payload=extra.get("payload"),
                )
            )
            session.commit()
    except Exception:
        # Never let logging crash the agent.
        pass


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    init_db()
    logger.remove()
    logger.add(sys.stderr, level=settings.log_level)
    logger.add(_to_db_sink, level="INFO")
    _configured = True


__all__ = ["logger", "setup_logging"]
