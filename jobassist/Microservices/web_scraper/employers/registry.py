"""Employer registry — resolves a company name (or careers URL) to its public ATS board.

Lets a search target named employers directly instead of guessing board slugs.
Resolution order for each company:

1. Its careers-page URL, when it points at a known ATS board (e.g. ``jobs.lever.co/x``).
2. ``_KNOWN_BOARDS`` — boards verified against the live public APIs.
3. Unresolved — the caller falls back to an aggregator search filtered to that employer.

Slugs are never guessed from the name: a guessed slug often hits an unrelated company's
board (``national`` on Greenhouse is a Canadian PR firm, not the National Physical Lab).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Board:
    """A public ATS job board: which ATS hosts it and the company's slug there."""

    ats: str
    slug: str


# Keys are `normalise_company()` forms. Verified Oct 2026 against each ATS's public API
# (board name and UK postings checked, not just a 200 response).
_KNOWN_BOARDS: dict[str, Board] = {
    "palantir": Board("lever", "palantir"),
    "spotify": Board("lever", "spotify"),
    "ocado": Board("greenhouse", "ocadogroup"),
    "ocado technology": Board("greenhouse", "ocadogroup"),
    "ocado group": Board("greenhouse", "ocadogroup"),
    "deliveroo": Board("greenhouse", "deliveroo"),
    "trainline": Board("ashby", "trainline"),
    "asos": Board("smartrecruiters", "ASOS"),
    "cloudflare": Board("greenhouse", "cloudflare"),
    "databricks": Board("greenhouse", "databricks"),
    "datadog": Board("greenhouse", "datadog"),
    "mongodb": Board("greenhouse", "mongodb"),
    "man group": Board("greenhouse", "mangroup"),
    "legal & general": Board("smartrecruiters", "legalandgeneral"),
    "legal and general": Board("smartrecruiters", "legalandgeneral"),
    "experian": Board("smartrecruiters", "experian"),
    "monzo": Board("greenhouse", "monzo"),
    "wise": Board("smartrecruiters", "wise"),
    "starling bank": Board("workable", "starling-bank"),
    "starling": Board("workable", "starling-bank"),
    "methods": Board("workable", "methods"),
    "faculty": Board("ashby", "faculty"),
    "thoughtworks": Board("greenhouse", "thoughtworks"),
    "baringa": Board("greenhouse", "baringa"),
    "elevenlabs": Board("ashby", "elevenlabs"),
    "synthesia": Board("ashby", "synthesia"),
    "wayve": Board("ashby", "wayve"),
    "polyai": Board("greenhouse", "polyai"),
    "encord": Board("ashby", "encord"),
    "isomorphic labs": Board("greenhouse", "isomorphiclabs"),
    "signal ai": Board("ashby", "signal-ai"),
    "quantexa": Board("ashby", "quantexa"),
    "prolific": Board("greenhouse", "prolific"),
    "lawhive": Board("ashby", "lawhive"),
    "gradient labs": Board("ashby", "gradient-labs"),
    "conduct": Board("ashby", "conduct"),
    "9fin": Board("ashby", "9fin"),
    "multiverse": Board("ashby", "multiverse"),
    "dexory": Board("greenhouse", "dexory"),
    "cohere": Board("ashby", "cohere"),
    "incubator for ai": Board("greenhouse", "iai"),
    "i.ai": Board("greenhouse", "iai"),
    "ai security institute": Board("greenhouse", "aisi"),
    "aisi": Board("greenhouse", "aisi"),
}

# Adzuna matches its own canonical employer names; these differ from common usage.
_ADZUNA_NAMES: dict[str, str] = {
    "amazon / aws": "Amazon",
    "aws": "Amazon",
    "dwp digital": "DWP",
    "ministry of justice digital": "Ministry of Justice",
    "lseg": "London Stock Exchange Group",
    "ibm consulting": "IBM",
    "microsoft uk": "Microsoft",
}

# (ATS, pattern capturing the slug). Matched against careers-page URLs.
_URL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "greenhouse",
        re.compile(r"greenhouse\.io/embed/job_(?:board|app)\?(?:[^\"'\s]*&)?for=([\w-]+)", re.I),
    ),
    ("greenhouse", re.compile(r"(?:job-)?boards(?:\.eu)?\.greenhouse\.io/([\w-]+)", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co/([\w.-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([\w.%-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([\w-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/([\w-]+)", re.I)),
]

# Path segments that look like slugs but are ATS routes, not company boards.
_NOT_SLUGS = {"embed", "j", "api", "v1"}


def normalise_company(name: str) -> str:
    """Lowercase *name*, drop parenthetical notes, and collapse whitespace.

    ``"Cohere (London office)"`` → ``"cohere"``.
    """
    without_notes = re.sub(r"\(.*?\)", "", name)
    return " ".join(without_notes.lower().split())


def board_from_url(url: str) -> Board | None:
    """Return the ATS board a careers-page *url* points at, or ``None``.

    Also works on a whole HTML page: careers sites often embed or link to their ATS
    board, and the board's JSON feed beats scraping the page.
    """
    for ats, pattern in _URL_PATTERNS:
        for match in pattern.finditer(url):
            if match.group(1).lower() not in _NOT_SLUGS:
                return Board(ats, match.group(1))
    return None


def resolve_board(company: str, careers_url: str | None = None) -> Board | None:
    """Return the public ATS board for *company*, or ``None`` when none is known."""
    if careers_url:
        board = board_from_url(careers_url)
        if board is not None:
            return board
    return _KNOWN_BOARDS.get(normalise_company(company))


def adzuna_employer_name(company: str) -> str:
    """Return the employer name Adzuna's ``company`` filter recognises for *company*."""
    key = normalise_company(company)
    return _ADZUNA_NAMES.get(key) or re.sub(r"\(.*?\)", "", company).strip()


def plan_employers(
    companies: list[str], company_urls: Mapping[str, str] | None = None
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Split *companies* into ATS boards and those with no known board.

    Returns ``({ats: {company: slug}}, unresolved_companies)``.
    """
    urls = company_urls or {}
    boards: dict[str, dict[str, str]] = {}
    unresolved: list[str] = []
    for company in companies:
        board = resolve_board(company, urls.get(company))
        if board is None:
            unresolved.append(company)
        else:
            boards.setdefault(board.ats, {})[company] = board.slug
    return boards, unresolved
