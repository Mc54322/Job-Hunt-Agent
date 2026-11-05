"""Location filter for ATS-board postings.

Aggregators filter by location server-side, but ATS boards return a company's whole
global board (Databricks lists Tokyo and Bengaluru next to London), so ATS postings
are filtered here instead.
"""

from __future__ import annotations

import re

_UK_NAMES = ("uk", "u.k.", "united kingdom", "great britain", "gb", "england", "scotland",
             "wales", "northern ireland", "britain")
# Postings often give only a town ("London", "Exeter"), so "UK" also matches common UK
# places. Not exhaustive — the LLM extractor is asked to add the country where it can.
_UK_PLACES = (
    "london", "manchester", "birmingham", "leeds", "glasgow", "edinburgh", "bristol", "cardiff",
    "belfast", "liverpool", "sheffield", "newcastle", "nottingham", "leicester", "southampton",
    "portsmouth", "reading", "oxford", "cambridge", "brighton", "york", "exeter", "plymouth",
    "norwich", "coventry", "bath", "swansea", "aberdeen", "dundee", "inverness", "stirling",
    "milton keynes", "slough", "bracknell", "wokingham", "guildford", "basingstoke", "hatfield",
    "ipswich", "cheltenham", "gloucester", "swindon", "northampton", "peterborough", "derby",
    "sunderland", "middlesbrough", "durham", "lancaster", "preston", "bolton", "salford",
    "warrington", "chester", "knutsford", "stockport", "huddersfield", "bradford", "hull",
    "lincoln", "luton", "watford", "st albans", "stevenage", "chelmsford", "colchester",
    "canterbury", "maidstone", "crawley", "croydon", "teddington", "harwell", "didcot",
    "farnborough", "telford", "wolverhampton", "derry", "londonderry", "newport", "wrexham",
    "porton down", "titchfield", "osterley", "kidlington", "berkshire", "hampshire", "surrey",
    "kent", "oxfordshire", "cambridgeshire", "hertfordshire", "yorkshire", "thames valley",
    "west midlands", "east midlands",
)
_UK_TERMS = _UK_NAMES + _UK_PLACES
# Word patterns that look British but aren't ("New South Wales", "New England").
_FALSE_UK = re.compile(r"new south wales|new england|new york|london,\s*(on|ontario|ky|oh)\b")


def _terms(part: str) -> tuple[str, ...]:
    return _UK_TERMS if part in _UK_NAMES else (part,)


def location_matches(posting_location: str, wanted: str) -> bool:
    """True when *posting_location* satisfies the user's *wanted* location.

    *wanted* is split on commas and any part may match as a whole word, so
    ``"London, UK"`` keeps London postings and anything in the UK (``"Remote (UK)"``,
    ``"Hatfield, United Kingdom"``, ``"Exeter"``). Use ``"London"`` alone to keep London
    only. Postings with no stated location are kept rather than lost.
    """
    posting = posting_location.strip().lower()
    if posting in ("", "unknown"):
        return True
    parts = [p.strip().lower() for p in wanted.split(",") if p.strip()]
    for part in parts:
        haystack = _FALSE_UK.sub(" ", posting) if part in _UK_NAMES else posting
        for term in _terms(part):
            if re.search(rf"(?<![\w]){re.escape(term)}(?![\w])", haystack):
                return True
    return False
