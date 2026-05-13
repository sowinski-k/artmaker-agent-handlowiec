"""Smoke testy dla agent/generate - anti-AI-slop + Track A vs B logic.

Te testy bronia jakosci maili. Bez nich kazda zmiana prompt'u / regexp'u
moze niezauwazenie obnizyc jakosc na produkcji.
"""
from __future__ import annotations

from agent.generate import (
    EmailDraftPayload,
    _parse_volume_pln,
    _strip_ai_artifacts,
    _suggest_track_hint,
    validate_draft,
)


class TestPunctuation:
    def test_em_dash_to_hyphen(self):
        assert _strip_ai_artifacts("Tak — to ja") == "Tak - to ja"

    def test_en_dash_to_hyphen(self):
        assert _strip_ai_artifacts("Test – check") == "Test - check"

    def test_smart_double_quotes(self):
        assert _strip_ai_artifacts("„hello”") == '"hello"'

    def test_smart_single_quotes(self):
        # apostrof / pojedyncze cudzyslowy maja byc znormalizowane do ASCII
        cleaned = _strip_ai_artifacts("don’t")
        assert "'" in cleaned and "’" not in cleaned

    def test_idempotent(self):
        """Drugie wywolanie na juz zczyszczonym tekscie nic nie zmienia."""
        text = "Czesc — to test „cytat”"
        once = _strip_ai_artifacts(text)
        twice = _strip_ai_artifacts(once)
        assert once == twice


class TestAiCliches:
    def test_strips_pragne_poinformowac(self):
        out = _strip_ai_artifacts("Pragnę poinformować o naszej ofercie. Konkret.")
        assert "Pragnę" not in out
        assert "Konkret" in out

    def test_strips_w_dzisiejszych_czasach(self):
        out = _strip_ai_artifacts("W dzisiejszych czasach klienci szukają jakości.")
        assert "W dzisiejszych czasach" not in out

    def test_strips_korzystajac_z_okazji(self):
        out = _strip_ai_artifacts("Korzystając z okazji, chcę napisać. Tresc.")
        assert "Korzystając z okazji" not in out
        assert "Tresc" in out

    def test_strips_szanowni_panstwo(self):
        """Szanowni Panstwo to klasyczny AI-tell + korpo, musi zniknac."""
        out = _strip_ai_artifacts("Szanowni Państwo, mam pytanie.")
        assert "Szanowni Państwo" not in out
        assert "mam pytanie" in out

    def test_strips_buzzwords(self):
        """Rewolucyjny / innowacyjny / wyjątkowy - typowe AI-puste slowa."""
        for bw in ["rewolucyjny", "innowacyjny", "wyjątkowy", "unikatowy"]:
            out = _strip_ai_artifacts(f"Mamy {bw} produkt.")
            assert bw not in out.lower()

    def test_strips_lider_w_branzy(self):
        out = _strip_ai_artifacts("Jestesmy liderem w branzy artystycznej.")
        assert "lider" not in out.lower()

    def test_strips_pozwole_sobie(self):
        out = _strip_ai_artifacts("Pozwolę sobie zaproponować coś. Konkret.")
        assert "Pozwolę sobie" not in out
        assert "Konkret" in out

    def test_strips_dzien_dobry_opening(self):
        """Dzien dobry na poczatku - banalne AI opening."""
        out = _strip_ai_artifacts("Dzień dobry,\nNasza oferta jest świetna.")
        assert not out.lower().startswith("dzień dobry")

    def test_strips_pozdrawiam_serdecznie(self):
        out = _strip_ai_artifacts("Tresc maila.\nPozdrawiam serdecznie")
        assert "Pozdrawiam serdecznie" not in out

    def test_strips_z_poważaniem(self):
        out = _strip_ai_artifacts("Tresc.\nZ poważaniem.")
        assert "Z poważaniem" not in out


class TestSuggestTrackHint:
    """Sygnaly skali decyduja o Track A vs B - regresja zlamie Track A priority."""

    def test_marka_wlasna_zawsze_private_label(self):
        hint = _suggest_track_hint("marka_wlasna", None, None, None)
        assert "private_label" in hint
        assert "Track A" in hint

    def test_default_segmentu_to_private_label_not_b2b(self):
        """KRYTYCZNE (regression v2 dla Seneks-mailu): default to private_label
        NIE 'both' i NIE 'b2b_panel'. Maile typu Seneks mialy tylko Track B
        bo heurystyka pchala 'both' i LLM defaultowal do panel'a."""
        hint = _suggest_track_hint("sklep_papierniczy", None, None, None)
        # Nie b2b_panel
        assert not hint.startswith("b2b_panel")
        # Track A (private_label) GLOWNY
        assert "private_label" in hint
        # I to jako glowny pitch, nie marginalny
        assert ("GLOWNY" in hint or "pchamy" in hint
                or hint.startswith("private_label"))

    def test_high_bulk_potential_suggests_both_track_a(self):
        """bulk_potential=2 -> both z mocnym Track A signal."""
        hint = _suggest_track_hint("inne", None, 2.0, 1.0)
        assert hint.startswith("both")
        assert "skali" in hint.lower() or "PIERWSZE" in hint or "Track A" in hint

    def test_high_volume_suggests_both(self):
        """Volume > 2000 PLN -> both."""
        hint = _suggest_track_hint("sklep_plastyczny", "5000 PLN", 1.0, 1.0)
        assert hint.startswith("both")

    def test_low_volume_small_shop_still_private_label(self):
        """Nawet maly sklep dostaje private_label suggestion (v2), nie 'both'
        ani 'b2b_panel'. Domyslna sciezka to import z Chin pod marka klienta."""
        hint = _suggest_track_hint("sklep_plastyczny", "300 PLN", 0.5, 0.5)
        # NIE b2b_panel solo (to byloby zlamanie filozofii Plan A)
        assert not hint.startswith("b2b_panel")
        # Private label powinien byc glowny pitch
        assert "private_label" in hint

    def test_paint_and_sip_both_with_track_b_first(self):
        """Paint&sip konsumuja od reki, ale Track A wciaz w sugestii."""
        hint = _suggest_track_hint("paint_and_sip", "500 PLN", 1.0, 1.0)
        assert hint.startswith("both")
        # Track A musi byc wymieniony nawet dla paint_and_sip
        assert "Track A" in hint or "zestawy startowe" in hint.lower() or "branding" in hint.lower() or "marka" in hint.lower()


class TestParseVolume:
    def test_simple_range(self):
        assert _parse_volume_pln("300-800 PLN") == 300

    def test_open_range(self):
        assert _parse_volume_pln("2000+ PLN") == 2000

    def test_with_spaces(self):
        assert _parse_volume_pln("5 000 PLN") == 5000

    def test_none(self):
        assert _parse_volume_pln(None) is None

    def test_empty(self):
        assert _parse_volume_pln("") is None

    def test_unparseable(self):
        assert _parse_volume_pln("kilkaset złotych") is None


class TestValidateDraft:
    def _make_payload(self, **overrides):
        """Helper - default valid payload z nadpisaniami."""
        defaults = dict(
            offer_track="both",
            subject="Konkretny temat dla Państwa",
            snippet1="Zerknąłem na Państwa stronę. Mam krótkie pytanie.",
            snippet2="Piszę z Artmakera. Importujemy farby bezpośrednio z Chin.",
            snippet3="Możemy dla Państwa produkować farby pod własną marką. "
                    "Trzydzieści procent taniej niż polska hurtownia. MOQ 300 sztuk. "
                    "A jak czegoś potrzebujecie z magazynu PL, mamy panel B2B b2b.sowins.pl.",
            snippet4=None,
            snippet5="Wysłać wstępną wycenę produkcyjną?",
        )
        defaults.update(overrides)
        return EmailDraftPayload(**defaults)

    def test_valid_draft_no_warnings(self):
        warns = validate_draft(self._make_payload())
        assert warns == [], f"Expected no warnings, got: {warns}"

    def test_subject_too_long_warns(self):
        long_subject = "Ten subject ma stanowczo za duzo znakow zeby przejsc przez walidator"
        warns = validate_draft(self._make_payload(subject=long_subject))
        assert any("subject za dlugi" in w for w in warns)

    def test_long_sentence_warns(self):
        long = ("To naprawdę długie zdanie ktore ma stanowczo za dużo słów żeby "
                "przejść przez naszą walidację i powinno wywołać warning "
                "regression test dla pewności i kompletności sprawy.")
        warns = validate_draft(self._make_payload(snippet2=long))
        assert any("snippet2" in w and "slow" in w for w in warns)

    def test_no_polish_diacritics_warns(self):
        no_pl = self._make_payload(
            snippet1="Zerknalem na Wasza strone i mam pytanie.",
            snippet2="Pisze z Artmakera i importujemy farby z Chin do Polski.",
            snippet3="Mozemy produkowac dla Was farby. 30-50% taniej. MOQ 300 sztuk minimum.",
            snippet5="Wyslac wstepna wycene produkcyjna do porownania?",
        )
        warns = validate_draft(no_pl)
        assert any("polskich znakow" in w for w in warns)

    def test_panstwo_wy_mix_warns(self):
        mixed = self._make_payload(
            snippet1="Zerknałem na Państwa stronę.",
            snippet2="Pisze do Was z Artmakera. Mamy ofertę dla Waszego sklepu.",
            snippet3="Państwa oferta jest świetna i u Was widać skalę. MOQ 300 szt.",
        )
        warns = validate_draft(mixed)
        assert any("Panstwo" in w and "Wy" in w for w in warns)

    def test_track_b_before_a_in_both_warns(self):
        """offer_track=both ale Track B wymieniony PRZED Track A - to wbrew filozofii."""
        wrong = self._make_payload(
            offer_track="both",
            snippet3="Mamy panel B2B b2b.sowins.pl z magazynu, dostawa 24h. "
                    "A jak chcecie wiekszy biznes - produkcja w Chinach pod wlasna marke.",
        )
        warns = validate_draft(wrong)
        assert any("Track B" in w and "Track A" in w for w in warns)

    def test_pure_b2b_panel_without_china_warns(self):
        """KRYTYCZNE (regression dla Seneks-style maila): mail bez wzmianki o
        Chinach / private label / produkcji - nawet jak offer_track=b2b_panel -
        traci nasz core differentiator. Musi byc warning."""
        pure_b2b = self._make_payload(
            offer_track="b2b_panel",
            snippet2="Pisze z Artmakera, jesteśmy bezpośrednim importerem.",
            snippet3="Zamowienia obslugujemy przez panel b2b.sowins.pl. "
                    "Magazyn w PL, dostawa 24h, minimum 1000 zł netto. "
                    "Transport gratis przy zamowieniach od minimum.",
            snippet5="Podrzucic Panu dostep do platformy?",
        )
        warns = validate_draft(pure_b2b)
        assert any("BRAK wzmianki" in w or "differentiator" in w for w in warns), \
            f"Expected Track A warning, got: {warns}"

    def test_mail_with_chiny_passes_track_a_check(self):
        """Mail wspominajacy Chiny / produkcje powinien przejsc check."""
        with_china = self._make_payload(
            offer_track="private_label",
            snippet3="Produkujemy w naszych fabrykach w Chinach pod Wasza marke. "
                    "30-50% taniej, MOQ 300 sztuk. Wycene zrobimy na kazdy produkt.",
        )
        warns = validate_draft(with_china)
        # Sprawdz ze BRAKU Track A keywords nie ma w warningach
        assert not any("BRAK wzmianki" in w for w in warns), \
            f"Should not warn about missing Track A keywords, got: {warns}"

    def test_mail_with_private_label_passes_track_a_check(self):
        with_pl = self._make_payload(
            offer_track="both",
            snippet3="Mozemy zrobic private label dla Państwa - własna marka, "
                    "własne opakowania. Plus panel B2B na uzupełnianie.",
        )
        warns = validate_draft(with_pl)
        assert not any("BRAK wzmianki" in w for w in warns)


class TestEdgeCases:
    def test_none_returns_none(self):
        assert _strip_ai_artifacts(None) is None

    def test_empty_returns_empty(self):
        # pusty string powinien przejsc przez early-return
        result = _strip_ai_artifacts("")
        assert result == "" or result is None

    def test_normal_text_unchanged(self):
        text = "Dzien dobry, mam pytanie."
        assert _strip_ai_artifacts(text) == text

    def test_collapses_multiple_spaces(self):
        assert _strip_ai_artifacts("a    b") == "a b"

    def test_trims_edges(self):
        assert _strip_ai_artifacts("  hello  ") == "hello"
