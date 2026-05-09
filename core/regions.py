"""Polskie regiony do lokalizacyjnego targetowania discovery.

Lista 16 województw + helper budujący frazę "miasto / województwo / cała
Polska" do wstrzyknięcia jako sufix do zapytania Google Places / Apify.
"""
from __future__ import annotations

WOJEWODZTWA: list[str] = [
    "dolnośląskie",
    "kujawsko-pomorskie",
    "lubelskie",
    "lubuskie",
    "łódzkie",
    "małopolskie",
    "mazowieckie",
    "opolskie",
    "podkarpackie",
    "podlaskie",
    "pomorskie",
    "śląskie",
    "świętokrzyskie",
    "warmińsko-mazurskie",
    "wielkopolskie",
    "zachodniopomorskie",
]


def location_phrase(mode: str, *, city: str = "", wojewodztwo: str = "") -> str:
    """Build the location suffix appended to the search phrase.

    mode is one of "Miasto", "Województwo", "Cała Polska". Returns "" when
    there's no useful location to add (e.g. mode=Miasto with empty city).
    """
    mode = (mode or "").strip()
    city = (city or "").strip()
    wojewodztwo = (wojewodztwo or "").strip()

    if mode == "Miasto":
        return city
    if mode == "Województwo":
        return f"województwo {wojewodztwo}" if wojewodztwo else ""
    if mode == "Cała Polska":
        return "Polska"
    return city


def location_label(mode: str, *, city: str = "", wojewodztwo: str = "") -> str:
    """Human-friendly label for prompts/logs."""
    phrase = location_phrase(mode, city=city, wojewodztwo=wojewodztwo)
    return phrase or "(brak lokalizacji)"
