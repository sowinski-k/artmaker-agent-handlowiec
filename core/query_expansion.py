"""Query expansion dla discovery - omija limit 60 wynikow per API call.

Problem: Google Places API ma hard cap 60 wynikow per query. Dla
"sklep papierniczy Warszawa" pokazuje 60 z ~500 ktore realnie istnieja.
Jak 30 to duplikaty z bazy, dostajemy 30 nowych mimo ze realnie 470
wciaz niesprawdzonych.

Rozwiazanie: generujemy wariacje query (semantyczne + geograficzne),
kazda zwraca do 60 swoich wynikow. Po dedupie po normalize_url(website)
dostajemy 5-8x wiecej unikalnych firm.

Przyklad dla "sklep_papierniczy Warszawa":
  - "sklep papierniczy Warszawa"       (base)
  - "papiernia Warszawa"               (synonym)
  - "artykuly biurowe Warszawa"        (broader)
  - "scrapbooking Warszawa"            (niche)
  - "sklep papierniczy Warszawa Mokotow"  (district)
  - "sklep papierniczy Warszawa Wola"     (district)
  - ...

Razem ~4 synonimy x 18 dzielnic = 72 queries.
"""
from __future__ import annotations

# Warianty semantyczne keyword'ow per segment. Pierwszy element to
# "canonical" wariant (uzywany przez fallback gdy nie ma w slowniku).
SEGMENT_SYNONYMS: dict[str, list[str]] = {
    "sklep_plastyczny": [
        "sklep plastyczny",
        "artykuly plastyczne",
        "artykuly malarskie",
        "sklep artystyczny",
        "sklep dla artystow",
        "farby akrylowe",
        "materialy plastyczne",
    ],
    "sklep_papierniczy": [
        "sklep papierniczy",
        "papiernia",
        "artykuly biurowe",
        "artykuly szkolne",
        "scrapbooking",
        "sklep biurowo-papierniczy",
        "sklep biurowy",
    ],
    "paint_and_sip": [
        "paint and sip",
        "malowanie z winem",
        "warsztaty malarstwa",
        "wieczor ze sztaluga",
        "studio malarskie",
    ],
    "warsztaty_dzieci": [
        "warsztaty plastyczne dla dzieci",
        "warsztaty kreatywne dla dzieci",
        "zajecia plastyczne",
        "pracownia dla dzieci",
        "atelier kreatywne",
    ],
    "animatorzy_eventy": [
        "animator zabaw dzieciecych",
        "organizator urodzin dla dzieci",
        "eventy kreatywne",
        "warsztaty rodzinne",
        "imprezy dla dzieci",
    ],
    "szkola_artystyczna": [
        "szkola plastyczna",
        "szkola artystyczna",
        "kurs rysunku",
        "kurs malarstwa",
        "pracownia malarstwa",
        "ognisko plastyczne",
    ],
    "marka_wlasna": [
        "producent zestawow malarskich",
        "marka wlasna farby",
        "producent artykulow plastycznych",
        "marka kreatywna",
    ],
    "inne": [
        "artykuly kreatywne",
        "sklep hobbystyczny",
    ],
}


# Dzielnice najwiekszych miast Polski. Per discovery dla danego miasta
# rozszerzamy query o kazda dzielnice (np. "sklep papierniczy Warszawa Mokotow").
# To pozwala kazdej dzielnicy dac swoje 60 wynikow.
#
# Lista nie wyczerpująca - top dzielnice z najwiekszą gęstością biznesu.
# Pełna lista jest w core/cities_pl.py (Faza 2).
CITY_DISTRICTS: dict[str, list[str]] = {
    "Warszawa": [
        "Mokotow", "Praga", "Wola", "Bemowo", "Bielany",
        "Ursynow", "Targowek", "Ochota", "Zoliborz", "Wlochy",
        "Wilanow", "Wesola", "Ursus", "Rembertow", "Wawer",
        "Bialoleka", "Srodmiescie",
    ],
    "Krakow": [
        "Stare Miasto", "Nowa Huta", "Krowodrza", "Podgorze",
        "Kazimierz", "Czyzyny", "Pradnik", "Bronowice", "Lagiewniki",
        "Mistrzejowice", "Bienczyce", "Zwierzyniec",
    ],
    "Lodz": [
        "Polesie", "Baluty", "Widzew", "Goerna", "Sródmiescie",
    ],
    "Wroclaw": [
        "Stare Miasto", "Sródmiescie", "Krzyki", "Fabryczna", "Psie Pole",
    ],
    "Poznan": [
        "Stare Miasto", "Nowe Miasto", "Grunwald", "Jezyce", "Wilda",
    ],
    "Gdansk": [
        "Sródmiescie", "Wrzeszcz", "Oliwa", "Stogi", "Brzezno",
        "Przymorze", "Zaspa",
    ],
    "Szczecin": [
        "Sródmiescie", "Pogodno", "Niebuszewo", "Pomorzany",
    ],
    "Bydgoszcz": [
        "Sródmiescie", "Fordon", "Wzgorze Wolnosci",
    ],
    "Lublin": [
        "Sródmiescie", "Wieniawa", "Czechow", "Bronowice",
    ],
    "Katowice": [
        "Sródmiescie", "Bogucice", "Zaleze", "Janow",
    ],
}


def expand_query(
    segment: str,
    location: str | None,
    *,
    max_variants: int = 30,
) -> list[tuple[str, str | None]]:
    """Wraca liste (query, location) wariacji do wyslania per source.

    Strategia:
      1. Bierz synonimy z SEGMENT_SYNONYMS (3-7 wariantow per segment)
      2. Dla kazdego synonimu:
         - jezeli location to duze miasto: dodaj per dzielnica
         - inaczej: dodaj tylko base (synonim + location)
      3. Cap na max_variants (ochrona budzetu - 30 queries x 60 wynikow
         = do 1800 firm potencjalnie po dedupie)

    Args:
      segment: LeadSegment value
      location: miasto / wojewodztwo / null
      max_variants: hard cap na liczbie zwroconych queries

    Returns:
      Lista (query_string, location_string|None) gotowa do wyslania.
      Pierwszy element to zawsze "base" (canonical query) - czyli to co
      uzytkownik wpisalby recznie.
    """
    synonyms = SEGMENT_SYNONYMS.get(segment) or SEGMENT_SYNONYMS["inne"]
    location_clean = (location or "").strip()

    # Czy location to miasto z dzielnicami w CITY_DISTRICTS?
    districts: list[str] = []
    if location_clean:
        for city_key, dst_list in CITY_DISTRICTS.items():
            if city_key.lower() == location_clean.lower():
                districts = dst_list
                break

    variants: list[tuple[str, str | None]] = []
    seen: set[str] = set()

    def _add(query: str, loc: str | None) -> None:
        key = f"{query}|{loc or ''}"
        if key in seen:
            return
        seen.add(key)
        variants.append((query, loc))

    # 1. Base queries: kazdy synonim + base location
    for syn in synonyms:
        full = syn if not location_clean else f"{syn} {location_clean}"
        _add(full, location_clean or None)
        if len(variants) >= max_variants:
            return variants

    # 2. Dla miast z dzielnicami: kazdy synonim x kazda dzielnica
    if districts:
        for syn in synonyms:
            for district in districts:
                full = f"{syn} {location_clean} {district}"
                _add(full, f"{location_clean} {district}")
                if len(variants) >= max_variants:
                    return variants

    return variants
