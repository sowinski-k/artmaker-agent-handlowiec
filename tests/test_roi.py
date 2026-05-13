"""Smoke testy dla ROI logic - liczenie 'ile agent zaoszczedzil'.

Kluczowy invariant: stawki auto-pickowane z current year, bez env vars.
Logika robust na przyszlosc (rok 2027/2028 fallback do najnowszego znanego).
"""
from __future__ import annotations

from unittest.mock import patch

from datetime import datetime, timezone


def test_get_roi_rates_returns_current_year():
    """Helper zwraca stawki dla biezacego roku."""
    from web.main import _get_roi_rates_for_today

    rates = _get_roi_rates_for_today()
    current_year = datetime.now(timezone.utc).year
    assert rates["year"] == current_year
    assert rates["min_wage_monthly"] > 0
    assert rates["min_wage_h"] > 0
    assert rates["sales_rate_h"] > 0


def test_get_roi_rates_fallback_for_unknown_year():
    """Jak uruchomimy w 2030 a mapping konczy sie na 2026 - bierzemy 2026 (latest).

    UWAGA: rates['year'] zwraca pick_year (rok z ktorego stawki sa wziete),
    NIE current year - inaczej displayowalibysmy stawki 2026 pod etykieta 2030.
    """
    from web.main import _get_roi_rates_for_today, MIN_WAGE_BY_YEAR

    latest_year = max(MIN_WAGE_BY_YEAR.keys())
    latest_value = MIN_WAGE_BY_YEAR[latest_year]

    with patch("web.main.datetime") as mock_dt:
        # Symuluj rok 2030 (nieobecny w mapping)
        mock_dt.now.return_value = datetime(2030, 6, 15, tzinfo=timezone.utc)
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

        rates = _get_roi_rates_for_today()
        # Fallback: pick_year = latest (2026), zeby labelka byla spojna z kwotami
        assert rates["year"] == latest_year
        assert rates["min_wage_monthly"] == latest_value


def test_min_wage_2026_correct():
    """Sanity check: kwota minimalna 2026 = 4806 zl (oficjalnie ogloszone)."""
    from web.main import MIN_WAGE_BY_YEAR
    assert MIN_WAGE_BY_YEAR[2026] == 4806.0


def test_min_wage_history():
    """Historia ma min 2024-2026 dane (do retroaktywnego liczenia)."""
    from web.main import MIN_WAGE_BY_YEAR
    assert 2024 in MIN_WAGE_BY_YEAR
    assert 2025 in MIN_WAGE_BY_YEAR
    assert 2026 in MIN_WAGE_BY_YEAR
    # Wartości rosnące rok do roku (sanity)
    assert MIN_WAGE_BY_YEAR[2025] > MIN_WAGE_BY_YEAR[2024]
    assert MIN_WAGE_BY_YEAR[2026] > MIN_WAGE_BY_YEAR[2025]


def test_hours_per_month_kodeks_pracy():
    """168h/mies = 21 dni roboczych x 8h, Kodeks Pracy art. 130."""
    from web.main import HOURS_PER_MONTH
    assert HOURS_PER_MONTH == 168


def test_employer_cost_multiplier_reasonable():
    """Mnoznik brutto -> realny koszt etatu. PL norma 1.20-1.40."""
    from web.main import EMPLOYER_COST_MULTIPLIER
    assert 1.15 < EMPLOYER_COST_MULTIPLIER < 1.50


def test_labor_time_minutes_positive():
    """Czasy musza byc dodatnie - inaczej ROI by byl ujemny."""
    from web.main import LABOR_TIME_MINUTES
    assert LABOR_TIME_MINUTES["research"] > 0
    assert LABOR_TIME_MINUTES["enrich_success"] > 0
    assert LABOR_TIME_MINUTES["draft"] > 0
    assert LABOR_TIME_MINUTES["sent"] >= 0  # 0 dozwolone (drobnoska)


def test_min_wage_hourly_2026_official():
    """min_wage_h dla 2026 to OFICJALNA stawka 31.40 zl/h (Rozp. RM z 11.09.2025).

    Wazne: oficjalna stawka NIE jest =miesięczna/168 (28.6). To dwie osobne kwoty
    w Rozporządzeniu - godzinowa rosnie szybciej niz miesięczna (bo godzinowa
    nie ma juz w sobie urlopu/chorobowego, ktore sa po stronie etatu).
    """
    from web.main import MIN_WAGE_HOURLY_BY_YEAR
    assert MIN_WAGE_HOURLY_BY_YEAR[2026] == 31.40


def test_get_roi_rates_uses_official_hourly_for_known_year():
    """_get_roi_rates_for_today preferuje oficjalna stawke (31.40), nie wyliczenie."""
    from web.main import _get_roi_rates_for_today, MIN_WAGE_HOURLY_BY_YEAR
    rates = _get_roi_rates_for_today()
    if rates["year"] in MIN_WAGE_HOURLY_BY_YEAR:
        # Powinno byc oficjalne, nie monthly/168
        assert rates["min_wage_h"] == MIN_WAGE_HOURLY_BY_YEAR[rates["year"]]


def test_min_wage_net_monthly_2026():
    """Netto miesieczne dla 4806 brutto = 3621 zl (PIT + ZUS pracownika)."""
    from web.main import MIN_WAGE_NET_MONTHLY_BY_YEAR
    assert MIN_WAGE_NET_MONTHLY_BY_YEAR[2026] == 3621.0


def test_employer_cost_mult_zus_only():
    """Mnoznik 1.2048 = brutto + ZUS pracodawcy (20.48% narzutu).
    Rezerwa urlopowa + chorobowe + benefity NIE wliczone (fluktuuje per firma).
    """
    from web.main import EMPLOYER_COST_MULTIPLIER
    # Zmienione z 1.33 (z benefitami) na 1.2048 (tylko ZUS) - bardziej fair
    assert 1.20 < EMPLOYER_COST_MULTIPLIER < 1.25
