"""Testy query_expansion - generator wariacji query do omijania limitu 60.

Regression guard - poprzednie iteracje pokazaly ze API ma hard cap 60
wynikow per query, ale realnie firm w branzy mozemy miec 500+. Bez
expansion 80% przestrzeni jest dla nas niedostepne.
"""
from __future__ import annotations

from core.query_expansion import (
    CITY_DISTRICTS,
    SEGMENT_SYNONYMS,
    expand_query,
)


class TestSegmentSynonyms:
    def test_all_segments_have_synonyms(self):
        # Wszystkie LeadSegment values powinny mieć synonimy lub fallback do "inne"
        # Bez synonimow expansion nie zadziala dla tego segmentu
        assert len(SEGMENT_SYNONYMS) >= 5
        for segment, syns in SEGMENT_SYNONYMS.items():
            assert len(syns) >= 1, f"Segment {segment} has no synonyms"
            assert all(isinstance(s, str) and s.strip() for s in syns)


class TestCityDistricts:
    def test_warszawa_has_districts(self):
        assert "Warszawa" in CITY_DISTRICTS
        assert len(CITY_DISTRICTS["Warszawa"]) >= 10  # min 10 dzielnic

    def test_top_cities_present(self):
        # Top 6 miast PL musi byc - bez nich expansion dla nich = tylko synonimy
        for city in ["Warszawa", "Krakow", "Lodz", "Wroclaw", "Poznan", "Gdansk"]:
            assert city in CITY_DISTRICTS, f"{city} missing from CITY_DISTRICTS"


class TestExpandQuery:
    def test_warszawa_papierniczy_generates_max_variants(self):
        # Warszawa ma 17 dzielnic, 7 synonimow papierniczy -> dużo wariantow
        result = expand_query("sklep_papierniczy", "Warszawa", max_variants=30)
        assert len(result) == 30  # hit cap
        # Pierwszy element to "base" query (synonim + miasto)
        first_q, first_loc = result[0]
        assert "Warszawa" in first_q
        assert first_loc == "Warszawa"

    def test_small_city_no_districts_only_synonyms(self):
        # Kutno nie ma w CITY_DISTRICTS - tylko synonimy
        result = expand_query("sklep_papierniczy", "Kutno", max_variants=30)
        # 7 synonimow papierniczy
        assert 5 <= len(result) <= 7
        for q, loc in result:
            assert "Kutno" in q
            assert loc == "Kutno"

    def test_no_location_uses_only_synonyms(self):
        result = expand_query("sklep_plastyczny", None, max_variants=30)
        assert len(result) >= 5
        for q, loc in result:
            assert loc is None  # brak miasta = brak loc
            q_lower = q.lower()
            # Synonimy dla sklep_plastyczny zawieraja polskie znaki -
            # sprawdzamy zarowno polskie jak i bez-ogonkowe formy
            assert any(s in q_lower for s in [
                "sklep", "artyk", "malar", "farby", "material",
                "materiał",  # polska forma 'materialy' -> 'materiały'
            ])

    def test_unknown_segment_falls_back_to_inne(self):
        # Nieznany segment -> uzywa synonimow "inne"
        result = expand_query("nieznany_segment_xyz", "Krakow", max_variants=30)
        # "inne" ma 2 synonimy + Krakow dzielnice (12) = 2 + 24 = 26
        assert len(result) >= 2

    def test_max_variants_respected(self):
        # Warszawa x 7 synonimow x 17 dzielnic = 119 mozliwych
        result = expand_query("sklep_papierniczy", "Warszawa", max_variants=10)
        assert len(result) == 10

    def test_no_duplicate_variants(self):
        result = expand_query("sklep_papierniczy", "Warszawa", max_variants=50)
        keys = {f"{q}|{loc or ''}" for q, loc in result}
        assert len(keys) == len(result), "Found duplicate variants"

    def test_base_queries_first(self):
        # Pierwsze N wariantow (gdzie N=len(synonimow)) to base (synonim + miasto
        # bez dzielnicy). Potem dopiero dzielnice.
        synonyms = SEGMENT_SYNONYMS["sklep_papierniczy"]
        result = expand_query("sklep_papierniczy", "Warszawa", max_variants=30)
        for i, syn in enumerate(synonyms):
            q, loc = result[i]
            assert syn in q
            assert "Warszawa" in q
            # base queries nie maja dzielnicy w loc (tylko miasto)
            assert loc == "Warszawa"
