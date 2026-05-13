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

    # Wypełniane przez mark_existing_in_db() PO mergu źródeł, PRZED filtrem
    # trafności LLM. Jeśli set: ten URL/firma jest już w bazie i nie powinniśmy
    # marnować tokenów na ponowne LLM scoring.
    existing_lead_id: int | None = None
    existing_lead_score: float | None = None


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
        "Sklep z artykułami plastycznymi i artystycznymi: farby, pędzle, płótna, "
        "sztalugi, glina, materiały do rękodzieła, scrapbooking. Stacjonarny lub "
        "e-commerce. Idealny lead Artmakera. NIE: supermarkety, apteki, sklepy "
        "medyczne, motoryzacyjne, AGD/RTV, zoologiczne, sklepy spożywcze."
    ),
    "sklep_papierniczy": (
        "Sklep papierniczy / biurowo-papierniczy / hobbystyczny mający w ofercie "
        "art. szkolne, biurowe, kreatywne, papier, długopisy, zeszyty + często "
        "też podstawowe artykuły plastyczne dla dzieci. Wartościowy lead dla "
        "Artmakera (Track B - panel B2B z magazynu, dostawa 24h, stała oferta "
        "produktów konsumpcyjnych). NIE: supermarkety, apteki, drukarnie "
        "wielkoformatowe, ksero/punkty xero bez sklepu."
    ),
    "paint_and_sip": (
        "Studio paint & sip / wieczory ze sztalugą - rozrywka gdzie goście "
        "malują obraz przy lampce wina pod okiem instruktora. NIE: zwykłe "
        "kawiarnie, restauracje, sklepy z farbami budowlanymi."
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
        "Producent / marka oferująca produkty plastyczne/artystyczne/papiernicze "
        "pod własnym logo lub firma poszukująca dostawcy do white-label / OEM. "
        "Idealny lead dla Track A (private label z Chin). NIE: ogólne sklepy "
        "bez własnej marki, dystrybutorzy bez aspiracji marki własnej."
    ),
    "inne": "Inny segment - oceniaj na podstawie nazwy i kategorii.",
}


# ---- Pydantic models for relevance batch ------------------------------------

class RelevanceItem(BaseModel):
    idx: int = Field(description="Indeks kandydata z listy wejściowej (0-based)")
    score: int = Field(description="Trafność 0-10 (10 = idealny lead, 0 = ewidentnie nie pasuje)")
    reason: str = Field(description="Krótkie uzasadnienie po polsku, max 1 zdanie")


class RelevanceBatch(BaseModel):
    items: list[RelevanceItem]


# ---- Secret resolution (env) ------------------------------------------------

def _resolve_secret(env_value: str, secret_key: str) -> str:
    return env_value or ""


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
        """Google Places Text Search NEW.

        Hard limit API: maxResultCount = 20 per request. Aby dostac wiecej,
        uzywamy paginacji przez `nextPageToken` z response - do 3 stron
        total (Google ogranicza tylko do 3 paged responses, max 60 wynikow).

        max_results > 60 zostanie scapowany do 60 (warning w log).
        """
        api_key = _resolve_secret(settings.google_places_api_key, "GOOGLE_PLACES_API_KEY")
        if not api_key:
            raise RuntimeError("Brak GOOGLE_PLACES_API_KEY.")

        headers = {
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": f"{self._FIELD_MASK},nextPageToken",
            "Content-Type": "application/json",
        }
        wanted = max(1, min(max_results, 60))
        per_page = min(wanted, 20)
        results: list[DiscoveredPlace] = []
        page_token: str | None = None

        with httpx.Client(timeout=30.0) as client:
            for page_idx in range(3):  # max 3 stron (Google API hard cap)
                payload: dict[str, object] = {
                    "textQuery": query,
                    "languageCode": "pl",
                    "regionCode": "PL",
                    "maxResultCount": per_page,
                }
                if page_token:
                    # Google wymaga ~2s pause przed page_token call
                    import time as _time
                    _time.sleep(2)
                    payload["pageToken"] = page_token
                response = client.post(self._ENDPOINT, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                places = data.get("places", []) or []
                for p in places:
                    results.append(self._normalize(p))
                    if len(results) >= wanted:
                        return results
                page_token = data.get("nextPageToken")
                if not page_token:
                    break  # brak kolejnej strony - mamy wszystko co Google ma
        return results

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
    workspace_id: int | None = None,
    city_filter: str | None = None,
) -> tuple[list[DiscoveredPlace], list[SourceResult]]:
    """Run all enabled sources in parallel; return deduplicated places + per-source diagnostics.

    city_filter: jezeli podane - dropuje places ktorych address nie pasuje do
    miasta (substring match po normalizacji, fallback na postal code prefix).
    Aplikuje sie PO mergu z roznych zrodel, PRZED mark_existing_in_db (oszczednosc
    SQL) i PRZED relevance scoring (oszczednosc LLM).
    """
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

    merged_places = list(seen.values())

    # Geo filter: dropuj wszystko z innego miasta zanim wydamy tokeny LLM.
    if city_filter:
        from agent.geo_filter import filter_places_by_city
        merged_places, _rejected = filter_places_by_city(merged_places, city_filter)

    # Mark places that are already in our leads DB - so downstream (relevance
    # filter, GUI) wie czego nie tknąć.
    mark_existing_in_db(merged_places, workspace_id=workspace_id)
    return merged_places, results


def mark_existing_in_db(places: list[DiscoveredPlace], workspace_id: int | None = None) -> None:
    """In-place: ustawia existing_lead_id i existing_lead_score na DiscoveredPlace
    których URL pasuje do istniejącego Lead w bazie.

    Jedno zapytanie SQL na cały batch (ILIKE po unikalnych hostach), potem
    weryfikacja przez normalize_url() w Pythonie. Skala: tysiące leadów w
    bazie = OK, bo ograniczamy zapytanie do hostów z aktualnej listy.

    workspace_id (opcjonalny): jeśli podany, dedup tylko per workspace - inaczej
    user widzi leady z cudzych workspace'ów jako "duplikaty".
    """
    if not places:
        return
    # Lokalne importy żeby uniknąć cyrkularnego importu (research -> discovery)
    from sqlalchemy import select, or_

    from core.db import Lead, SessionLocal
    from core.urls import host_only, normalize_url

    # Zbierz unikalne hosty z aktualnych places
    hosts_to_check: dict[str, list[DiscoveredPlace]] = {}
    for p in places:
        if not p.website:
            continue
        host = host_only(p.website)
        if host:
            hosts_to_check.setdefault(host, []).append(p)

    if not hosts_to_check:
        return

    # Chunking po hostach - duzy OR(*ILIKE) ma poor query plan w Postgres,
    # dzielimy na chunki po 20 hostow. Total queries = ceil(n_hosts/20) ale
    # kazda jest szybka (B-tree z OR=ILIKE wciaz seq-scan, ale na mniejszej batch).
    CHUNK = 20
    all_hosts = list(hosts_to_check.keys())
    rows: list[tuple[int, str | None, float | None]] = []
    with SessionLocal() as session:
        for i in range(0, len(all_hosts), CHUNK):
            chunk = all_hosts[i:i + CHUNK]
            conditions = [Lead.website.ilike(f"%{h}%") for h in chunk]
            q = select(Lead.id, Lead.website, Lead.score).where(
                Lead.website.isnot(None),
                or_(*conditions),
            )
            if workspace_id is not None:
                q = q.where(Lead.workspace_id == workspace_id)
            rows.extend(session.execute(q).all())

    # Mapuj DB rows -> DiscoveredPlace przez exact normalize_url match
    by_norm: dict[str, tuple[int, float | None]] = {
        normalize_url(website): (lead_id, score)
        for lead_id, website, score in rows
    }
    for p in places:
        if not p.website:
            continue
        norm = normalize_url(p.website)
        if norm in by_norm:
            p.existing_lead_id, p.existing_lead_score = by_norm[norm]


# ---- Relevance filter (cheap LLM batch scoring) -----------------------------

# Czarna lista keyword'ow w nazwie/kategorii - lapie firmy ktore JEDNOZNACZNIE
# nie pasuja do Artmaker (farby/plotna/papier/DIY). PRE-FILTER lokalny (bez LLM)
# = oszczednosc tokenow. Match na lowercase substring w nazwie+kategorii.
#
# WAZNE: tylko BARDZO PEWNE mismatch'e. Lepiej puscic do LLM ze szumem niz
# odrzucic dobry lead lokalnie. Stad ostre keyword'y typu "minecraft",
# "kulinarn", "fitness", a nie ogolne "warsztaty".
_HARD_MISMATCH_KEYWORDS = [
    # Tech / IT - nie nasz target
    'minecraft', 'programowani', 'koderz', 'koderk', 'koderyk',
    'scratch', 'python', 'arduino', 'roblox', 'robotyk',
    # Jezyki obce - inny rynek
    'jezyk angielski', 'jezyk niemieck', 'language school',
    'lektor', 'translator',
    # Sport / fitness / taniec - inny rynek
    'fitness', 'crossfit', 'silowni', 'siłowni',
    'joga ', ' joga', 'pilates', 'aerobik',
    'taniec', 'taneczn', 'baletow', 'akrobaty', 'gimnastyk',
    'sporto', 'futbol', 'pilkar', 'piłkar',
    # Kulinarn - inny rynek
    'kulinarn', 'gotowani', 'kucharsk', 'kuchni dziec',
    'smakuje', 'baking', 'cooking',
    # Beauty / health
    'fryzjer', 'kosmetyk', 'manicure', 'pedicure', 'spa ',
    'masaz', 'masaż', 'medycyn', 'stomatolog',
    # Muzyka
    'muzyczn', 'instrument', 'wokalist', 'piosenk', 'gitara',
    # Inne ewidentne off-topic
    'restaur', 'pizzeri', 'fastfood',
    'apteka', 'apteczn',
    'autoryzowany dealer', 'salonu samochod',
    'kantor', 'kantyna',
]


def _local_prefilter_score(place: 'DiscoveredPlace') -> tuple[int, str] | None:
    """Heurystyczny pre-filter - zwraca (score, reason) jesli ewidentny mismatch.
    None = przepuszczamy do LLM dla wlasciwej oceny.

    Match: lowercase substring w (name + notes + address). Sprawdzamy
    najpopularniejsze mismatch'e zeby NIE PALIC TOKENOW LLM dla firm
    ktore na 100% nie pasuja (Minecraft programowanie / kulinarne / fitness).
    """
    haystack = ' '.join([
        (place.name or '').lower(),
        (place.notes or '').lower(),
        (place.address or '').lower(),
    ])
    for kw in _HARD_MISMATCH_KEYWORDS:
        if kw in haystack:
            return (1, f"branża niepowiązana ({kw.strip()}) - off-target dla Artmakera")
    return None


# Pozytywne keyword'y - sugeruja ze firma DOBRZE pasuje. Uzywane jako
# heurystyczny fallback gdy LLM relevance call padnie (timeout / brak klucza /
# parse fail). Dziala lokalnie, bez tokenow.
_POSITIVE_KEYWORDS_WITH_SCORE: list[tuple[list[str], int, str]] = [
    # Score 8: bardzo wyrazne signaly Artmaker target
    (['plastyczn', 'malarsk', 'rysunek', 'artystyczn'], 8,
     "warsztaty plastyczne / artystyczne - idealny target"),
    (['scrapbook', 'rekodzieł', 'rękodzieł', 'handmade'], 8,
     "rekodzielo / scrapbooking - mocno plastyczny"),
    (['paint & sip', 'paint and sip', 'paint sip', 'malowanie z winem'], 8,
     "paint&sip - segment idealny"),
    # Score 7: dobre signaly
    (['kreatywn', 'creative'], 7, "warsztaty kreatywne"),
    (['ceramik', 'pottery'], 7, "ceramika - sasiedztwo branzy"),
    (['decoupage', 'mass plastyczn'], 7, "DIY / decoupage"),
    # Score 6: srednie - kandydat ale wymaga LLM
    (['warsztat', 'pracowni'], 6, "ogolne warsztaty - mozliwy target"),
    (['szkola artystyczn', 'ognisko plastyczn'], 7, "szkola plastyczna"),
    (['papierniczy', 'biurow', 'office supply'], 7, "papier/biuro - target"),
    (['sklep plastyczn', 'artystyczn', 'malarski'], 8,
     "sklep plastyczny / artystyczny - target"),
]


def _heuristic_score(place: 'DiscoveredPlace') -> tuple[int, str]:
    """Local fallback scoring uzywany gdy LLM relevance call padnie.
    Zwraca (score, reason) na podstawie keyword'ow w nazwie/notes/adres.

    NIE zastepuje LLM (LLM widzi kontekst, segment, custom_description), ale
    daje USER'OWI cos do roboty gdy LLM nie odpalil. Lepsze niz puste null
    ktore powodowalo 0-zaznaczonych w UI.
    """
    haystack = ' '.join([
        (place.name or '').lower(),
        (place.notes or '').lower(),
        (place.address or '').lower(),
    ])
    # Negatywne (hard mismatch) - score 1
    for kw in _HARD_MISMATCH_KEYWORDS:
        if kw in haystack:
            return (1, f"branża niepowiązana ({kw.strip()})")
    # Pozytywne - bierzemy najwyzszy match
    best_score = 0
    best_reason = ""
    for keywords, score, reason in _POSITIVE_KEYWORDS_WITH_SCORE:
        if any(k in haystack for k in keywords):
            if score > best_score:
                best_score = score
                best_reason = reason
    if best_score > 0:
        return (best_score, f"{best_reason} (heurystyka lokalna)")
    # Neutral fallback - nic nie wiemy
    return (5, "brak silnych sygnalow w nazwie - sprawdz recznie")


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

    # PRE-FILTER 1: nie scoruj dubli. Dla każdego place z existing_lead_id
    # syntetyzujemy RelevanceItem (score=existing_score lub 5 jeśli nieznany)
    # zamiast wysyłać do LLM. Reszta idzie do prawdziwego scoringu.
    #
    # PRE-FILTER 2: hard-mismatch keyword'y (Minecraft / kulinarn / fitness
    # itd.) tez nie ida do LLM - dostaja score=1 lokalnie. To oszczedza tokeny
    # gdy Google Places wciaga 50+ smieci typu "Programowanie Minecraft" dla
    # query "warsztaty dzieci".
    prefilter_items: list[RelevanceItem] = []
    fresh_indices: list[int] = []  # indeksy w `places` które idą do LLM
    for idx, p in enumerate(places):
        if p.existing_lead_id is not None:
            # Zachowaj score który Lead już ma w bazie (jeśli był researchowany),
            # albo dej 5 jako "neutralne" - user widzi że to dubel i decyduje sam.
            score_int = (
                int(round(p.existing_lead_score))
                if p.existing_lead_score is not None else 5
            )
            prefilter_items.append(RelevanceItem(
                idx=idx,
                score=max(0, min(10, score_int)),
                reason=f"Duplikat - już w bazie jako lead #{p.existing_lead_id}",
            ))
            continue

        # Hard-mismatch keyword check (PRE-FILTER 2)
        local = _local_prefilter_score(p)
        if local is not None:
            score, reason = local
            prefilter_items.append(RelevanceItem(
                idx=idx, score=score, reason=reason,
            ))
            continue

        fresh_indices.append(idx)

    # Jeśli wszystkie odfiltrowane - nic nie wysyłamy do LLM
    if not fresh_indices:
        return prefilter_items, {}

    if custom_description and custom_description.strip():
        target_label = "(własny target)"
        target_description = custom_description.strip()
    else:
        target_label = segment
        target_description = SEGMENT_DESCRIPTIONS.get(
            segment, SEGMENT_DESCRIPTIONS["inne"]
        )

    # Catalog tylko dla "fresh" - ale indeksy w prompcie muszą się mapować
    # z powrotem na oryginalne `places`, więc renumeruję i mapuję back.
    fresh_to_orig: dict[int, int] = {}  # local_idx -> orig_idx
    catalog_lines = []
    for local_idx, orig_idx in enumerate(fresh_indices):
        fresh_to_orig[local_idx] = orig_idx
        p = places[orig_idx]
        category = p.notes or "?"
        addr = p.address or "?"
        catalog_lines.append(f"[{local_idx}] {p.name} | kategoria: {category} | adres: {addr}")
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

    # Remap indeksy z lokalnych (LLM widział tylko fresh) na oryginalne
    remapped = [
        RelevanceItem(
            idx=fresh_to_orig.get(item.idx, item.idx),
            score=item.score,
            reason=item.reason,
        )
        for item in parsed.items
        if item.idx in fresh_to_orig
    ]
    return remapped + prefilter_items, usage
