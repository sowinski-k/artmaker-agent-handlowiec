"""Top miast Polski - knowledge base dla discovery.

Lista ~100 najwiekszych miast PL z (nazwa, wojewodztwo, populacja).
Pokrywa ~80% populacji Polski. Wystarczajaco dla MVP "Polska-wide
discovery".

Plus 16 wojewodztw (VOIVODESHIPS) jako enum do filtrowania.

Frontend uzywa do dropdownu w `/pozyskiwanie`: user wybiera "Top 30
miast PL", "Wojewodztwo: malopolskie", albo wpisuje custom.

Backend uzywa w Fazie 3 (bulk discovery) do iteracji - "puszcz dla
top 50 miast" tworzy 50 jobow z odpowiednimi location.

Dane: GUS 2023+ approximations. Nie traktujemy populacji jako exact -
chodzi o relative ranking (Warszawa > Krakow > Lodz...).
"""
from __future__ import annotations

from typing import TypedDict


class City(TypedDict):
    name: str
    voivodeship: str
    population: int  # tysiace mieszkancow


# 16 wojewodztw + slug do filtrowania
VOIVODESHIPS: list[str] = [
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


# Top 100 miast PL po populacji (tysiace mieszkancow). Lista posortowana
# malejaco - pierwszy element to Warszawa (~1860k), ostatni okolo 30k.
CITIES_PL: list[City] = [
    {"name": "Warszawa", "voivodeship": "mazowieckie", "population": 1862},
    {"name": "Kraków", "voivodeship": "małopolskie", "population": 800},
    {"name": "Wrocław", "voivodeship": "dolnośląskie", "population": 672},
    {"name": "Łódź", "voivodeship": "łódzkie", "population": 658},
    {"name": "Poznań", "voivodeship": "wielkopolskie", "population": 533},
    {"name": "Gdańsk", "voivodeship": "pomorskie", "population": 487},
    {"name": "Szczecin", "voivodeship": "zachodniopomorskie", "population": 395},
    {"name": "Bydgoszcz", "voivodeship": "kujawsko-pomorskie", "population": 339},
    {"name": "Lublin", "voivodeship": "lubelskie", "population": 333},
    {"name": "Białystok", "voivodeship": "podlaskie", "population": 295},
    {"name": "Katowice", "voivodeship": "śląskie", "population": 286},
    {"name": "Gdynia", "voivodeship": "pomorskie", "population": 245},
    {"name": "Częstochowa", "voivodeship": "śląskie", "population": 213},
    {"name": "Radom", "voivodeship": "mazowieckie", "population": 201},
    {"name": "Toruń", "voivodeship": "kujawsko-pomorskie", "population": 198},
    {"name": "Sosnowiec", "voivodeship": "śląskie", "population": 192},
    {"name": "Rzeszów", "voivodeship": "podkarpackie", "population": 197},
    {"name": "Kielce", "voivodeship": "świętokrzyskie", "population": 190},
    {"name": "Gliwice", "voivodeship": "śląskie", "population": 174},
    {"name": "Olsztyn", "voivodeship": "warmińsko-mazurskie", "population": 169},
    {"name": "Bielsko-Biała", "voivodeship": "śląskie", "population": 168},
    {"name": "Zabrze", "voivodeship": "śląskie", "population": 167},
    {"name": "Bytom", "voivodeship": "śląskie", "population": 162},
    {"name": "Zielona Góra", "voivodeship": "lubuskie", "population": 141},
    {"name": "Opole", "voivodeship": "opolskie", "population": 127},
    {"name": "Tarnów", "voivodeship": "małopolskie", "population": 105},
    {"name": "Płock", "voivodeship": "mazowieckie", "population": 116},
    {"name": "Gorzów Wielkopolski", "voivodeship": "lubuskie", "population": 113},
    {"name": "Ruda Śląska", "voivodeship": "śląskie", "population": 132},
    {"name": "Elbląg", "voivodeship": "warmińsko-mazurskie", "population": 116},
    {"name": "Włocławek", "voivodeship": "kujawsko-pomorskie", "population": 105},
    {"name": "Tychy", "voivodeship": "śląskie", "population": 124},
    {"name": "Wałbrzych", "voivodeship": "dolnośląskie", "population": 109},
    {"name": "Dąbrowa Górnicza", "voivodeship": "śląskie", "population": 117},
    {"name": "Koszalin", "voivodeship": "zachodniopomorskie", "population": 105},
    {"name": "Kalisz", "voivodeship": "wielkopolskie", "population": 99},
    {"name": "Legnica", "voivodeship": "dolnośląskie", "population": 97},
    {"name": "Grudziądz", "voivodeship": "kujawsko-pomorskie", "population": 92},
    {"name": "Słupsk", "voivodeship": "pomorskie", "population": 90},
    {"name": "Jaworzno", "voivodeship": "śląskie", "population": 90},
    {"name": "Jastrzębie-Zdrój", "voivodeship": "śląskie", "population": 88},
    {"name": "Nowy Sącz", "voivodeship": "małopolskie", "population": 84},
    {"name": "Jelenia Góra", "voivodeship": "dolnośląskie", "population": 76},
    {"name": "Siedlce", "voivodeship": "mazowieckie", "population": 78},
    {"name": "Mysłowice", "voivodeship": "śląskie", "population": 73},
    {"name": "Konin", "voivodeship": "wielkopolskie", "population": 71},
    {"name": "Piła", "voivodeship": "wielkopolskie", "population": 72},
    {"name": "Piotrków Trybunalski", "voivodeship": "łódzkie", "population": 71},
    {"name": "Inowrocław", "voivodeship": "kujawsko-pomorskie", "population": 71},
    {"name": "Lubin", "voivodeship": "dolnośląskie", "population": 71},
    {"name": "Ostrów Wielkopolski", "voivodeship": "wielkopolskie", "population": 70},
    {"name": "Suwałki", "voivodeship": "podlaskie", "population": 69},
    {"name": "Stargard", "voivodeship": "zachodniopomorskie", "population": 67},
    {"name": "Gniezno", "voivodeship": "wielkopolskie", "population": 67},
    {"name": "Siemianowice Śląskie", "voivodeship": "śląskie", "population": 65},
    {"name": "Głogów", "voivodeship": "dolnośląskie", "population": 65},
    {"name": "Pabianice", "voivodeship": "łódzkie", "population": 64},
    {"name": "Leszno", "voivodeship": "wielkopolskie", "population": 63},
    {"name": "Zamość", "voivodeship": "lubelskie", "population": 62},
    {"name": "Łomża", "voivodeship": "podlaskie", "population": 62},
    {"name": "Żory", "voivodeship": "śląskie", "population": 61},
    {"name": "Pruszków", "voivodeship": "mazowieckie", "population": 63},
    {"name": "Tomaszów Mazowiecki", "voivodeship": "łódzkie", "population": 59},
    {"name": "Ełk", "voivodeship": "warmińsko-mazurskie", "population": 60},
    {"name": "Tarnowskie Góry", "voivodeship": "śląskie", "population": 60},
    {"name": "Mielec", "voivodeship": "podkarpackie", "population": 59},
    {"name": "Przemyśl", "voivodeship": "podkarpackie", "population": 59},
    {"name": "Stalowa Wola", "voivodeship": "podkarpackie", "population": 57},
    {"name": "Kędzierzyn-Koźle", "voivodeship": "opolskie", "population": 56},
    {"name": "Tczew", "voivodeship": "pomorskie", "population": 57},
    {"name": "Bełchatów", "voivodeship": "łódzkie", "population": 55},
    {"name": "Świdnica", "voivodeship": "dolnośląskie", "population": 55},
    {"name": "Biała Podlaska", "voivodeship": "lubelskie", "population": 54},
    {"name": "Mińsk Mazowiecki", "voivodeship": "mazowieckie", "population": 41},
    {"name": "Wejherowo", "voivodeship": "pomorskie", "population": 50},
    {"name": "Skierniewice", "voivodeship": "łódzkie", "population": 46},
    {"name": "Świnoujście", "voivodeship": "zachodniopomorskie", "population": 41},
    {"name": "Starachowice", "voivodeship": "świętokrzyskie", "population": 47},
    {"name": "Ostrowiec Świętokrzyski", "voivodeship": "świętokrzyskie", "population": 60},
    {"name": "Zgierz", "voivodeship": "łódzkie", "population": 56},
    {"name": "Krosno", "voivodeship": "podkarpackie", "population": 46},
    {"name": "Racibórz", "voivodeship": "śląskie", "population": 53},
    {"name": "Legionowo", "voivodeship": "mazowieckie", "population": 55},
    {"name": "Otwock", "voivodeship": "mazowieckie", "population": 45},
    {"name": "Piaseczno", "voivodeship": "mazowieckie", "population": 49},
    {"name": "Bolesławiec", "voivodeship": "dolnośląskie", "population": 38},
    {"name": "Chorzów", "voivodeship": "śląskie", "population": 105},
    {"name": "Świętochłowice", "voivodeship": "śląskie", "population": 49},
    {"name": "Knurów", "voivodeship": "śląskie", "population": 38},
    {"name": "Marki", "voivodeship": "mazowieckie", "population": 36},
    {"name": "Świecie", "voivodeship": "kujawsko-pomorskie", "population": 25},
    {"name": "Olkusz", "voivodeship": "małopolskie", "population": 35},
    {"name": "Cieszyn", "voivodeship": "śląskie", "population": 33},
    {"name": "Zakopane", "voivodeship": "małopolskie", "population": 27},
    {"name": "Sanok", "voivodeship": "podkarpackie", "population": 36},
    {"name": "Kołobrzeg", "voivodeship": "zachodniopomorskie", "population": 46},
    {"name": "Sopot", "voivodeship": "pomorskie", "population": 36},
    {"name": "Police", "voivodeship": "zachodniopomorskie", "population": 32},
    {"name": "Rumia", "voivodeship": "pomorskie", "population": 50},
    {"name": "Reda", "voivodeship": "pomorskie", "population": 27},
    {"name": "Żyrardów", "voivodeship": "mazowieckie", "population": 39},
    {"name": "Nysa", "voivodeship": "opolskie", "population": 42},
    {"name": "Chełm", "voivodeship": "lubelskie", "population": 60},
    {"name": "Lubliniec", "voivodeship": "śląskie", "population": 23},
]


def get_top_cities(n: int = 30) -> list[City]:
    """Zwraca top N miast po populacji."""
    return CITIES_PL[: max(1, n)]


def cities_in_voivodeship(voivodeship: str) -> list[City]:
    """Lista miast w danym wojewodztwie (case insensitive match)."""
    target = voivodeship.strip().lower()
    return [c for c in CITIES_PL if c["voivodeship"].lower() == target]


def city_names_only(cities: list[City]) -> list[str]:
    """Helper - zwraca tylko nazwy. Frontend uzywa do POST body."""
    return [c["name"] for c in cities]
