"""ATS detector — maps a URL or HTML snippet to a known ATS type."""

from __future__ import annotations

import re

# Ordered from most-specific to least-specific.  URL patterns are checked first
# (no HTTP needed); HTML patterns are the fallback when only the page source is
# available.

_URL_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"boards\.greenhouse\.io", re.I), "greenhouse"),
    (re.compile(r"jobs\.lever\.co", re.I), "lever"),
    (re.compile(r"jobs\.ashbyhq\.com", re.I), "ashby"),
    (re.compile(r"myworkdayjobs\.com", re.I), "workday"),
    (re.compile(r"smartrecruiters\.com", re.I), "smartrecruiters"),
    (re.compile(r"personio\.(?:de|com)", re.I), "personio"),
    (re.compile(r"teamtailor\.com", re.I), "teamtailor"),
    (re.compile(r"bamboohr\.com", re.I), "bamboohr"),
    (re.compile(r"reed\.co\.uk", re.I), "reed"),
]

_HTML_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"boards\.greenhouse\.io", re.I), "greenhouse"),
    (re.compile(r"jobs\.lever\.co", re.I), "lever"),
    (re.compile(r"jobs\.ashbyhq\.com", re.I), "ashby"),
    (re.compile(r"myworkdayjobs\.com", re.I), "workday"),
    (re.compile(r"smartrecruiters\.com", re.I), "smartrecruiters"),
]


def detect_ats(url: str, html: str = "") -> str | None:
    """Return the ATS identifier for *url* / *html*, or ``None`` if not recognised.

    URL patterns are checked first (fast, no HTTP).  Pass *html* from the page
    source for a second-pass check when the URL alone is not conclusive.
    """
    for pattern, ats in _URL_RULES:
        if pattern.search(url):
            return ats
    for pattern, ats in _HTML_RULES:
        if pattern.search(html):
            return ats
    return None
