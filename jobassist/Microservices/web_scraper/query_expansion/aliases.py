"""Similar-title generator — expands a job title into titles worth searching too.

Includes close roles with overlapping skills, not just synonyms (e.g. "AI Engineer" also
brings "Data Scientist", "Machine Learning Engineer"): scoring against the CV decides
what actually fits. Generated once per title and kept permanently in the cache, so a
title is never looked up twice (one small call, ~$0.002).
"""

from __future__ import annotations

import json
import re

import anthropic

from jobassist.Microservices.web_scraper.cache_client import CacheClient, cache_key
from jobassist.Microservices.web_scraper.costs.meter import CostMeter, metered_create

_MODEL = "claude-sonnet-4-6"

_SYSTEM_PROMPT = """\
You help a UK job seeker widen a job search. Given a job title, return 6–10 other job \
titles worth searching too, most relevant first:
- other names employers use for the same job, and
- closely related roles that need largely the same skills (for example, for \
"AI Engineer": "Machine Learning Engineer", "Data Scientist", "Applied Scientist").
Do not include roles that need a different skill set, and keep the same broad level \
(no "Head of" or "Director" titles for a junior or mid-level title).

Return a JSON array of strings (no markdown fences, no explanation).
Include only titles — no descriptions, no bullet points.
Do not include the original title in the list."""


def _strip_fences(text: str) -> str:
    return re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()


class AliasGenerator:
    """Generate and cache role alias lists using Claude."""

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        cache: CacheClient,
        *,
        meter: CostMeter | None = None,
    ) -> None:
        self._client = client
        self._cache = cache
        self._meter = meter

    async def generate(self, role: str, job_type: str | None = None) -> list[str]:
        """Return similar job titles for *role*, most relevant first.

        Cached permanently by the title alone (any job type, any casing or spacing), so
        Claude is only asked once per title. *job_type* is accepted for compatibility.
        """
        key = cache_key("aliases_v2", " ".join(role.lower().split()))
        cached = await self._cache.get_cached(key)
        if cached is not None:
            return self._parse(cached)

        response = await metered_create(
            self._client,
            self._meter,
            "",
            "similar job titles",
            model=_MODEL,
            max_tokens=256,
            system=_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": f'Job title: "{role}"'}
            ],
        )

        block = response.content[0]
        if not isinstance(block, anthropic.types.TextBlock):
            return []

        raw = block.text
        await self._cache.set_cached(key, raw)
        return self._parse(raw)

    def _parse(self, text: str) -> list[str]:
        try:
            result = json.loads(_strip_fences(text))
            if isinstance(result, list):
                return [str(item) for item in result if item]
        except (json.JSONDecodeError, TypeError):
            pass
        return []
