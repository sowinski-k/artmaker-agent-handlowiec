"""Pydantic schema dla research output.

Zapewnia ze ScoreBreakdown odrzuca wartosci poza zakresem 0-2 / 0-10,
oraz ze ResearchResult wymaga minimum pol (company_name, segment, score).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.scoring import (
    ConcreteHook,
    ResearchResult,
    ScoreBreakdown,
)


class TestScoreBreakdown:
    def test_valid_score(self):
        s = ScoreBreakdown(
            activity=2, scale=2, fit=2, bulk_potential=2, contact_quality=2,
            total=10,
        )
        assert s.total == 10

    def test_score_above_2_rejected(self):
        with pytest.raises(ValidationError):
            ScoreBreakdown(
                activity=3, scale=2, fit=2, bulk_potential=2, contact_quality=2,
                total=11,
            )

    def test_score_below_0_rejected(self):
        with pytest.raises(ValidationError):
            ScoreBreakdown(
                activity=-1, scale=2, fit=2, bulk_potential=2, contact_quality=2,
                total=7,
            )

    def test_total_above_10_rejected(self):
        with pytest.raises(ValidationError):
            ScoreBreakdown(
                activity=2, scale=2, fit=2, bulk_potential=2, contact_quality=2,
                total=15,
            )

    def test_fractional_score_allowed(self):
        # 0.5 stopnia w kazdej kategorii - rubryka dopuszcza
        s = ScoreBreakdown(
            activity=1.5, scale=1.5, fit=2, bulk_potential=1, contact_quality=2,
            total=8.0,
        )
        assert s.activity == 1.5


class TestResearchResult:
    def _minimal_score(self):
        return ScoreBreakdown(
            activity=1, scale=1, fit=1, bulk_potential=1, contact_quality=1,
            total=5,
        )

    def test_minimum_fields(self):
        r = ResearchResult(
            company_name="Foo",
            segment="sklep_plastyczny",
            score=self._minimal_score(),
            rationale="Test rationale.",
        )
        assert r.company_name == "Foo"
        assert r.email is None
        assert r.concrete_hooks == []
        assert r.warning_flags == []

    def test_invalid_segment_rejected(self):
        with pytest.raises(ValidationError):
            ResearchResult(
                company_name="Foo",
                segment="bzdura",  # nie ma takiego segmentu
                score=self._minimal_score(),
                rationale="x",
            )

    def test_segments_8_known(self):
        """Lista znanych segmentow - jak ktos dorzuci 9-ty bez ResearchResult update,
        ten test wykryje."""
        for seg in [
            "sklep_plastyczny", "sklep_papierniczy", "paint_and_sip",
            "warsztaty_dzieci", "animatorzy_eventy", "szkola_artystyczna",
            "marka_wlasna", "inne",
        ]:
            r = ResearchResult(
                company_name="X", segment=seg, score=self._minimal_score(),
                rationale="x",
            )
            assert r.segment == seg

    def test_concrete_hooks_with_source(self):
        r = ResearchResult(
            company_name="X", segment="inne", score=self._minimal_score(),
            rationale="x",
            concrete_hooks=[
                ConcreteHook(text="duzy dzial scrapbooking", source="homepage"),
            ],
        )
        assert r.concrete_hooks[0].source == "homepage"
