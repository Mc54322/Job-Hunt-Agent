"""Tests for additional ATS fetchers: Ashby, SmartRecruiters, Teamtailor, Workable."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from jobassist.Microservices.web_scraper.models.schemas import JobPosting, JobQuery
from jobassist.Microservices.web_scraper.sources.ats.ashby.ashby import AshbyFetcher
from jobassist.Microservices.web_scraper.sources.ats.smartrecruiters.smartrecruiters import (
    SmartRecruitersFetcher,
)
from jobassist.Microservices.web_scraper.sources.ats.teamtailor.teamtailor import (
    TeamtailorFetcher,
)
from jobassist.Microservices.web_scraper.sources.ats.workable.workable import WorkableFetcher

_FIXTURES = Path(__file__).parent / "fixtures"

_QUERY_SE = JobQuery(role="Software Engineer", job_type="full-time", companies=["Acme"])
_QUERY_PM = JobQuery(role="Product Manager", job_type="full-time", companies=["Acme"])
_QUERY_NONE = JobQuery(role="Nonexistent Role XYZ", job_type="full-time", companies=["Acme"])


def _load(name: str) -> Any:
    return json.loads((_FIXTURES / name).read_text())


# ---------------------------------------------------------------------------
# Ashby
# ---------------------------------------------------------------------------


class TestAshbyFetcher:
    @pytest.mark.asyncio
    async def test_returns_matching_postings(self) -> None:

        data = _load("ashby_jobs.json")
        with respx.mock:
            respx.get("https://api.ashbyhq.com/posting-api/job-board/acme").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = AshbyFetcher(client)
                results = [p async for p in await fetcher.search(_QUERY_SE)]

        assert len(results) == 1
        assert results[0].role == "Software Engineer"

    @pytest.mark.asyncio
    async def test_posting_fields(self) -> None:

        data = _load("ashby_jobs.json")
        with respx.mock:
            respx.get("https://api.ashbyhq.com/posting-api/job-board/acme").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = AshbyFetcher(client)
                results = [p async for p in await fetcher.search(_QUERY_SE)]

        p = results[0]
        assert p.source == "ashby"
        assert p.company == "Acme"
        assert p.location == "London, UK"
        assert "ashbyhq.com" in p.url

    @pytest.mark.asyncio
    async def test_remote_flag_used_when_location_blank(self) -> None:

        data = _load("ashby_jobs.json")
        query = JobQuery(role="Data Analyst", job_type="full-time", companies=["Acme"])
        with respx.mock:
            respx.get("https://api.ashbyhq.com/posting-api/job-board/acme").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = AshbyFetcher(client)
                results = [p async for p in await fetcher.search(query)]

        assert results[0].location == "Remote"

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self) -> None:

        data = _load("ashby_jobs.json")
        with respx.mock:
            respx.get("https://api.ashbyhq.com/posting-api/job-board/acme").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = AshbyFetcher(client)
                results = [p async for p in await fetcher.search(_QUERY_NONE)]

        assert results == []

    @pytest.mark.asyncio
    async def test_http_error_skips_company(self) -> None:

        with respx.mock:
            respx.get("https://api.ashbyhq.com/posting-api/job-board/acme").mock(
                return_value=httpx.Response(404)
            )
            async with httpx.AsyncClient() as client:
                fetcher = AshbyFetcher(client)
                results = [p async for p in await fetcher.search(_QUERY_SE)]

        assert results == []

    @pytest.mark.asyncio
    async def test_all_postings_are_job_postings(self) -> None:

        data = _load("ashby_jobs.json")
        query = JobQuery(role="", job_type="full-time", companies=["Acme"])
        with respx.mock:
            respx.get("https://api.ashbyhq.com/posting-api/job-board/acme").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = AshbyFetcher(client)
                results = [p async for p in await fetcher.search(query)]

        assert all(isinstance(p, JobPosting) for p in results)


# ---------------------------------------------------------------------------
# SmartRecruiters
# ---------------------------------------------------------------------------


class TestSmartRecruitersFetcher:
    @pytest.mark.asyncio
    async def test_returns_matching_postings(self) -> None:

        data = _load("smartrecruiters_jobs.json")
        with respx.mock:
            respx.get("https://api.smartrecruiters.com/v1/companies/Acme/postings").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = SmartRecruitersFetcher(client)
                results = [p async for p in await fetcher.search(_QUERY_SE)]

        assert len(results) == 1
        assert results[0].role == "Software Engineer"

    @pytest.mark.asyncio
    async def test_posting_fields(self) -> None:

        data = _load("smartrecruiters_jobs.json")
        with respx.mock:
            respx.get("https://api.smartrecruiters.com/v1/companies/Acme/postings").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = SmartRecruitersFetcher(client)
                results = [p async for p in await fetcher.search(_QUERY_SE)]

        p = results[0]
        assert p.source == "smartrecruiters"
        assert p.company == "Acme"  # the caller's name, so dedupe/one-per-company line up
        assert "London" in p.location
        # Public ad page, not the JSON API `ref` URL.
        assert p.url == "https://jobs.smartrecruiters.com/Acme/sr-001"

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self) -> None:

        data = _load("smartrecruiters_jobs.json")
        with respx.mock:
            respx.get("https://api.smartrecruiters.com/v1/companies/Acme/postings").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = SmartRecruitersFetcher(client)
                results = [p async for p in await fetcher.search(_QUERY_NONE)]

        assert results == []

    @pytest.mark.asyncio
    async def test_http_error_skips_company(self) -> None:

        with respx.mock:
            respx.get("https://api.smartrecruiters.com/v1/companies/Acme/postings").mock(
                return_value=httpx.Response(503)
            )
            async with httpx.AsyncClient() as client:
                fetcher = SmartRecruitersFetcher(client)
                results = [p async for p in await fetcher.search(_QUERY_SE)]

        assert results == []

    @pytest.mark.asyncio
    async def test_q_param_passed(self) -> None:

        data = _load("smartrecruiters_jobs.json")
        with respx.mock:
            route = respx.get("https://api.smartrecruiters.com/v1/companies/Acme/postings").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = SmartRecruitersFetcher(client)
                [p async for p in await fetcher.search(_QUERY_SE)]

        assert "q" in str(route.calls[0].request.url)


# ---------------------------------------------------------------------------
# Teamtailor
# ---------------------------------------------------------------------------


class TestTeamtailorFetcher:
    _API_KEY = "test-api-key"

    @pytest.mark.asyncio
    async def test_returns_matching_postings(self) -> None:

        data = _load("teamtailor_jobs.json")
        with respx.mock:
            respx.get("https://api.teamtailor.com/v1/jobs").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = TeamtailorFetcher(client, self._API_KEY, "Acme")
                results = [p async for p in await fetcher.search(_QUERY_SE)]

        assert len(results) == 1
        assert results[0].role == "Software Engineer"

    @pytest.mark.asyncio
    async def test_posting_fields(self) -> None:

        data = _load("teamtailor_jobs.json")
        with respx.mock:
            respx.get("https://api.teamtailor.com/v1/jobs").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = TeamtailorFetcher(client, self._API_KEY, "Acme")
                results = [p async for p in await fetcher.search(_QUERY_SE)]

        p = results[0]
        assert p.source == "teamtailor"
        assert p.company == "Acme"
        assert p.location == "London"
        assert "teamtailor.com" in p.url

    @pytest.mark.asyncio
    async def test_location_resolved_from_included(self) -> None:

        data = _load("teamtailor_jobs.json")
        with respx.mock:
            respx.get("https://api.teamtailor.com/v1/jobs").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = TeamtailorFetcher(client, self._API_KEY, "Acme")
                results = [p async for p in await fetcher.search(_QUERY_SE)]

        assert results[0].location == "London"

    @pytest.mark.asyncio
    async def test_no_location_falls_back_to_unknown(self) -> None:

        data = _load("teamtailor_jobs.json")
        with respx.mock:
            respx.get("https://api.teamtailor.com/v1/jobs").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = TeamtailorFetcher(client, self._API_KEY, "Acme")
                results = [p async for p in await fetcher.search(_QUERY_PM)]

        assert results[0].location == "Unknown"

    @pytest.mark.asyncio
    async def test_auth_header_sent(self) -> None:

        data = _load("teamtailor_jobs.json")
        with respx.mock:
            route = respx.get("https://api.teamtailor.com/v1/jobs").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = TeamtailorFetcher(client, self._API_KEY, "Acme")
                [p async for p in await fetcher.search(_QUERY_SE)]

        assert "Token token=test-api-key" in route.calls[0].request.headers["Authorization"]

    @pytest.mark.asyncio
    async def test_http_error_stops_iteration(self) -> None:

        with respx.mock:
            respx.get("https://api.teamtailor.com/v1/jobs").mock(
                return_value=httpx.Response(401)
            )
            async with httpx.AsyncClient() as client:
                fetcher = TeamtailorFetcher(client, self._API_KEY, "Acme")
                results = [p async for p in await fetcher.search(_QUERY_SE)]

        assert results == []


# ---------------------------------------------------------------------------
# Workable
# ---------------------------------------------------------------------------


_WORKABLE_URL = "https://apply.workable.com/api/v1/widget/accounts/acme"


class TestWorkableFetcher:
    @pytest.mark.asyncio
    async def test_returns_matching_postings(self) -> None:
        with respx.mock:
            respx.get(_WORKABLE_URL).mock(
                return_value=httpx.Response(200, json=_load("workable_jobs.json"))
            )
            async with httpx.AsyncClient() as client:
                results = [p async for p in await WorkableFetcher(client).search(_QUERY_SE)]

        assert len(results) == 1
        p = results[0]
        assert p.source == "workable"
        assert p.company == "Acme"
        assert p.location == "London, United Kingdom"
        assert p.url == "https://apply.workable.com/j/AAA111"
        assert p.posted_date is not None and p.posted_date.isoformat() == "2026-09-28"

    @pytest.mark.asyncio
    async def test_remote_location(self) -> None:
        query = JobQuery(role="Data Analyst", job_type="full-time", companies=["Acme"])
        with respx.mock:
            respx.get(_WORKABLE_URL).mock(
                return_value=httpx.Response(200, json=_load("workable_jobs.json"))
            )
            async with httpx.AsyncClient() as client:
                results = [p async for p in await WorkableFetcher(client).search(query)]

        assert results[0].location == "United Kingdom (Remote)"

    @pytest.mark.asyncio
    async def test_slug_override(self) -> None:
        query = JobQuery(role="Software Engineer", job_type="full-time", companies=["Acme Ltd"])
        with respx.mock:
            route = respx.get(_WORKABLE_URL).mock(
                return_value=httpx.Response(200, json=_load("workable_jobs.json"))
            )
            async with httpx.AsyncClient() as client:
                fetcher = WorkableFetcher(client, slugs={"Acme Ltd": "acme"})
                results = [p async for p in await fetcher.search(query)]

        assert route.call_count == 1
        assert results[0].company == "Acme Ltd"

    @pytest.mark.asyncio
    async def test_http_error_skips_company(self) -> None:
        with respx.mock:
            respx.get(_WORKABLE_URL).mock(return_value=httpx.Response(404))
            async with httpx.AsyncClient() as client:
                results = [p async for p in await WorkableFetcher(client).search(_QUERY_SE)]

        assert results == []


class TestSmartRecruitersAliases:
    @pytest.mark.asyncio
    async def test_one_request_per_term_and_no_duplicates(self) -> None:
        data = _load("smartrecruiters_jobs.json")
        query = JobQuery(
            role="Software Engineer",
            job_type="full-time",
            companies=["Acme"],
            role_aliases=["Engineer", "Developer"],
        )
        with respx.mock:
            route = respx.get("https://api.smartrecruiters.com/v1/companies/Acme/postings").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = SmartRecruitersFetcher(client)
                results = [p async for p in await fetcher.search(query)]

        assert route.call_count == 3
        assert [c.request.url.params["q"] for c in route.calls] == [
            "Software Engineer", "Engineer", "Developer"
        ]
        # Same ads come back for every term; each is yielded once.
        assert sorted(p.role for p in results) == ["Backend Developer", "Software Engineer"]
