"""Tests for the salary normaliser."""

from __future__ import annotations

from jobassist.salary import SalaryRange, parse_salary

# ---------------------------------------------------------------------------
# None / empty inputs
# ---------------------------------------------------------------------------


def test_none_returns_none() -> None:
    assert parse_salary(None) is None


def test_empty_string_returns_none() -> None:
    assert parse_salary("") is None


def test_non_salary_text_returns_none() -> None:
    assert parse_salary("Competitive") is None


def test_negotiable_returns_none() -> None:
    assert parse_salary("Negotiable") is None


# ---------------------------------------------------------------------------
# GBP ranges
# ---------------------------------------------------------------------------


def test_gbp_range_plain() -> None:
    result = parse_salary("£60,000 - £80,000")
    assert result is not None
    assert result.currency == "GBP"
    assert result.low == 60_000
    assert result.high == 80_000
    assert result.is_annual is True


def test_gbp_range_en_dash() -> None:
    result = parse_salary("£60,000 – £80,000")
    assert result is not None
    assert result.low == 60_000
    assert result.high == 80_000


def test_gbp_range_k_suffix() -> None:
    result = parse_salary("£60k - £80k")
    assert result is not None
    assert result.low == 60_000
    assert result.high == 80_000


# ---------------------------------------------------------------------------
# USD ranges
# ---------------------------------------------------------------------------


def test_usd_range() -> None:
    result = parse_salary("$80,000 - $100,000")
    assert result is not None
    assert result.currency == "USD"
    assert result.low == 80_000
    assert result.high == 100_000


def test_usd_k_range() -> None:
    result = parse_salary("$80k–$100k")
    assert result is not None
    assert result.low == 80_000
    assert result.high == 100_000


# ---------------------------------------------------------------------------
# Single amounts
# ---------------------------------------------------------------------------


def test_single_gbp_amount() -> None:
    result = parse_salary("£50,000 per annum")
    assert result is not None
    assert result.low == 50_000
    assert result.high == 50_000
    assert result.midpoint == 50_000


def test_single_gbp_k() -> None:
    result = parse_salary("£45k")
    assert result is not None
    assert result.low == 45_000


# ---------------------------------------------------------------------------
# Hourly rates → annualised
# ---------------------------------------------------------------------------


def test_hourly_rate_annualised() -> None:
    result = parse_salary("£25/hr")
    assert result is not None
    assert result.low == 25 * 1920
    assert result.is_annual is False


def test_hourly_range_annualised() -> None:
    result = parse_salary("£20 - £30 per hour")
    assert result is not None
    assert result.low == 20 * 1920
    assert result.high == 30 * 1920


# ---------------------------------------------------------------------------
# SalaryRange helpers
# ---------------------------------------------------------------------------


def test_midpoint() -> None:
    sr = SalaryRange(currency="GBP", low=60_000, high=80_000, is_annual=True)
    assert sr.midpoint == 70_000


def test_str_gbp() -> None:
    sr = SalaryRange(currency="GBP", low=60_000, high=80_000, is_annual=True)
    s = str(sr)
    assert "£" in s
    assert "60,000" in s
    assert "80,000" in s
    assert "pa" in s


def test_str_usd_hourly() -> None:
    sr = SalaryRange(currency="USD", low=40_000, high=40_000, is_annual=False)
    s = str(sr)
    assert "ph" in s
