"""Tests for the cover letter and CV bullet drafter."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import anthropic
import pytest

from jobassist.drafter import CoverLetterDrafter, DraftedApplication, _strip_fences
from jobassist.schemas import JobPosting
from jobassist.store import Store

_RESUME = "Experienced software engineer with 5 years in Python and distributed systems."
_POSTING = JobPosting(
    company="Acme",
    role="Software Engineer",
    location="London, UK",
    url="https://jobs.acme.com/se-001",
    source="greenhouse",
    description="Build scalable distributed systems in Python.",
)


@pytest.fixture
def store() -> Store:
    return Store(":memory:")


def _make_client(cover_letter_text: str, bullets_text: str) -> anthropic.AsyncAnthropic:
    """Return a mock Anthropic client that alternates between two responses."""
    calls: list[int] = [0]

    async def _create(**kwargs: object) -> MagicMock:
        idx = calls[0]
        calls[0] += 1
        text = cover_letter_text if idx == 0 else bullets_text
        block = MagicMock(spec=anthropic.types.TextBlock)
        block.text = text
        response = MagicMock()
        response.content = [block]
        return response

    messages = MagicMock()
    messages.create = _create
    client = MagicMock(spec=anthropic.AsyncAnthropic)
    client.messages = messages
    return client  # type: ignore[return-value]


_CL_RESPONSE = json.dumps({"cover_letter": "Dear Hiring Manager, I am excited to apply."})
_BULLETS_RESPONSE = json.dumps({
    "bullets": ["Led migration to microservices.", "Reduced latency by 30%."]
})


# ---------------------------------------------------------------------------
# _strip_fences
# ---------------------------------------------------------------------------


def test_strip_fences_removes_json_fence() -> None:
    text = '```json\n{"key": "val"}\n```'
    assert _strip_fences(text) == '{"key": "val"}'


def test_strip_fences_passthrough_plain() -> None:
    text = '{"key": "val"}'
    assert _strip_fences(text) == text


# ---------------------------------------------------------------------------
# DraftedApplication — basic structure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_draft_returns_drafted_application(store: Store) -> None:
    client = _make_client(_CL_RESPONSE, _BULLETS_RESPONSE)
    drafter = CoverLetterDrafter(client, _RESUME, store)

    result = await drafter.draft(_POSTING)

    assert isinstance(result, DraftedApplication)


@pytest.mark.asyncio
async def test_draft_cover_letter_non_empty(store: Store) -> None:
    client = _make_client(_CL_RESPONSE, _BULLETS_RESPONSE)
    drafter = CoverLetterDrafter(client, _RESUME, store)

    result = await drafter.draft(_POSTING)

    assert len(result.cover_letter) > 0
    assert "Hiring Manager" in result.cover_letter


@pytest.mark.asyncio
async def test_draft_bullets_non_empty(store: Store) -> None:
    client = _make_client(_CL_RESPONSE, _BULLETS_RESPONSE)
    drafter = CoverLetterDrafter(client, _RESUME, store)

    result = await drafter.draft(_POSTING)

    assert len(result.bullets) == 2
    assert all(isinstance(b, str) for b in result.bullets)


@pytest.mark.asyncio
async def test_draft_makes_two_llm_calls(store: Store) -> None:
    """One call for the cover letter, one for the bullets."""
    call_count: list[int] = [0]

    async def _create(**kwargs: object) -> MagicMock:
        call_count[0] += 1
        text = _CL_RESPONSE if call_count[0] == 1 else _BULLETS_RESPONSE
        block = MagicMock(spec=anthropic.types.TextBlock)
        block.text = text
        resp = MagicMock()
        resp.content = [block]
        return resp

    messages = MagicMock()
    messages.create = _create
    client = MagicMock(spec=anthropic.AsyncAnthropic)
    client.messages = messages

    drafter = CoverLetterDrafter(client, _RESUME, store)  # type: ignore[arg-type]
    await drafter.draft(_POSTING)

    assert call_count[0] == 2


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_draft_uses_cache(store: Store) -> None:
    call_count: list[int] = [0]

    async def _create(**kwargs: object) -> MagicMock:
        call_count[0] += 1
        text = _CL_RESPONSE if call_count[0] <= 1 else _BULLETS_RESPONSE
        block = MagicMock(spec=anthropic.types.TextBlock)
        block.text = text
        resp = MagicMock()
        resp.content = [block]
        return resp

    messages = MagicMock()
    messages.create = _create
    client = MagicMock(spec=anthropic.AsyncAnthropic)
    client.messages = messages

    drafter = CoverLetterDrafter(client, _RESUME, store)  # type: ignore[arg-type]
    first = await drafter.draft(_POSTING)
    second = await drafter.draft(_POSTING)

    assert call_count[0] == 2  # no extra calls on second draft
    assert first.cover_letter == second.cover_letter
    assert first.bullets == second.bullets


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_draft_handles_invalid_cover_letter_json(store: Store) -> None:
    client = _make_client("not json at all", _BULLETS_RESPONSE)
    drafter = CoverLetterDrafter(client, _RESUME, store)

    result = await drafter.draft(_POSTING)

    assert result.cover_letter == ""


@pytest.mark.asyncio
async def test_draft_handles_invalid_bullets_json(store: Store) -> None:
    client = _make_client(_CL_RESPONSE, "oops")
    drafter = CoverLetterDrafter(client, _RESUME, store)

    result = await drafter.draft(_POSTING)

    assert result.bullets == []


@pytest.mark.asyncio
async def test_draft_filters_empty_bullets(store: Store) -> None:
    bad_bullets = json.dumps({"bullets": ["Good bullet.", "", "  "]})
    client = _make_client(_CL_RESPONSE, bad_bullets)
    drafter = CoverLetterDrafter(client, _RESUME, store)

    result = await drafter.draft(_POSTING)

    assert "" not in result.bullets
    assert len(result.bullets) == 1
