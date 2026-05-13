"""Smoke testy dla agent/generate._strip_ai_artifacts.

Ten post-process jest ostatnia linia obrony przed AI-slop w mailach
(em-dash, smart quotes, korpo-frazy). Kazda regresja = wszystkie maile
beda brzmialy jak ChatGPT.
"""
from __future__ import annotations

from agent.generate import _strip_ai_artifacts


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
        out = _strip_ai_artifacts("Pragnę poinformować o naszej ofercie. Dzien dobry.")
        assert "Pragnę" not in out
        assert "Dzien dobry" in out

    def test_strips_w_dzisiejszych_czasach(self):
        out = _strip_ai_artifacts("W dzisiejszych czasach klienci szukają jakości.")
        assert "W dzisiejszych czasach" not in out

    def test_strips_korzystajac_z_okazji(self):
        out = _strip_ai_artifacts("Korzystając z okazji, chcę napisać. Tresc.")
        assert "Korzystając z okazji" not in out
        assert "Tresc" in out


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
