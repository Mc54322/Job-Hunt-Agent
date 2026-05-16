"""Role alias generator — expands a role title into equivalent search terms."""

from __future__ import annotations

import json
import re

import anthropic

from jobassist.store import Store, cache_key

_MODEL = "claude-sonnet-4-6"

_SYSTEM_PROMPT = """\
You generate alternative job title search terms. Given a role title and employment type, \
return 5–8 alternative titles that a recruiter might use for the same or equivalent position.

Return a JSON array of strings (no markdown fences, no explanation).
Include only titles — no descriptions, no bullet points.
Do not include the original title in the list."""


def _strip_fences(text: str) -> str:
    return re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()


class AliasGenerator:
    """Generate and cache role alias lists using Claude."""

    def __init__(self, client: anthropic.AsyncAnthropic, store: Store) -> None:
        self._client = client
        self._store = store

    async def generate(self, role: str, job_type: str) -> list[str]:
        """Return a list of alternative role titles for *role* + *job_type*.

        Results are cached by `(role, job_type)` so the LLM is only called once
        per unique combination.
        """
        key = cache_key("aliases_v1", role.lower(), job_type.lower())
        cached = self._store.get_cached(key)
        if cached is not None:
            return self._parse(cached)

        response = await self._client.messages.create(
            model=_MODEL,
            max_tokens=256,
            system=_SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": f'Role: "{role}"\nEmployment type: {job_type}'}
            ],
        )

        block = response.content[0]
        if not isinstance(block, anthropic.types.TextBlock):
            return []

        raw = block.text
        self._store.set_cached(key, raw)
        return self._parse(raw)

    def _parse(self, text: str) -> list[str]:
        try:
            result = json.loads(_strip_fences(text))
            if isinstance(result, list):
                return [str(item) for item in result if item]
        except (json.JSONDecodeError, TypeError):
            pass
        return []
