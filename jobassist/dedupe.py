"""Deduplication — prefer ATS-direct sources over aggregators on hash collision."""

from __future__ import annotations

from typing import AsyncIterator

from jobassist.schemas import JobPosting

# Sources that fetch directly from an ATS — higher priority than aggregators.
# Extend this set as new ATS fetchers are added.
ATS_SOURCES: frozenset[str] = frozenset({
    "greenhouse",
    "lever",
    "workday",
    "ashby",
    "smartrecruiters",
    "personio",
    "teamtailor",
    "bamboohr",
})


def _is_ats(source: str) -> bool:
    return source in ATS_SOURCES


async def deduplicate(stream: AsyncIterator[JobPosting]) -> AsyncIterator[JobPosting]:
    """Yield unique postings from *stream*, preferring ATS-direct over aggregators.

    When two postings share the same ``posting_hash``:
    - If the incoming posting is ATS-direct and the stored one is an aggregator,
      the ATS-direct copy replaces it (upgrade).
    - Otherwise the first-seen copy is kept.

    All postings are buffered internally before any are yielded, so the full
    stream is consumed before output begins.
    """
    seen: dict[str, JobPosting] = {}

    async for posting in stream:
        h = posting.hash
        if h not in seen:
            seen[h] = posting
        elif _is_ats(posting.source) and not _is_ats(seen[h].source):
            seen[h] = posting  # upgrade aggregator copy to ATS-direct

    for posting in seen.values():
        yield posting
