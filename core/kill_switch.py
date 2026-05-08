from core.config import PROJECT_ROOT

STOP_FILE = PROJECT_ROOT / "STOP.txt"


def is_stopped() -> bool:
    return STOP_FILE.exists()


def stop(reason: str = "manual stop") -> None:
    STOP_FILE.write_text(reason)


def resume() -> None:
    if STOP_FILE.exists():
        STOP_FILE.unlink()
