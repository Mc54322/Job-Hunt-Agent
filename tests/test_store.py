"""Tests for the SQLite store and response cache."""

from __future__ import annotations

import sqlite3

import pytest

from jobassist.schemas import JobPosting
from jobassist.store import Store, cache_key

_POSTING = JobPosting(
    company="Acme",
    role="Software Engineer",
    location="London, UK",
    url="https://example.com/job/1",
    source="greenhouse",
    salary_raw=None,
)

_POSTING_2 = JobPosting(
    company="BetaCorp",
    role="Data Analyst",
    location="Manchester, UK",
    url="https://example.com/job/2",
    source="adzuna",
    salary_raw="£40,000 - £55,000",
)


@pytest.fixture
def store() -> Store:
    return Store(":memory:")


# ---------------------------------------------------------------------------
# cache_key helper
# ---------------------------------------------------------------------------


def test_cache_key_is_deterministic() -> None:
    assert cache_key("a", "b") == cache_key("a", "b")


def test_cache_key_differs_on_different_parts() -> None:
    assert cache_key("a", "b") != cache_key("a", "c")


def test_cache_key_is_64_hex_chars() -> None:
    k = cache_key("foo", "bar")
    assert len(k) == 64
    assert all(c in "0123456789abcdef" for c in k)


# ---------------------------------------------------------------------------
# Posting persistence
# ---------------------------------------------------------------------------


def test_save_then_has(store: Store) -> None:
    store.save(_POSTING)
    assert store.has(_POSTING.hash)


def test_has_returns_false_for_unseen(store: Store) -> None:
    assert not store.has("deadbeef" * 8)


def test_save_then_get_roundtrip(store: Store) -> None:
    store.save(_POSTING)
    loaded = store.get(_POSTING.hash)
    assert loaded is not None
    assert loaded.company == _POSTING.company
    assert loaded.role == _POSTING.role
    assert loaded.location == _POSTING.location
    assert loaded.source == _POSTING.source
    assert loaded.hash == _POSTING.hash


def test_get_returns_none_for_unseen(store: Store) -> None:
    assert store.get("deadbeef" * 8) is None


def test_save_is_idempotent(store: Store) -> None:
    store.save(_POSTING)
    store.save(_POSTING)
    assert len(store.all_postings()) == 1


def test_all_postings_empty(store: Store) -> None:
    assert store.all_postings() == []


def test_all_postings_returns_all_saved(store: Store) -> None:
    store.save(_POSTING)
    store.save(_POSTING_2)
    all_p = store.all_postings()
    assert len(all_p) == 2
    companies = {p.company for p in all_p}
    assert companies == {"Acme", "BetaCorp"}


def test_roundtrip_preserves_salary_raw(store: Store) -> None:
    store.save(_POSTING_2)
    loaded = store.get(_POSTING_2.hash)
    assert loaded is not None
    assert loaded.salary_raw == "£40,000 - £55,000"


def test_roundtrip_preserves_hash(store: Store) -> None:
    store.save(_POSTING)
    loaded = store.get(_POSTING.hash)
    assert loaded is not None
    assert loaded.hash == _POSTING.hash


# ---------------------------------------------------------------------------
# Response cache
# ---------------------------------------------------------------------------


def test_get_cached_returns_none_for_unseen(store: Store) -> None:
    assert store.get_cached("missing-key") is None


def test_set_and_get_cached(store: Store) -> None:
    store.set_cached("k1", "response-value")
    assert store.get_cached("k1") == "response-value"


def test_set_cached_replaces_existing(store: Store) -> None:
    store.set_cached("k1", "old")
    store.set_cached("k1", "new")
    assert store.get_cached("k1") == "new"


def test_different_keys_are_independent(store: Store) -> None:
    store.set_cached("k1", "value1")
    store.set_cached("k2", "value2")
    assert store.get_cached("k1") == "value1"
    assert store.get_cached("k2") == "value2"


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


def test_context_manager_closes_connection() -> None:
    with Store(":memory:") as s:
        s.save(_POSTING)
        assert s.has(_POSTING.hash)
    with pytest.raises(sqlite3.ProgrammingError):
        s.all_postings()
