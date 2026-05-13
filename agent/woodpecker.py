"""Woodpecker.co API client.

Cienka warstwa nad REST API Woodpeckera. Trzy główne funkcje:

  - list_campaigns()        - pobiera listę kampanii (do dropdownu w GUI)
  - add_prospects(...)      - push prospects (drafftów) do wybranej kampanii;
                              Woodpecker startuje sekwencję follow-upów per
                              konfiguracji kampanii
  - get_prospect_statuses() - polling: jaki status mają nasze sent leady?
                              (REPLIED, BOUNCED, INTERESTED...)

Auth: header `x-api-key: <KEY>`. Rate limit Woodpeckera = 1 req/s, queue 6.
Robimy sync requests z httpx, jeden po drugim.

Docs (źródło prawdy): https://developers.woodpecker.co/docs/
"""
from __future__ import annotations

import time
from typing import Any, Iterable

import httpx
from pydantic import BaseModel, Field

from core.config import settings


# ---- Konfiguracja --------------------------------------------------------

WOODPECKER_BASE_V1 = "https://api.woodpecker.co/rest/v1"
WOODPECKER_BASE_V2 = "https://api.woodpecker.co/rest/v2"

# Rate limit: Woodpecker pozwala 1 req/s. Dla bezpieczeństwa robimy 1.2s pauzy.
_MIN_REQUEST_INTERVAL_S = 1.2
_last_request_at: float = 0.0


def _resolve_key() -> str:
    return settings.woodpecker_api_key or ""


def has_woodpecker_key() -> bool:
    return bool(_resolve_key())


# ---- Pydantic modele dla payloadów ---------------------------------------

class WoodpeckerCampaign(BaseModel):
    """Trimmed payload kampanii - wykorzystywane do dropdownu w GUI."""
    id: int
    name: str
    status: str | None = None  # RUNNING, PAUSED, STOPPED, DRAFT, EDITED


class WoodpeckerProspect(BaseModel):
    """Payload prospect'a do push'u. Wszystkie pola opcjonalne poza email."""
    email: str
    first_name: str | None = None
    last_name: str | None = None
    company: str | None = None
    title: str | None = None
    industry: str | None = None
    website: str | None = None
    phone: str | None = None
    city: str | None = None
    country: str | None = None
    # Snippets 1-15 - mapują się na placeholdery {{SNIPPET1}}..{{SNIPPET15}}
    # w template'ach kampanii Woodpeckera.
    snippet1: str | None = None
    snippet2: str | None = None
    snippet3: str | None = None
    snippet4: str | None = None
    snippet5: str | None = None
    snippet6: str | None = None  # zarezerwowany na subject (override w template)
    snippet7: str | None = None
    snippet8: str | None = None

    def to_woodpecker_dict(self) -> dict[str, Any]:
        """Drop None values - Woodpecker nie lubi explicit nulls w payload."""
        return {k: v for k, v in self.model_dump().items() if v is not None}


class WoodpeckerProspectStatus(BaseModel):
    """Skrót statusu prospect'a wracającego z Woodpeckera podczas polling."""
    email: str
    status: str  # ACTIVE, FINISHED, REPLIED, BOUNCED, BLACKLISTED, INTERESTED, NOT_INTERESTED
    interested: str | None = None  # NOT_MARKED, INTERESTED, MAYBE_LATER, NOT_INTERESTED
    last_event_at: str | None = None
    bounced: bool = False


# ---- Wewnętrzny request helper ------------------------------------------

class WoodpeckerError(RuntimeError):
    """Wszystkie błędy API podnosimy z konkretnym status code + body."""


def _request(method: str, url: str, *, json: dict | None = None, params: dict | None = None) -> dict | list:
    """Bazowy request z rate limit'em + jednolite obsłużenie błędów."""
    global _last_request_at
    api_key = _resolve_key()
    if not api_key:
        raise WoodpeckerError("Brak WOODPECKER_API_KEY (env var lub Streamlit secret).")

    # Rate limit guard: czekaj przed kolejnym requestem
    elapsed = time.monotonic() - _last_request_at
    if elapsed < _MIN_REQUEST_INTERVAL_S:
        time.sleep(_MIN_REQUEST_INTERVAL_S - elapsed)
    _last_request_at = time.monotonic()

    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    with httpx.Client(timeout=30.0) as client:
        try:
            response = client.request(method, url, headers=headers, json=json, params=params)
        except httpx.RequestError as exc:
            raise WoodpeckerError(f"Sieć padła wołając Woodpecker: {exc}") from exc

    if response.status_code >= 400:
        body_preview = response.text[:500]
        raise WoodpeckerError(
            f"Woodpecker {method} {url} → HTTP {response.status_code}: {body_preview}"
        )
    if response.status_code == 204 or not response.text:
        return {}
    try:
        return response.json()
    except ValueError:
        raise WoodpeckerError(
            f"Woodpecker zwrócił non-JSON (HTTP {response.status_code}): {response.text[:200]}"
        )


# ---- Public API ----------------------------------------------------------

def list_campaigns() -> list[WoodpeckerCampaign]:
    """Pobiera wszystkie kampanie konta. Wykorzystywane do dropdownu w GUI."""
    data = _request("GET", f"{WOODPECKER_BASE_V1}/campaign_list")
    if not isinstance(data, list):
        raise WoodpeckerError(f"campaign_list nie zwrócił listy: {type(data)}")
    return [
        WoodpeckerCampaign(
            id=int(c["id"]),
            name=str(c.get("name", "(bez nazwy)")),
            status=c.get("status"),
        )
        for c in data
        if "id" in c
    ]


def add_prospects(campaign_id: int, prospects: Iterable[WoodpeckerProspect]) -> dict:
    """Push jednego lub wielu prospects'ów do kampanii.

    Po stronie Woodpeckera:
    - jeśli prospect nie istnieje -> dodaje + startuje sekwencję
    - jeśli istnieje -> aktualizuje fields i statusy zgodnie z update=True
    - rate limit: 1 prospect = 1 request; możesz wysłać batch w jednym
      requestcie (max ~100 prospects wg docs)

    Returns: surowy response z Woodpeckera (zawiera prospect_ids itp.)
    """
    payload = {
        "campaign": {"campaign_id": int(campaign_id)},
        "update": True,
        "prospects": [p.to_woodpecker_dict() for p in prospects],
    }
    return _request(
        "POST", f"{WOODPECKER_BASE_V1}/add_prospects_campaign", json=payload
    )  # type: ignore[return-value]


def get_prospects_by_email(emails: Iterable[str]) -> list[WoodpeckerProspectStatus]:
    """Polling: pyta Woodpecker o statusy prospects po liście maili.

    Robimy w batchach - Woodpecker /prospects endpoint przyjmuje query params
    (email=X&email=Y...) ale lepiej jeden mail na request żeby uniknąć
    400-tek przy złych charakterach.
    """
    results: list[WoodpeckerProspectStatus] = []
    for email in emails:
        email = email.strip()
        if not email:
            continue
        try:
            data = _request(
                "GET",
                f"{WOODPECKER_BASE_V1}/prospects",
                params={"email": email},
            )
        except WoodpeckerError:
            # Pojedynczy mail się posypał - logujemy i jedziemy dalej
            continue
        rows = data if isinstance(data, list) else data.get("prospects", [])
        for row in rows:
            results.append(
                WoodpeckerProspectStatus(
                    email=row.get("email", email),
                    status=str(row.get("status", "UNKNOWN")),
                    interested=row.get("interested"),
                    last_event_at=row.get("last_event_time"),
                    bounced=bool(row.get("bounced", False)),
                )
            )
    return results
