"""Post-scoring result filters."""

from __future__ import annotations

from jobassist.Microservices.job_recommender.models import ScoredPosting


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
