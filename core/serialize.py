"""Serialization helpers - JSON-safe rzutowanie datetime do ISO z UTC suffixem.

Problem ktory rozwiazuje (bug raportowany przez usera "2h temu" na swiezym
evencie):
- core/db.py uzywa default=utcnow() ktory zwraca tz-aware UTC datetime
- Postgres TIMESTAMP WITHOUT TIME ZONE columns trzymaja UTC ale strip'uja
  tzinfo przy read'cie -> SQLAlchemy zwraca naive datetime
- datetime.isoformat() na naive datetime daje '2026-05-13T14:30:00' BEZ 'Z'
- JavaScript new Date('2026-05-13T14:30:00') interpretuje to jako LOKALNY
  czas browsera (np. UTC+2 dla PL) -> diff od now() = 2h jesli serwer UTC
- Wynik: "2h temu" na evencie ktory powstal 5s temu

Fix: kazdy datetime -> ISO suffix'em "+00:00" zeby Date.parse na froncie
wiedzialo ze to UTC.
"""
from __future__ import annotations

from datetime import datetime, timezone


def iso_utc(dt: datetime | None) -> str | None:
    """Zwraca ISO 8601 z explicit UTC suffix.

    None -> None.
    Naive datetime -> traktujemy jako UTC, dorzucamy tzinfo.
    Aware datetime (jakakolwiek strefa) -> przeliczamy na UTC.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # SQLAlchemy zwrocil naive z TIMESTAMP column - to ZAWSZE UTC bo my
        # zapisujemy utcnow() (tz-aware), Postgres strip'uje tylko tzinfo.
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        # Aware ale moze byc np. local - przelicz na UTC dla czystosci
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()
