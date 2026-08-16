"""Salary normaliser — parses raw salary strings into a canonical annual GBP/USD range."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Patterns are tried in order; first match wins.
_CURRENCY_SYMBOLS: dict[str, str] = {"£": "GBP", "$": "USD", "€": "EUR"}

# Matches e.g. "60k", "60,000", "60000", "60.5k" — k suffix is included in group
_AMOUNT = r"([\d,]+(?:\.\d+)?k?)"

# Full range pattern: "£60,000 - £80,000", "$60k–$80k", etc.
_RANGE_RE = re.compile(
    r"([£$€])\s*" + _AMOUNT + r"\s*[-–—to]+\s*[£$€]?\s*" + _AMOUNT,
    re.I,
)

# Single amount: "£50,000 per annum", "£25/hr"
_SINGLE_RE = re.compile(r"([£$€])\s*" + _AMOUNT, re.I)

# Per-hour marker
_HOURLY_RE = re.compile(r"/\s*h(?:ou?r?)?|per\s+h(?:ou?r?)?", re.I)

_ANNUAL_HOURS = 1920  # 48 weeks × 40 hrs — conservative full-time year


def _parse_amount(raw: str) -> float:
    """Convert a raw numeric string (possibly ending in 'k') to a float."""
    clean = raw.lower().rstrip("k").replace(",", "")
    value = float(clean)
    if raw.lower().endswith("k"):
        value *= 1000
    return value


@dataclass
class SalaryRange:
    currency: str
    low: float
    high: float
    is_annual: bool

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2

    def __str__(self) -> str:
        sym = next((s for s, c in _CURRENCY_SYMBOLS.items() if c == self.currency), self.currency)
        freq = "pa" if self.is_annual else "ph"
        return f"{sym}{self.low:,.0f}–{sym}{self.high:,.0f} {freq}"


def parse_salary(raw: str | None) -> SalaryRange | None:
    """Parse *raw* salary text into a :class:`SalaryRange`, or return ``None``.

    Handles:
    - Ranges: "£60,000 – £80,000", "$60k-$80k"
    - Singles: "£50,000 pa" (high = low for singles)
    - Hourly: "£25/hr" → annualised at 1920 hours
    - k-suffix: "60k" → 60 000
    """
    if not raw:
        return None

    raw = raw.strip()
    hourly = bool(_HOURLY_RE.search(raw))

    m = _RANGE_RE.search(raw)
    if m:
        currency = _CURRENCY_SYMBOLS.get(m.group(1), m.group(1))
        low = _parse_amount(m.group(2))
        high = _parse_amount(m.group(3))
        if hourly:
            low *= _ANNUAL_HOURS
            high *= _ANNUAL_HOURS
        return SalaryRange(currency=currency, low=low, high=high, is_annual=not hourly)

    m2 = _SINGLE_RE.search(raw)
    if m2:
        currency = _CURRENCY_SYMBOLS.get(m2.group(1), m2.group(1))
        amount = _parse_amount(m2.group(2))
        if hourly:
            amount *= _ANNUAL_HOURS
        return SalaryRange(currency=currency, low=amount, high=amount, is_annual=not hourly)

    return None
