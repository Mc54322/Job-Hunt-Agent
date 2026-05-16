"""Tests for the LLM scoring pipeline."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import anthropic
import pytest

from jobassist.schemas import JobPosting, ScoredPosting
from jobassist.scorer import ScoringPipeline, _build_user_message, _extract_json
from jobassist.store import Store

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_RESUME = "Experienced software engineer with Python, SQL, and data analysis skills."

_POSTING = JobPosting(
    company="Acme",
    role="Software Engineer",
    location="London, UK",
    url="https://example.com/job/1",
    source="greenhouse",
    salary_raw=None,
)

_POSTING_WITH_SALARY = JobPosting(
    company="BetaCorp",
    role="Data Analyst",
    location="Manchester, UK",
    url="https://example.com/job/2",
    source="adzuna",
    salary_raw="£40,000 - £55,000",
    description="Analyse large datasets and produce reports.",
)

_SCORE_RESPONSE = json.dumps({"score": 0.85, "rationale": "Strong Python and data skills match."})


@pytest.fixture
def store() -> Store:
    return Store(":memory:")


def _make_client(text: str) -> anthropic.AsyncAnthropic:
    """Return a mock AsyncAnthropic whose messages.create resolves to *text*."""
    text_block = MagicMock(spec=anthropic.types.TextBlock)
    text_block.text = text
    mock_response = MagicMock()
    mock_response.content = [text_block]

    mock_messages = MagicMock()
    mock_messages.create = AsyncMock(return_value=mock_response)

    client = MagicMock(spec=anthropic.AsyncAnthropic)
    client.messages = mock_messages
    return client  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------


def test_extract_json_plain() -> None:
    data = _extract_json('{"score": 0.8, "rationale": "Good match."}')
    assert data["score"] == 0.8
    assert data["rationale"] == "Good match."


def test_extract_json_with_json_fence() -> None:
    text = '```json\n{"score": 0.5, "rationale": "Partial."}\n```'
    data = _extract_json(text)
    assert data["score"] == 0.5


def test_extract_json_with_plain_fence() -> None:
    text = '```\n{"score": 0.3, "rationale": "Weak."}\n```'
    data = _extract_json(text)
    assert data["score"] == 0.3


# ---------------------------------------------------------------------------
# _build_user_message
# ---------------------------------------------------------------------------


def test_build_user_message_includes_basics() -> None:
    msg = _build_user_message(_POSTING)
    assert "Acme" in msg
    assert "Software Engineer" in msg
    assert "London, UK" in msg


def test_build_user_message_no_salary_when_none() -> None:
    msg = _build_user_message(_POSTING)
    assert "Salary" not in msg


def test_build_user_message_includes_salary_when_present() -> None:
    msg = _build_user_message(_POSTING_WITH_SALARY)
    assert "£40,000 - £55,000" in msg


def test_build_user_message_includes_description() -> None:
    msg = _build_user_message(_POSTING_WITH_SALARY)
    assert "Analyse large datasets" in msg


def test_build_user_message_no_description_placeholder() -> None:
    msg = _build_user_message(_POSTING)
    assert "no description provided" in msg


# ---------------------------------------------------------------------------
# ScoringPipeline — cache miss (LLM called)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_calls_llm_on_cache_miss(store: Store) -> None:
    client = _make_client(_SCORE_RESPONSE)
    pipeline = ScoringPipeline(client, _RESUME, store)

    result = await pipeline.score(_POSTING)

    client.messages.create.assert_awaited_once()  # type: ignore[attr-defined]
    assert isinstance(result, ScoredPosting)
    assert result.score == pytest.approx(0.85)
    assert "Python" in result.rationale


@pytest.mark.asyncio
async def test_score_caches_response_after_llm_call(store: Store) -> None:
    client = _make_client(_SCORE_RESPONSE)
    pipeline = ScoringPipeline(client, _RESUME, store)

    await pipeline.score(_POSTING)

    # Cache should now hold the raw JSON for this posting
    import hashlib

    from jobassist.store import cache_key

    resume_hash = hashlib.sha256(_RESUME.encode()).hexdigest()
    key = cache_key(resume_hash, _POSTING.hash)
    assert store.get_cached(key) == _SCORE_RESPONSE


# ---------------------------------------------------------------------------
# ScoringPipeline — cache hit (LLM NOT called)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_uses_cache_on_second_call(store: Store) -> None:
    client = _make_client(_SCORE_RESPONSE)
    pipeline = ScoringPipeline(client, _RESUME, store)

    await pipeline.score(_POSTING)
    await pipeline.score(_POSTING)  # second call — should hit cache

    assert client.messages.create.await_count == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_score_returns_cached_result(store: Store) -> None:
    client = _make_client(_SCORE_RESPONSE)
    pipeline = ScoringPipeline(client, _RESUME, store)

    first = await pipeline.score(_POSTING)
    second = await pipeline.score(_POSTING)

    assert first.score == second.score
    assert first.rationale == second.rationale


# ---------------------------------------------------------------------------
# ScoringPipeline — different resumes use independent caches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_different_resumes_are_cached_independently(store: Store) -> None:
    response_a = json.dumps({"score": 0.9, "rationale": "Excellent match for resume A."})
    response_b = json.dumps({"score": 0.4, "rationale": "Weak match for resume B."})

    client_a = _make_client(response_a)
    client_b = _make_client(response_b)

    pipeline_a = ScoringPipeline(client_a, "Resume A content.", store)
    pipeline_b = ScoringPipeline(client_b, "Resume B content.", store)

    result_a = await pipeline_a.score(_POSTING)
    result_b = await pipeline_b.score(_POSTING)

    assert result_a.score == pytest.approx(0.9)
    assert result_b.score == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# ScoringPipeline — LLM prompt includes resume in system
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_sends_resume_in_system_prompt(store: Store) -> None:
    client = _make_client(_SCORE_RESPONSE)
    pipeline = ScoringPipeline(client, _RESUME, store)

    await pipeline.score(_POSTING)

    call_kwargs = client.messages.create.call_args.kwargs  # type: ignore[attr-defined]
    system = call_kwargs["system"]
    assert isinstance(system, list)
    assert len(system) == 1
    assert _RESUME in system[0]["text"]


@pytest.mark.asyncio
async def test_score_system_block_has_cache_control(store: Store) -> None:
    client = _make_client(_SCORE_RESPONSE)
    pipeline = ScoringPipeline(client, _RESUME, store)

    await pipeline.score(_POSTING)

    call_kwargs = client.messages.create.call_args.kwargs  # type: ignore[attr-defined]
    system_block = call_kwargs["system"][0]
    assert system_block.get("cache_control") == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# ScoringPipeline — score range
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_is_between_0_and_1(store: Store) -> None:
    for score_val in [0.0, 0.5, 1.0]:
        local_store = Store(":memory:")
        resp = json.dumps({"score": score_val, "rationale": "test"})
        client = _make_client(resp)
        pipeline = ScoringPipeline(client, _RESUME, local_store)
        result = await pipeline.score(_POSTING)
        assert 0.0 <= result.score <= 1.0
