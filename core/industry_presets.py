"""Industry presets - mapowanie naszego LeadSegment na konkretne źródła
discovery (Allegro kategorie + keywords + filtry skali).

Dodanie nowej branży = nowy wpis tutaj. Kod (discovery, frontend) odczytuje
ten słownik dynamicznie i nie musi być modyfikowany.

Schema per branża:
    allegro_categories: list[str]  - URL kategorii Allegro do searchu po URL
    allegro_keywords: list[str]    - search terms (wyrażenia typu człowiek wpisuje)
    min_reviews: int               - filtr skali (sprzedawca z <N opinii jest skip'owany)
    min_rating: float              - filtr jakości (sprzedawca <rating jest skip'owany)
    label: str                     - user-facing nazwa (dla GUI dropdown)
"""
from __future__ import annotations

from typing import TypedDict


class IndustryPreset(TypedDict):
    label: str
    allegro_categories: list[str]
    allegro_keywords: list[str]
    min_reviews: int
    min_rating: float


# Mapowanie LeadSegment -> preset. Klucze pokrywaja sie z core.db.LeadSegment
# values, dzieki czemu mozemy poslawac jeden segment do roznych zrodel
# (Google Places, Allegro, LinkedIn) w jednym requescie.
INDUSTRY_PRESETS: dict[str, IndustryPreset] = {
    "sklep_plastyczny": {
        "label": "Sklepy plastyczne / artystyczne",
        "allegro_categories": [
            "https://allegro.pl/kategoria/sztuki-piekne-malarstwo-3148",
            "https://allegro.pl/kategoria/artykuly-plastyczne-99021",
        ],
        "allegro_keywords": [
            "farby akrylowe hurt",
            "plotna malarskie hurt",
            "pedzle artystyczne",
            "sztaluga malarska",
        ],
        "min_reviews": 50,
        "min_rating": 4.3,
    },
    "sklep_papierniczy": {
        "label": "Sklepy papiernicze",
        "allegro_categories": [
            "https://allegro.pl/kategoria/artykuly-biurowe-i-papiernicze-22011",
            "https://allegro.pl/kategoria/scrapbooking-31588",
        ],
        "allegro_keywords": [
            "papier scrapbookowy hurt",
            "washi tape",
            "stempelki kreatywne",
            "dziurkacze ozdobne",
        ],
        "min_reviews": 50,
        "min_rating": 4.3,
    },
    "paint_and_sip": {
        "label": "Paint & sip / wieczory artystyczne",
        "allegro_categories": [],  # paint & sip nie ma natywnej kategorii allegro
        "allegro_keywords": [
            "warsztaty malarstwa",
            "paint and sip",
            "wieczor ze sztaluga",
        ],
        "min_reviews": 10,  # nisze - mniej opinii
        "min_rating": 4.0,
    },
    "warsztaty_dzieci": {
        "label": "Warsztaty kreatywne dla dzieci",
        "allegro_categories": [],
        "allegro_keywords": [
            "warsztaty plastyczne dzieci",
            "zajecia kreatywne",
            "kursy malarstwa dla dzieci",
        ],
        "min_reviews": 10,
        "min_rating": 4.0,
    },
    "animatorzy_eventy": {
        "label": "Animatorzy / eventy kreatywne",
        "allegro_categories": [],
        "allegro_keywords": [
            "animator zabaw dziecięcych",
            "organizacja urodzin",
            "eventy kreatywne firma",
        ],
        "min_reviews": 5,
        "min_rating": 4.0,
    },
    "szkola_artystyczna": {
        "label": "Szkoły artystyczne / pracownie malarstwa",
        "allegro_categories": [],
        "allegro_keywords": [
            "kurs rysunku",
            "szkola plastyczna",
            "pracownia malarstwa",
        ],
        "min_reviews": 5,
        "min_rating": 4.2,
    },
    "marka_wlasna": {
        "label": "Marki własne / OEM (twórcy zestawów)",
        "allegro_categories": [
            "https://allegro.pl/kategoria/zestawy-malarskie-do-malowania-308434",
        ],
        "allegro_keywords": [
            "zestaw do malowania",
            "zestaw kreatywny DIY",
            "marka wlasna farby",
        ],
        "min_reviews": 30,
        "min_rating": 4.3,
    },
    "inne": {
        "label": "Inne",
        "allegro_categories": [],
        "allegro_keywords": [],
        "min_reviews": 0,
        "min_rating": 0.0,
    },
}


def get_preset(segment: str) -> IndustryPreset:
    """Zwraca preset dla segmentu albo 'inne' jako fallback."""
    return INDUSTRY_PRESETS.get(segment) or INDUSTRY_PRESETS["inne"]


def list_segments_with_presets() -> list[dict[str, str]]:
    """Lista (segment, label) - do dropdownu w GUI. Pomija 'inne'."""
    return [
        {"key": k, "label": v["label"]}
        for k, v in INDUSTRY_PRESETS.items()
        if k != "inne"
    ]
