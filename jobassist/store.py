"""SQLite store for job posting persistence and LLM/HTTP response caching."""

from __future__ import annotations

import hashlib
import sqlite3
import types
from pathlib import Path
from typing import TYPE_CHECKING

from jobassist.schemas import JobPosting

if TYPE_CHECKING:
    pass

_DEFAULT_DB: Path = Path.home() / ".jobassist" / "data.db"

_DDL = """
CREATE TABLE IF NOT EXISTS postings (
    hash     TEXT PRIMARY KEY,
    data     TEXT NOT NULL,
    source   TEXT NOT NULL,
    saved_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS response_cache (
    cache_key TEXT PRIMARY KEY,
    value     TEXT NOT NULL,
    saved_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def cache_key(*parts: str) -> str:
    """Return a sha256 hex digest of the concatenated *parts*, used as a cache lookup key."""
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()


class Store:
    """Thin SQLite wrapper for job posting persistence and response caching."""

    def __init__(self, path: str | Path = _DEFAULT_DB) -> None:
        if str(path) != ":memory:":
            Path(str(path)).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.executescript(_DDL)
        self._conn.commit()

    # --- Postings ---

    def save(self, posting: JobPosting) -> None:
        """Persist *posting*; silently ignores duplicates (hash is the primary key)."""
        self._conn.execute(
            "INSERT OR IGNORE INTO postings (hash, data, source) VALUES (?, ?, ?)",
            (posting.hash, posting.model_dump_json(), posting.source),
        )
        self._conn.commit()

    def has(self, posting_hash: str) -> bool:
        """Return True if a posting with *posting_hash* is already stored."""
        cur = self._conn.execute("SELECT 1 FROM postings WHERE hash = ?", (posting_hash,))
        return cur.fetchone() is not None

    def get(self, posting_hash: str) -> JobPosting | None:
        """Return the stored posting for *posting_hash*, or None."""
        cur = self._conn.execute("SELECT data FROM postings WHERE hash = ?", (posting_hash,))
        row = cur.fetchone()
        return JobPosting.model_validate_json(row[0]) if row else None

    def all_postings(self) -> list[JobPosting]:
        """Return all stored postings ordered by insertion time."""
        cur = self._conn.execute("SELECT data FROM postings ORDER BY saved_at")
        return [JobPosting.model_validate_json(row[0]) for row in cur.fetchall()]

    # --- Response cache ---

    def get_cached(self, key: str) -> str | None:
        """Return the cached value for *key*, or None if not cached."""
        cur = self._conn.execute(
            "SELECT value FROM response_cache WHERE cache_key = ?", (key,)
        )
        row = cur.fetchone()
        return str(row[0]) if row else None

    def set_cached(self, key: str, value: str) -> None:
        """Store *value* under *key*, replacing any existing entry."""
        self._conn.execute(
            "INSERT OR REPLACE INTO response_cache (cache_key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    # --- Lifecycle ---

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        self.close()
