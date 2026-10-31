"""Resume-aware LLM scoring pipeline with prompt caching."""

from __future__ import annotations

import hashlib
import html
import json
import re

import anthropic

from jobassist.Microservices.job_recommender.cache_client import CacheClient, cache_key
from jobassist.Microservices.job_recommender.costs.meter import CostMeter, metered_create
from jobassist.Microservices.job_recommender.models import JobPosting, ScoredPosting

_MODEL = "claude-sonnet-4-6"

_SYSTEM_TEMPLATE = """\
You are an expert recruiter evaluating job postings against a candidate's resume.

<resume>
{resume}
</resume>

For each job posting, respond with a JSON object (no markdown fences) containing:
- "score": a float from 0.0 to 1.0 representing how well the candidate fits the role
- "rationale": one concise paragraph explaining the score

Scoring guide:
0.9–1.0  Excellent match — skills, experience, and location align strongly
0.7–0.8  Good match — most requirements met, minor gaps
0.5–0.6  Partial match — some relevant experience but notable gaps
0.3–0.4  Weak match — limited alignment with requirements
0.0–0.2  Poor match — candidate lacks core requirements"""

_USER_TEMPLATE = """\
Company: {company}
Role: {role}
Location: {location}{salary_line}
{description_block}

Score this posting against the candidate's resume."""


def resume_fingerprint(resume: str) -> str:
    """Hash of the CV's words, ignoring spacing and line breaks.

    The same CV read from a .txt file, pasted, or uploaded (which trims whitespace) must
    reuse the same saved scores; only a change of wording should count as a new CV.
    """
    return hashlib.sha256(" ".join(resume.split()).encode()).hexdigest()


# Some boards send the whole ad as escaped HTML; markup is paid input but adds nothing.
_MAX_DESCRIPTION_CHARS = 6_000


def _plain_description(description: str | None) -> str:
    if not description:
        return "(no description provided)"
    text = re.sub(r"<[^>]+>", " ", html.unescape(html.unescape(description)))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_MAX_DESCRIPTION_CHARS] or "(no description provided)"


def _build_user_message(posting: JobPosting) -> str:
    salary_line = f"\nSalary: {posting.salary_raw}" if posting.salary_raw else ""
    desc = _plain_description(posting.description)
    return _USER_TEMPLATE.format(
        company=posting.company,
        role=posting.role,
        location=posting.location,
        salary_line=salary_line,
        description_block=f"Description:\n{desc}",
    )


def _extract_json(text: str) -> dict[str, object]:
    """Strip optional markdown fences then parse JSON."""
    clean = re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()
    result: dict[str, object] = json.loads(clean)
    return result


class ScoringPipeline:
    """Score job postings against a resume using Claude with prompt caching."""

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        resume: str,
        cache: CacheClient,
        *,
        meter: CostMeter | None = None,
    ) -> None:
        self._client = client
        self._cache = cache
        self._meter = meter
        self._resume_hash = resume_fingerprint(resume)
        # Scores saved before fingerprints ignored formatting were keyed on the exact text.
        self._legacy_hash = hashlib.sha256(resume.encode()).hexdigest()
        self._system = _SYSTEM_TEMPLATE.format(resume=resume)

    async def score(self, posting: JobPosting) -> ScoredPosting:
        """Return a scored posting, using the response cache when available."""
        key = cache_key(self._resume_hash, posting.hash)
        cached = await self._lookup(posting)
        if cached is not None:
            return self._parse(posting, cached)

        response = await metered_create(
            self._client,
            self._meter,
            posting.company,
            "scoring",
            model=_MODEL,
            max_tokens=512,
            system=[
                {
                    "type": "text",
                    "text": self._system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": _build_user_message(posting)}],
        )
        block = response.content[0]
        if not isinstance(block, anthropic.types.TextBlock):
            raise ValueError(f"Unexpected content block type: {type(block)}")
        text = block.text
        await self._cache.set_cached(key, text)
        return self._parse(posting, text)

    async def cached_score(self, posting: JobPosting) -> ScoredPosting | None:
        """Return the score already saved for this resume + posting, without calling Claude."""
        cached = await self._lookup(posting)
        if cached is None:
            return None
        try:
            return self._parse(posting, cached)
        except (ValueError, KeyError):
            return None

    async def _lookup(self, posting: JobPosting) -> str | None:
        """Return the saved response for this CV + posting (current key, then legacy)."""
        cached = await self._cache.get_cached(cache_key(self._resume_hash, posting.hash))
        if cached is None:
            cached = await self._cache.get_cached(cache_key(self._legacy_hash, posting.hash))
        return cached

    def _parse(self, posting: JobPosting, text: str) -> ScoredPosting:
        data = _extract_json(text)
        return ScoredPosting(
            posting=posting,
            score=float(data["score"]),  # type: ignore[arg-type]
            rationale=str(data["rationale"]),
        )
