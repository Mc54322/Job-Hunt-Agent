"""Tests for the role alias generator."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import anthropic
import pytest

from jobassist.aliases import AliasGenerator, _strip_fences
from jobassist.store import Store

_ROLE = "Software Engineer"
_JOB_TYPE = "full-time"

_ALIASES_RESPONSE = json.dumps([
    "Software Developer",
    "Backend Engineer",
    "Python Engineer",
    "SWE",
    "Application Developer",
])


@pytest.fixture
def store() -> Store:
    return Store(":memory:")


def _make_client(text: str) -> anthropic.AsyncAnthropic:
    block = MagicMock(spec=anthropic.types.TextBlock)
    block.text = text
    response = MagicMock()
    response.content = [block]
    messages = MagicMock()
    messages.create = AsyncMock(return_value=response)
    client = MagicMock(spec=anthropic.AsyncAnthropic)
    client.messages = messages
    return client  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# _strip_fences
# ---------------------------------------------------------------------------


def test_strip_fences_removes_json_fence() -> None:
    text = '```json\n["a", "b"]\n```'
    assert _strip_fences(text) == '["a", "b"]'


def test_strip_fences_plain_passthrough() -> None:
    text = '["a", "b"]'
    assert _strip_fences(text) == text


# ---------------------------------------------------------------------------
# generate — cache miss
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_calls_llm_on_cache_miss(store: Store) -> None:
    client = _make_client(_ALIASES_RESPONSE)
    gen = AliasGenerator(client, store)

    aliases = await gen.generate(_ROLE, _JOB_TYPE)

    client.messages.create.assert_awaited_once()  # type: ignore[attr-defined]
    assert isinstance(aliases, list)
    assert len(aliases) == 5


@pytest.mark.asyncio
async def test_generate_returns_strings(store: Store) -> None:
    client = _make_client(_ALIASES_RESPONSE)
    gen = AliasGenerator(client, store)

    aliases = await gen.generate(_ROLE, _JOB_TYPE)

    assert all(isinstance(a, str) for a in aliases)


@pytest.mark.asyncio
async def test_generate_aliases_do_not_include_original(store: Store) -> None:
    # LLM response includes only alternatives (original is excluded by prompt)
    client = _make_client(_ALIASES_RESPONSE)
    gen = AliasGenerator(client, store)

    aliases = await gen.generate(_ROLE, _JOB_TYPE)

    assert _ROLE not in aliases


# ---------------------------------------------------------------------------
# generate — cache hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_uses_cache_on_second_call(store: Store) -> None:
    client = _make_client(_ALIASES_RESPONSE)
    gen = AliasGenerator(client, store)

    await gen.generate(_ROLE, _JOB_TYPE)
    await gen.generate(_ROLE, _JOB_TYPE)

    assert client.messages.create.await_count == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_generate_cache_is_case_insensitive(store: Store) -> None:
    client = _make_client(_ALIASES_RESPONSE)
    gen = AliasGenerator(client, store)

    await gen.generate("Software Engineer", "full-time")
    await gen.generate("software engineer", "FULL-TIME")

    assert client.messages.create.await_count == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_different_roles_are_independent(store: Store) -> None:
    response_a = json.dumps(["Dev A1", "Dev A2"])
    response_b = json.dumps(["Analyst B1", "Analyst B2"])

    client_a = _make_client(response_a)
    client_b = _make_client(response_b)

    gen_a = AliasGenerator(client_a, store)
    gen_b = AliasGenerator(client_b, store)

    aliases_a = await gen_a.generate("Software Engineer", "full-time")
    aliases_b = await gen_b.generate("Data Analyst", "full-time")

    assert "Dev A1" in aliases_a
    assert "Analyst B1" in aliases_b


# ---------------------------------------------------------------------------
# generate — error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_returns_empty_on_invalid_json(store: Store) -> None:
    client = _make_client("not json at all")
    gen = AliasGenerator(client, store)

    aliases = await gen.generate(_ROLE, _JOB_TYPE)

    assert aliases == []


@pytest.mark.asyncio
async def test_generate_returns_empty_on_non_list_json(store: Store) -> None:
    client = _make_client('{"unexpected": "object"}')
    gen = AliasGenerator(client, store)

    aliases = await gen.generate(_ROLE, _JOB_TYPE)

    assert aliases == []


@pytest.mark.asyncio
async def test_generate_filters_empty_strings(store: Store) -> None:
    client = _make_client('["Backend Engineer", "", "Python Developer"]')
    gen = AliasGenerator(client, store)

    aliases = await gen.generate(_ROLE, _JOB_TYPE)

    assert "" not in aliases
    assert len(aliases) == 2
