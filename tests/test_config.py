"""Smoke testy dla core/config.Settings - krytyczne dla deploy.

Postgres URL normalizacja: Railway zwraca 'postgres://...' ale SQLAlchemy 2.x
wymaga 'postgresql://'. Bez tej normalizacji aplikacja nie startuje na Railway.
"""
from __future__ import annotations

import os

# WAZNE: importujemy Settings (klasa) zamiast singletona `settings`, zeby moc
# konstruowac fresh instancje dla kazdego test case (env-driven).
from core.config import Settings


def test_default_sqlite_when_no_database_url():
    s = Settings(database_url="")
    assert s.db_url.startswith("sqlite:///")


def test_postgres_url_normalization():
    """Railway zwraca 'postgres://' - musi byc zamieniony na 'postgresql://'."""
    s = Settings(database_url="postgres://user:pass@host:5432/db")
    assert s.db_url == "postgresql://user:pass@host:5432/db"


def test_postgresql_url_unchanged():
    """Jak juz jest 'postgresql://', zostawiamy w spokoju."""
    url = "postgresql://user:pass@host/db"
    s = Settings(database_url=url)
    assert s.db_url == url


def test_dry_run_default_true():
    """DRY_RUN domyslnie True - zabezpieczenie przed accidental Woodpecker push."""
    s = Settings()
    assert s.dry_run is True


def test_llm_provider_default_anthropic():
    s = Settings()
    assert s.llm_provider == "anthropic"
