"""Pytest config - importable z roota projektu + in-memory SQLite dla testow DB."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow imports z root projektu w testach
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Wymus in-memory SQLite zanim cokolwiek zaimportuje core.config / core.db.
# DATABASE_URL nadpisuje SQLite default - dla testow chcemy izolowanej bazy.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
# Wylacz autorejestracje admina (wymaga ADMIN_EMAIL) - testy nie potrzebuja.
os.environ.pop("ADMIN_EMAIL", None)
os.environ.pop("ADMIN_PASSWORD", None)
os.environ.pop("APP_PASSWORD", None)
# Sentry DSN puste - testujemy no-op path.
os.environ.pop("SENTRY_DSN", None)
