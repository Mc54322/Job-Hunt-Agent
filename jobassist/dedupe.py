"""Deduplication — prefer ATS-direct sources over aggregators on hash collision."""

from __future__ import annotations

import re
from typing import AsyncIterator

from jobassist.schemas import JobPosting

# Sources that fetch directly from an ATS — higher priority than aggregators.
# Extend this set as new ATS fetchers are added.
ATS_SOURCES: frozenset[str] = frozenset({
    "greenhouse",
    "lever",
    "ashby",
    "smartrecruiters",
    "teamtailor",
})

# Noise suffixes that recruiters append to role titles (e.g. "- job guarantee",
# "(m/f/d)", "(London)") — stripped before the soft-key comparison.
_NOISE_RE = re.compile(
    r"\s*[-–(]\s*(?:job guarantee|m/f/d|f/m/d|hybrid|remote|london|uk)\b.*$",
    re.I,
)


def _is_ats(source: str) -> bool:
    return source in ATS_SOURCES


def _soft_key(posting: JobPosting) -> str:
    """Return a normalised (company, role) key that ignores location and noise suffixes.

    Used as a secondary dedup pass to collapse same-recruiter/same-role postings
    that appear at multiple locations or with slightly different titles.
    """
    role = _NOISE_RE.sub("", posting.role).lower().strip()
    company = posting.company.lower().strip()
    return f"{company}|{role}"


async def deduplicate(stream: AsyncIterator[JobPosting]) -> AsyncIterator[JobPosting]:
    """Yield unique postings from *stream*, preferring ATS-direct over aggregators.

    Two dedup passes are applied:

    1. **Exact hash** (company + role + location): ATS-direct beats aggregator on
       collision; otherwise first-seen wins.
    2. **Soft key** (normalised company + role, location ignored): collapses
       same-recruiter postings that target multiple locations with the same title.
       The posting with the most specific location is kept (shortest location string
       is treated as most general; longer ones tend to name an actual city).

    All postings are buffered before any are yielded.
    """
    seen: dict[str, JobPosting] = {}

    async for posting in stream:
        h = posting.hash
        if h not in seen:
            seen[h] = posting
        elif _is_ats(posting.source) and not _is_ats(seen[h].source):
            seen[h] = posting  # upgrade aggregator copy to ATS-direct

    # Secondary pass: collapse by soft key, keeping the most specific location
    soft: dict[str, JobPosting] = {}
    for posting in seen.values():
        sk = _soft_key(posting)
        if sk not in soft:
            soft[sk] = posting
        else:
            existing = soft[sk]
            # Prefer ATS-direct; otherwise prefer longer (more specific) location
            if _is_ats(posting.source) and not _is_ats(existing.source):
                soft[sk] = posting
            elif not _is_ats(existing.source) and len(posting.location) > len(existing.location):
                soft[sk] = posting

    for posting in soft.values():
        yield posting
