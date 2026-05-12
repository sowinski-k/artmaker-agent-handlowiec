"""Geo-filter dla DiscoveredPlace.

Problem: Apify/Google zwracają miejsca z całej Polski mimo `query` typu
"sklep plastyczny Kraków". User chce TYLKO Krakow -> dropujemy reszte zanim
wyślemy do LLM scoring (~$0.001/lead) albo research (~$0.005/lead).

Strategia:
  1. Substring match nazwy miasta w address (po normalizacji - lowercase,
     bez polskich znakow).
  2. Postal-code prefix match dla TOP-30 miast PL (np. "00-001" -> Warszawa,
     "30-XXX" -> Krakow). Lapie sytuacje gdy nazwa miasta jest pisana inaczej
     lub w skrocie.
  3. Brak address -> include (niepewnosc, lepiej puscic dalej niz odrzucic).

Nie potrzebujemy mega-precyzji - to filtr "od grubego". Reszte zalatwi
LLM relevance scoring i research.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

log = logging.getLogger("ecombinat.geo_filter")

# Mapa: ascii city name -> lista prefixow kodu pocztowego (pierwsze 2 cyfry).
# Zrodlo: Poczta Polska KPP. Tylko top miasta gdzie scope wystepuje.
CITY_POSTAL_PREFIXES: dict[str, list[str]] = {
    "warszawa": ["00", "01", "02", "03", "04"],
    "krakow": ["30", "31"],
    "lodz": ["90", "91", "92", "93", "94"],
    "wroclaw": ["50", "51", "52", "53", "54"],
    "poznan": ["60", "61"],
    "gdansk": ["80"],
    "szczecin": ["70", "71"],
    "bydgoszcz": ["85", "86"],
    "lublin": ["20"],
    "katowice": ["40"],
    "bialystok": ["15", "16"],
    "gdynia": ["81"],
    "czestochowa": ["42"],
    "radom": ["26"],
    "torun": ["87"],
    "sosnowiec": ["41"],
    "rzeszow": ["35"],
    "kielce": ["25"],
    "gliwice": ["44"],
    "zabrze": ["41"],
    "olsztyn": ["10", "11"],
    "bielsko-biala": ["43"],
    "bytom": ["41"],
    "ruda slaska": ["41"],
    "rybnik": ["44"],
    "tychy": ["43"],
    "dabrowa gornicza": ["41"],
    "plock": ["09"],
    "elblag": ["82"],
    "opole": ["45", "46"],
    "tarnow": ["33"],
    "gorzow wielkopolski": ["66"],
    "wloclawek": ["87"],
    "koszalin": ["75"],
    "kalisz": ["62"],
    "legnica": ["59"],
    "grudziadz": ["86"],
    "slupsk": ["76"],
    "jaworzno": ["43"],
    "jastrzebie-zdroj": ["44"],
    "nowy sacz": ["33"],
    "siedlce": ["08"],
    "pila": ["64"],
    "lomza": ["18"],
    "ostrowiec swietokrzyski": ["27"],
    "stargard": ["73"],
    "swidnica": ["58"],
    "pabianice": ["95"],
    "konin": ["62"],
    "leszno": ["64"],
    "suwalki": ["16"],
    "chorzow": ["41"],
    "zielona gora": ["65"],
    "lubin": ["59"],
    "miedzyrzec podlaski": ["21"],
    "starachowice": ["27"],
    "pruszkow": ["05"],
    "ostrow wielkopolski": ["63"],
    "stalowa wola": ["37"],
    "tczew": ["83"],
    "biala podlaska": ["21"],
    "tomaszow mazowiecki": ["97"],
    "chelm": ["22"],
    "klodzko": ["57"],
    "mielec": ["39"],
    "kedzierzyn-kozle": ["47"],
    "przemysl": ["37"],
    "zamosc": ["22"],
    "swinoujscie": ["72"],
    "olawa": ["55"],
    "krosno": ["38"],
    "piotrkow trybunalski": ["97"],
    "skierniewice": ["96"],
    "inowroclaw": ["88"],
}

# Mapa polskich znakow na ascii. Trzymamy lokalnie zeby uniknac unidecode dependency.
_PL_DIACRITICS = str.maketrans({
    "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n",
    "ó": "o", "ś": "s", "ź": "z", "ż": "z",
    "Ą": "a", "Ć": "c", "Ę": "e", "Ł": "l", "Ń": "n",
    "Ó": "o", "Ś": "s", "Ź": "z", "Ż": "z",
})

# PL postal code: XX-XXX
_POSTAL_RE = re.compile(r"\b(\d{2})-(\d{3})\b")


def normalize_city(s: str) -> str:
    """Lowercase + remove polish diacritics + collapse whitespace."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", s.translate(_PL_DIACRITICS).lower().strip())


def extract_postal_prefix(address: str) -> str | None:
    """Wyciagnij pierwsze 2 cyfry kodu pocztowego z adresu, jesli jest."""
    if not address:
        return None
    m = _POSTAL_RE.search(address)
    return m.group(1) if m else None


@dataclass
class GeoMatch:
    matched: bool
    reason: str  # "city_substring", "postal_prefix", "no_address", "rejected"


def matches_city(address: str | None, city: str) -> GeoMatch:
    """Czy address pasuje do city. Polityka:
      1. Brak address -> matched=True (no_address) - bo nie wiemy, lepiej puscic.
      2. Brak city wymaganego -> matched=True (no requirement).
      3. Normalized city substring w normalized address -> match.
      4. Postal prefix z address matchuje listę dla city -> match.
      5. Else -> rejected.
    """
    if not city:
        return GeoMatch(True, "no_requirement")
    if not address:
        return GeoMatch(True, "no_address")

    city_n = normalize_city(city)
    addr_n = normalize_city(address)

    # Substring check
    if city_n and city_n in addr_n:
        return GeoMatch(True, "city_substring")

    # Postal prefix check - tylko jesli mamy mape dla tego miasta
    prefixes = CITY_POSTAL_PREFIXES.get(city_n)
    if prefixes:
        postal_prefix = extract_postal_prefix(address)
        if postal_prefix and postal_prefix in prefixes:
            return GeoMatch(True, "postal_prefix")

    return GeoMatch(False, "rejected")


def filter_places_by_city(places, city: str | None) -> tuple[list, list]:
    """Splituj DiscoveredPlace na (matching, rejected) wzg. miasta.

    Jezeli city pusty -> wszystko matching. Niepewnosc (brak address) -> matching.
    """
    if not city:
        return list(places), []

    matching, rejected = [], []
    for p in places:
        addr = getattr(p, "address", None)
        m = matches_city(addr, city)
        if m.matched:
            matching.append(p)
        else:
            rejected.append(p)

    log.info(
        f"geo_filter city={city!r}: {len(matching)} match, {len(rejected)} rejected "
        f"(z {len(matching) + len(rejected)} total)"
    )
    return matching, rejected
