"""Adzuna aggregator fetcher — UK job search API, free tier."""

from __future__ import annotations

import asyncio
import random
import re
from datetime import date, datetime
from typing import Any, AsyncIterator

import httpx

from jobassist.Microservices.web_scraper.models.schemas import JobPosting, JobQuery

_SEARCH_URL = "https://api.adzuna.com/v1/api/jobs/gb/search/{page}"
_USER_AGENT = "JobAssist/0.1 (personal job search; https://github.com/job-hunt-agent)"
_RATE_DELAY = 1.0
_RATE_JITTER = 0.2
_COUNTRY_NAMES = {"uk", "u.k.", "gb", "great britain", "united kingdom", "england", "britain"}
_COUNTRY_SUFFIX = re.compile(
    r",\s*(uk|u\.k\.|gb|great britain|united kingdom|england|scotland|wales)\s*$", re.I
)
_NAME_STOPWORDS = {"the", "and", "plc", "ltd", "limited", "group", "uk", "co", "inc"}


def _parse_date(value: str) -> date | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _format_salary(min_val: float | None, max_val: float | None) -> str | None:
    if min_val is None and max_val is None:
        return None
    if min_val is not None and max_val is not None:
        return f"£{int(min_val):,} - £{int(max_val):,}"
    if min_val is not None:
        return f"£{int(min_val):,}+"
    return f"up to £{int(max_val):,}"  # type: ignore[arg-type]


def adzuna_where(location: str) -> str | None:
    """The ``where`` value for *location*, or None when it only names the country.

    The endpoint is UK-only already, and Adzuna answers ``where=UK`` combined with a
    company filter with HTTP 503 — so country-level locations are dropped and trailing
    country suffixes ("London, UK") stripped.
    """
    place = _COUNTRY_SUFFIX.sub("", location).strip()
    if not place or place.lower() in _COUNTRY_NAMES:
        return None
    return place


def _name_tokens(name: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", name.lower()) if t not in _NAME_STOPWORDS]


def employer_matches(display_name: str, employer: str) -> bool:
    """True when Adzuna's *display_name* plausibly refers to *employer*.

    Adzuna's ``company`` filter is fuzzy (``Financial Conduct Authority`` also returns
    an unrelated ``Conduct``). The shorter name, spaces removed, must be a prefix of
    the longer one ending on (or within 3 letters of) a word boundary — so
    ``Lloyds Bank`` ~ ``Lloyds Banking Group`` and ``JPMorganChase`` ~ ``JPMorgan Chase``,
    but not ``Citi`` ~ ``Citizens Advice``.
    """
    a, b = _name_tokens(display_name), _name_tokens(employer)
    if not a or not b:
        return False
    shorter, longer = sorted((a, b), key=lambda tokens: len("".join(tokens)))
    compact_short, compact_long = "".join(shorter), "".join(longer)
    if not compact_long.startswith(compact_short):
        return False
    boundaries = [len("".join(longer[: i + 1])) for i in range(len(longer))]
    return any(0 <= b - len(compact_short) <= 3 for b in boundaries)


def _to_posting(job: dict[str, Any], label: str | None = None) -> JobPosting:
    company: str = label or (job.get("company") or {}).get("display_name") or "Unknown"
    location: str = (job.get("location") or {}).get("display_name") or "Unknown"
    return JobPosting(
        company=company,
        role=job["title"],
        location=location,
        url=job["redirect_url"],
        source="adzuna",
        posted_date=_parse_date(job.get("created", "")),
        description=job.get("description"),
        salary_raw=_format_salary(job.get("salary_min"), job.get("salary_max")),
    )


class AdzunaFetcher:
    """Fetches postings from the Adzuna UK jobs API."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        app_id: str,
        app_key: str,
        *,
        results_per_page: int = 50,
        employer: str | None = None,
        employer_label: str | None = None,
    ) -> None:
        """*employer* restricts results to one company (Adzuna's canonical name);
        kept postings are labelled *employer_label* (defaults to *employer*)."""
        self._client = client
        self._app_id = app_id
        self._app_key = app_key
        self._results_per_page = results_per_page
        self._employer = employer
        self._employer_label = employer_label or employer

    async def search(self, query: JobQuery) -> AsyncIterator[JobPosting]:
        """Return an async iterator of postings matching *query* from Adzuna."""
        client = self._client
        app_id = self._app_id
        app_key = self._app_key
        results_per_page = self._results_per_page
        employer = self._employer
        label = self._employer_label

        async def _generate() -> AsyncIterator[JobPosting]:
            yielded = 0
            page = 1

            while yielded < query.max_results:
                batch_size = min(results_per_page, query.max_results - yielded)
                params: dict[str, str | int] = {
                    "app_id": app_id,
                    "app_key": app_key,
                    "what": query.role,
                    "results_per_page": batch_size,
                }
                where = adzuna_where(query.location) if query.location else None
                if where:
                    params["where"] = where
                if employer:
                    params["company"] = employer

                try:
                    resp = await client.get(
                        _SEARCH_URL.format(page=page),
                        params=params,
                        headers={"User-Agent": _USER_AGENT},
                    )
                    resp.raise_for_status()
                except httpx.HTTPError:
                    break

                results: list[dict[str, Any]] = resp.json().get("results", [])
                if not results:
                    break

                for job in results:
                    if employer:
                        display = (job.get("company") or {}).get("display_name") or ""
                        if not employer_matches(display, employer):
                            continue
                    yield _to_posting(job, label)
                    yielded += 1
                    if yielded >= query.max_results:
                        return

                if len(results) < batch_size:
                    break

                page += 1
                await asyncio.sleep(_RATE_DELAY + random.uniform(-_RATE_JITTER, _RATE_JITTER))

        return _generate()
