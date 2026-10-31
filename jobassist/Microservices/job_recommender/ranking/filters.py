"""Pre- and post-scoring result filters."""

from __future__ import annotations

from jobassist.Microservices.job_recommender.models import JobPosting, ScoredPosting

_AGGREGATORS = frozenset({"adzuna", "reed"})


def cap_for_scoring(postings: list[JobPosting], limit: int) -> list[JobPosting]:
    """Return at most *limit* postings to score, spread fairly across companies.

    Round-robin by company (each company's 1st posting, then each one's 2nd, ...) so a
    multi-employer search is not filled by the few employers with the biggest boards.
    Within a round, ATS-direct postings come before aggregator copies.
    """
    rank: dict[str, int] = {}
    keyed: list[tuple[int, bool, int, JobPosting]] = []
    for i, posting in enumerate(postings):
        company = posting.company.lower()
        nth = rank.get(company, 0)
        rank[company] = nth + 1
        keyed.append((nth, posting.source in _AGGREGATORS, i, posting))
    keyed.sort(key=lambda k: k[:3])
    return [k[3] for k in keyed[:limit]]


def top_per_company(results: list[ScoredPosting]) -> list[ScoredPosting]:
    """Return only the highest-scored posting for each company.

    Comparison is case-insensitive; the original casing of the kept posting
    is preserved.  Insertion order among the winners matches the order of
    first appearance in *results*.
    """
    best: dict[str, ScoredPosting] = {}
    for sp in results:
        key = sp.posting.company.lower()
        if key not in best or sp.score > best[key].score:
            best[key] = sp
    # Preserve first-seen company order
    seen: list[str] = []
    for sp in results:
        k = sp.posting.company.lower()
        if k not in seen:
            seen.append(k)
    return [best[k] for k in seen]
