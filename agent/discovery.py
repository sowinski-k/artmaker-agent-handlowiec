"""Lead discovery: pluggable sources that find businesses to research.

Three sources are supported, all optional and independent:
    - ApifySource: Apify Google Maps Scraper actor (paid, ~$5/1000)
    - GooglePlacesSource: Google Places API (New) Text Search (paid, ~$25-32/1000)
    - CSVSource: import URL list from a user-uploaded CSV (free)

Sources can be run in parallel (`run_search`) and the merged results are
deduplicated by website URL so you don't research the same lead twice.
"""
from __future__ import annotations

import csv
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, Protocol
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from core.config import settings


class DiscoveredPlace(BaseModel):
    """A lead candidate produced by some source. Matches the bare minimum we
    need to send the URL into research_and_save()."""

    source: str  # "apify" | "google_places" | "csv"
    name: str
    website: str | None = None
    address: str | None = None
    phone: str | None = None
    rating: float | None = None
    review_count: int | None = None
    raw_id: str | None = None
    notes: str | None = None


class SourceResult(BaseModel):
    source: str
    places: list[DiscoveredPlace] = Field(default_factory=list)
    error: str | None = None
    duration_s: float | None = None


# ---- Secret resolution (env first, Streamlit secrets as fallback) -----------

def _resolve_secret(env_value: str, secret_key: str) -> str:
    if env_value:
        return env_value
    try:
        import streamlit as st  # type: ignore[import-not-found]

        if hasattr(st, "secrets") and secret_key in st.secrets:
            return str(st.secrets[secret_key])
    except Exception:
        pass
    return ""


def has_apify_token() -> bool:
    return bool(_resolve_secret(settings.apify_api_token, "APIFY_API_TOKEN"))


def has_places_key() -> bool:
    return bool(_resolve_secret(settings.google_places_api_key, "GOOGLE_PLACES_API_KEY"))


# ---- Source protocol --------------------------------------------------------

class LeadSource(Protocol):
    name: str

    def available(self) -> bool: ...
    def search(self, *, query: str, max_results: int) -> list[DiscoveredPlace]: ...


# ---- Apify Google Maps Scraper ---------------------------------------------

class ApifySource:
    """Wraps Apify's run-sync-get-dataset-items endpoint for the configured
    Google Maps actor."""

    name = "apify"

    def available(self) -> bool:
        return has_apify_token()

    def search(self, *, query: str, max_results: int) -> list[DiscoveredPlace]:
        token = _resolve_secret(settings.apify_api_token, "APIFY_API_TOKEN")
        if not token:
            raise RuntimeError("Brak APIFY_API_TOKEN.")

        actor = settings.apify_gmaps_actor
        url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
        payload = {
            "searchStringsArray": [query],
            "maxCrawledPlacesPerSearch": min(max_results, 50),
            "language": "pl",
            "countryCode": "pl",
            "skipClosedPlaces": True,
        }
        with httpx.Client(timeout=180.0) as client:
            response = client.post(url, params={"token": token}, json=payload)
        response.raise_for_status()
        data = response.json()
        return [self._normalize(item) for item in data][:max_results]

    @staticmethod
    def _normalize(item: dict) -> DiscoveredPlace:
        return DiscoveredPlace(
            source="apify",
            name=item.get("title") or item.get("name") or "(bez nazwy)",
            website=item.get("website") or None,
            address=item.get("address") or None,
            phone=item.get("phone") or None,
            rating=item.get("totalScore"),
            review_count=item.get("reviewsCount"),
            raw_id=item.get("placeId") or item.get("id"),
            notes=item.get("categoryName"),
        )


# ---- Google Places API (New) ------------------------------------------------

class GooglePlacesSource:
    """Google Places API (New) Text Search v1 with field mask."""

    name = "google_places"
    _ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
    _FIELD_MASK = (
        "places.id,places.displayName,places.websiteUri,places.formattedAddress,"
        "places.internationalPhoneNumber,places.rating,places.userRatingCount,"
        "places.businessStatus,places.primaryTypeDisplayName"
    )

    def available(self) -> bool:
        return has_places_key()

    def search(self, *, query: str, max_results: int) -> list[DiscoveredPlace]:
        api_key = _resolve_secret(settings.google_places_api_key, "GOOGLE_PLACES_API_KEY")
        if not api_key:
            raise RuntimeError("Brak GOOGLE_PLACES_API_KEY.")

        headers = {
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": self._FIELD_MASK,
            "Content-Type": "application/json",
        }
        payload = {
            "textQuery": query,
            "languageCode": "pl",
            "regionCode": "PL",
            "maxResultCount": min(max_results, 20),
        }
        with httpx.Client(timeout=30.0) as client:
            response = client.post(self._ENDPOINT, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        return [self._normalize(p) for p in data.get("places", [])]

    @staticmethod
    def _normalize(p: dict) -> DiscoveredPlace:
        display = p.get("displayName") or {}
        category = p.get("primaryTypeDisplayName") or {}
        status = p.get("businessStatus")
        return DiscoveredPlace(
            source="google_places",
            name=display.get("text") or "(bez nazwy)",
            website=p.get("websiteUri"),
            address=p.get("formattedAddress"),
            phone=p.get("internationalPhoneNumber"),
            rating=p.get("rating"),
            review_count=p.get("userRatingCount"),
            raw_id=p.get("id"),
            notes=(category.get("text") if category else None) or status,
        )


# ---- CSV import -------------------------------------------------------------

class CSVSource:
    """In-memory CSV parser. Caller passes raw bytes; we accept the column
    "url" (required) and any of "name", "city", "address", "phone".
    """

    name = "csv"

    def __init__(self, csv_bytes: bytes | None = None) -> None:
        self.csv_bytes = csv_bytes

    def available(self) -> bool:
        return self.csv_bytes is not None

    def search(self, *, query: str, max_results: int) -> list[DiscoveredPlace]:
        if not self.csv_bytes:
            return []
        text = self.csv_bytes.decode("utf-8-sig", errors="replace")
        # Try comma first, fall back to semicolon (Polish Excel default).
        sample = text[:4096]
        delim = ";" if sample.count(";") > sample.count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delim)
        results: list[DiscoveredPlace] = []
        for row in reader:
            url = (row.get("url") or row.get("URL") or row.get("website") or "").strip()
            if not url:
                continue
            results.append(
                DiscoveredPlace(
                    source="csv",
                    name=(row.get("name") or row.get("Nazwa") or "").strip() or url,
                    website=url,
                    address=(row.get("address") or row.get("Adres") or None),
                    phone=(row.get("phone") or row.get("Telefon") or None),
                    notes=(row.get("notes") or None),
                )
            )
            if len(results) >= max_results:
                break
        return results


# ---- Parallel runner --------------------------------------------------------

def _normalize_url(u: str) -> str:
    """Loose dedup key for websites: scheme-stripped host + path, trailing
    slash dropped, lowercased."""
    if not u:
        return ""
    try:
        parsed = urlparse(u if "://" in u else f"http://{u}")
        host = (parsed.netloc or parsed.path or "").lower().lstrip("www.")
        path = parsed.path.rstrip("/") if parsed.netloc else ""
        return f"{host}{path}"
    except Exception:
        return u.strip().lower().rstrip("/")


def run_search(
    sources: Iterable[LeadSource],
    *,
    query: str,
    max_results_per_source: int = 20,
    progress_callback: Callable[[str, str], None] | None = None,
) -> tuple[list[DiscoveredPlace], list[SourceResult]]:
    """Run all enabled sources in parallel; return deduplicated places + per-source diagnostics."""
    import time

    sources = [s for s in sources if s.available()]
    if not sources:
        return [], []

    def _run_one(src: LeadSource) -> SourceResult:
        if progress_callback:
            progress_callback(src.name, "started")
        t0 = time.time()
        try:
            places = src.search(query=query, max_results=max_results_per_source)
            return SourceResult(
                source=src.name, places=places, duration_s=round(time.time() - t0, 2)
            )
        except Exception as exc:
            return SourceResult(
                source=src.name, error=str(exc), duration_s=round(time.time() - t0, 2)
            )
        finally:
            if progress_callback:
                progress_callback(src.name, "done")

    results: list[SourceResult] = []
    with ThreadPoolExecutor(max_workers=len(sources)) as executor:
        futures = {executor.submit(_run_one, s): s for s in sources}
        for future in as_completed(futures):
            results.append(future.result())

    seen: dict[str, DiscoveredPlace] = {}
    for r in results:
        for place in r.places:
            key = _normalize_url(place.website or "") or f"{r.source}:{place.raw_id or place.name}"
            if key in seen:
                # Prefer entries that have website + more rating info.
                existing = seen[key]
                if not existing.website and place.website:
                    seen[key] = place
                elif (place.review_count or 0) > (existing.review_count or 0):
                    seen[key] = place
            else:
                seen[key] = place
    return list(seen.values()), results
