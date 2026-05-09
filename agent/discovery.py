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

import httpx
from pydantic import BaseModel, Field

from core.config import settings
from core.llm import parse_structured
from core.urls import normalize_url as _normalize_url
from prompts.brand import BRAND_CONTEXT


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


# ---- Per-segment relevance hints --------------------------------------------
# Plain-language description of what each LeadSegment really means in business
# terms — used to anchor the LLM relevance filter so it can spot e.g. that a
# Kaufland is NOT a sklep plastyczny even though Google Maps loosely matched.
SEGMENT_DESCRIPTIONS: dict[str, str] = {
    "sklep_plastyczny": (
        "Sklep z artykułami plastycznymi i papierniczymi dla artystów, plastyków, "
        "uczniów i hobbystów: farby, pędzle, płótna, papiery, glina, materiały "
        "do rękodzieła, scrapbooking. NIE: supermarkety, apteki, sklepy "
        "medyczne, motoryzacyjne, AGD/RTV, ogólne sklepy przemysłowe, sklepy "
        "z zabawkami, zoologiczne."
    ),
    "paint_and_sip": (
        "Studio paint & sip / wieczory ze sztalugą — rozrywka, w której goście "
        "malują obraz przy lampce wina pod okiem instruktora. NIE: zwykłe "
        "kawiarnie, restauracje, sklepy z farbami."
    ),
    "warsztaty_dzieci": (
        "Firma prowadząca regularne warsztaty kreatywne, plastyczne, "
        "ceramiczne, artystyczne dla dzieci i młodzieży. NIE: szkoły publiczne, "
        "przedszkola, kluby sportowe, sklepy z zabawkami."
    ),
    "animatorzy_eventy": (
        "Animatorzy zabaw dziecięcych, organizatorzy urodzin i eventów dla "
        "dzieci, firmy eventowe robiące rękodzieło lub plastyczne aktywności. "
        "NIE: cateringi, sale weselne, fotografowie."
    ),
    "szkola_artystyczna": (
        "Szkoła plastyczna, artystyczna, pracownia malarstwa, kurs rysunku, "
        "ASP, prywatna szkoła sztuk pięknych. NIE: szkoły muzyczne, "
        "językowe, podstawowe."
    ),
    "marka_wlasna": (
        "Producent / marka oferująca produkty plastyczne/artystyczne pod własnym "
        "logo lub firma poszukująca dostawcy do white-label. NIE: ogólne sklepy."
    ),
    "inne": "Inny segment — oceniaj na podstawie nazwy i kategorii.",
}


# ---- Pydantic models for relevance batch ------------------------------------

class RelevanceItem(BaseModel):
    idx: int = Field(description="Indeks kandydata z listy wejściowej (0-based)")
    score: int = Field(description="Trafność 0-10 (10 = idealny lead, 0 = ewidentnie nie pasuje)")
    reason: str = Field(description="Krótkie uzasadnienie po polsku, max 1 zdanie")


class RelevanceBatch(BaseModel):
    items: list[RelevanceItem]


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


# ---- Apify base + actor-specific subclasses --------------------------------

def _apify_run_actor(actor_id: str, payload: dict, *, timeout: float = 180.0) -> list[dict]:
    """Hit Apify run-sync-get-dataset-items for the given actor and payload.
    Returns the raw dataset items list; caller normalizes per-actor."""
    token = _resolve_secret(settings.apify_api_token, "APIFY_API_TOKEN")
    if not token:
        raise RuntimeError("Brak APIFY_API_TOKEN.")
    url = f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, params={"token": token}, json=payload)
    response.raise_for_status()
    return response.json() or []


class ApifySource:
    """Apify Google Maps Scraper — best for local businesses with phone+website."""

    name = "apify"

    def available(self) -> bool:
        return has_apify_token()

    def search(self, *, query: str, max_results: int) -> list[DiscoveredPlace]:
        payload = {
            "searchStringsArray": [query],
            "maxCrawledPlacesPerSearch": min(max_results, 50),
            "language": "pl",
            "countryCode": "pl",
            "skipClosedPlaces": True,
        }
        data = _apify_run_actor(settings.apify_gmaps_actor, payload)
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


class ApifyAllegroSource:
    """Apify Allegro Scraper — finds sellers and offers on Allegro.pl.

    Useful for sourcing competitor sellers in plastic/art categories that we
    could approach for B2B / private label deals. Default actor configurable
    via APIFY_ALLEGRO_ACTOR (no widely-adopted "official" Allegro actor on
    the marketplace; user picks one from apify.com/store).
    """

    name = "apify_allegro"

    def available(self) -> bool:
        return has_apify_token() and bool(settings.apify_allegro_actor)

    def search(self, *, query: str, max_results: int) -> list[DiscoveredPlace]:
        payload = {
            "searchTerms": [query],
            "maxItems": min(max_results, 100),
        }
        data = _apify_run_actor(settings.apify_allegro_actor, payload)
        return [self._normalize(item) for item in data][:max_results]

    @staticmethod
    def _normalize(item: dict) -> DiscoveredPlace:
        seller = (
            item.get("sellerName")
            or item.get("seller", {}).get("login")
            or item.get("sellerLogin")
            or item.get("title")
            or "(sprzedawca Allegro)"
        )
        return DiscoveredPlace(
            source="apify_allegro",
            name=str(seller),
            website=item.get("sellerUrl")
            or item.get("seller", {}).get("url")
            or item.get("url"),
            address=item.get("location"),
            rating=item.get("sellerRating") or item.get("rating"),
            review_count=item.get("sellerFeedbackCount") or item.get("reviewCount"),
            raw_id=item.get("offerId") or item.get("id"),
            notes=item.get("category") or "Allegro listing",
        )


class ApifyLinkedInSource:
    """Apify LinkedIn Companies Scraper — discovers company profiles by query.

    Configure actor id via APIFY_LINKEDIN_ACTOR. Use cases: find Polish art
    supply distributors, paint & sip studios, art schools that publish on
    LinkedIn. Compliance note: ensure your Apify actor + LinkedIn usage
    follow LinkedIn TOS and your local outreach laws (GDPR).
    """

    name = "apify_linkedin"

    def available(self) -> bool:
        return has_apify_token() and bool(settings.apify_linkedin_actor)

    def search(self, *, query: str, max_results: int) -> list[DiscoveredPlace]:
        # LinkedIn actors usually accept either keyword search or company URL.
        # We pass the query as a search keyword; payload shape varies per actor
        # but most accept "queries" or "searchKeywords".
        payload = {
            "queries": [query],
            "searchKeywords": [query],
            "maxItems": min(max_results, 50),
        }
        data = _apify_run_actor(settings.apify_linkedin_actor, payload)
        return [self._normalize(item) for item in data][:max_results]

    @staticmethod
    def _normalize(item: dict) -> DiscoveredPlace:
        return DiscoveredPlace(
            source="apify_linkedin",
            name=item.get("name") or item.get("companyName") or item.get("title") or "(LinkedIn)",
            website=item.get("websiteUrl")
            or item.get("website")
            or item.get("url")
            or item.get("companyUrl"),
            address=item.get("headquarters") or item.get("location"),
            phone=item.get("phone"),
            raw_id=item.get("companyId") or item.get("id"),
            notes=item.get("industry") or item.get("description"),
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


# ---- Relevance filter (cheap LLM batch scoring) -----------------------------

def score_relevance_batch(
    places: list[DiscoveredPlace],
    *,
    segment: str,
    city: str | None = None,
    custom_description: str | None = None,
    provider: str = "gemini",
    model: str = "gemini-2.5-flash-lite",
) -> tuple[list[RelevanceItem], dict]:
    """Score relevance of every candidate against the target segment+city in
    a single LLM call. Returns (items, usage_dict).

    Default model is the cheapest available — this is meant to be run on
    20-50 candidates at a time and cost a fraction of a cent. The full
    research pipeline (research_and_save) is ~30x more expensive per lead,
    so filtering here saves both money and time.

    If `custom_description` is provided it overrides the preset segment
    definition — useful when the user types a free-form target like
    "producenci sztalug pod private label".
    """
    if not places:
        return [], {}

    if custom_description and custom_description.strip():
        target_label = "(własny target)"
        target_description = custom_description.strip()
    else:
        target_label = segment
        target_description = SEGMENT_DESCRIPTIONS.get(
            segment, SEGMENT_DESCRIPTIONS["inne"]
        )

    catalog_lines = []
    for i, p in enumerate(places):
        category = p.notes or "?"
        addr = p.address or "?"
        catalog_lines.append(f"[{i}] {p.name} | kategoria: {category} | adres: {addr}")
    catalog = "\n".join(catalog_lines)

    system = (
        f"{BRAND_CONTEXT}\n\n"
        "Jesteś bezlitosnym filtrem leadów dla agenta sprzedaży B2B Artmakera. "
        "Twoim zadaniem jest odsiać firmy, które nie pasują do zadanego segmentu "
        "ani do oferty Artmakera. Lepiej odrzucić wątpliwy lead niż zmarnować "
        "budżet research'u na ewidentny mismatch. Bądź surowy. Zwracasz wyłącznie "
        "poprawny JSON zgodny ze schematem."
    )
    city_clause = f"Miasto docelowe: {city}\n" if city else ""
    user = (
        f"Segment docelowy: {target_label}\n"
        f"Definicja targetu: {target_description}\n"
        f"{city_clause}\n"
        f"Kandydaci (idx | nazwa | kategoria | adres):\n{catalog}\n\n"
        "Dla KAŻDEGO kandydata zwróć obiekt {idx, score, reason}:\n"
        "- score 10 = idealny lead, dokładnie ten typ firmy + pasuje do oferty Artmakera\n"
        "- score 7-9 = bardzo prawdopodobny lead, warto zresearchować\n"
        "- score 4-6 = niepewny, potencjalnie pasuje ale ryzyko mismatch\n"
        "- score 1-3 = ewidentnie nie pasuje (inna branża, inne miasto)\n"
        "- score 0 = na pewno śmieć (supermarket, apteka, motoryzacja itp.)\n"
        "Pisz reason po polsku, jedno krótkie zdanie. Zwróć WSZYSTKIE indeksy."
    )

    parsed, usage = parse_structured(
        system=system,
        user=user,
        output_schema=RelevanceBatch,
        provider=provider,
        model=model,
        max_tokens=4096,
    )
    return parsed.items, usage
