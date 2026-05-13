"""Sentry init - no-op gdy brak DSN, aktywuje sie gdy DSN ustawione.

Kluczowy invariant: brak SENTRY_DSN NIE moze wywalic aplikacji. Wszystkie
deploye (dev, staging) bez DSN muszly nadal startowac.
"""
from __future__ import annotations

import os

from core.observability import init_sentry


def test_init_sentry_no_dsn_returns_false():
    """Bez DSN -> no-op, zwraca False, app sie nie wywala."""
    os.environ.pop("SENTRY_DSN", None)
    assert init_sentry("test") is False


def test_init_sentry_empty_dsn_returns_false():
    """Pusty DSN tez traktowany jak brak."""
    os.environ["SENTRY_DSN"] = ""
    try:
        assert init_sentry("test") is False
    finally:
        os.environ.pop("SENTRY_DSN", None)


def test_init_sentry_whitespace_dsn_returns_false():
    """Sam whitespace = brak."""
    os.environ["SENTRY_DSN"] = "   "
    try:
        assert init_sentry("test") is False
    finally:
        os.environ.pop("SENTRY_DSN", None)
