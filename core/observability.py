"""Observability: Sentry init + heartbeat helpers.

Sentry: opt-in przez env var SENTRY_DSN. Brak DSN -> no-op (nic nie wysyla).
Aktywne na obu service'ach (web + worker) zeby kazdy exception lapal.

Heartbeat: worker co WORKER_HEARTBEAT_S sekund pisze Event(type='worker.heartbeat')
do bazy. Backend ma endpoint /api/_health/worker ktory sprawdza czy ostatni
heartbeat <2 min temu - jak nie, worker padl (alert).
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("ecombinat.observability")


def init_sentry(component: str) -> bool:
    """Inicjalizuj Sentry SDK jesli SENTRY_DSN ustawione.

    component: 'web' | 'worker' (tag dla rozroznienia w UI Sentry)
    Zwraca True jesli aktywowane.
    """
    dsn = (os.getenv("SENTRY_DSN") or "").strip()
    if not dsn:
        log.info(f"Sentry: skipped (no SENTRY_DSN) for component={component}")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        log.warning("Sentry: sentry_sdk not installed, skipping")
        return False

    environment = (
        os.getenv("SENTRY_ENVIRONMENT")
        or ("production" if os.getenv("RAILWAY_ENVIRONMENT") else "development")
    )
    release = os.getenv("SENTRY_RELEASE") or os.getenv("RAILWAY_GIT_COMMIT_SHA") or None
    # Sampling: 100% errorow, 10% performance traces (taniej w wolumenie)
    traces_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1"))

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        traces_sample_rate=traces_rate,
        # Lapie WARNING+ jako breadcrumbs, ERROR+ jako events
        integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)],
        # Nie wysylaj zmiennych srodowiskowych ani body requestu (PII)
        send_default_pii=False,
    )
    sentry_sdk.set_tag("component", component)
    log.info(f"Sentry: initialized for component={component} env={environment}")
    return True
