"""Tests for additional ATS fetchers: Ashby, SmartRecruiters, Personio, Teamtailor, BambooHR."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from jobassist.schemas import JobPosting, JobQuery

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
        from jobassist.sources.ashby import AshbyFetcher

        data = _load("ashby_jobs.json")
        with respx.mock:
            respx.post("https://api.ashbyhq.com/posting-api/job-board/acme").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = AshbyFetcher(client)
                results = [p async for p in await fetcher.search(_QUERY_SE)]

        assert len(results) == 1
        assert results[0].role == "Software Engineer"

    @pytest.mark.asyncio
    async def test_posting_fields(self) -> None:
        from jobassist.sources.ashby import AshbyFetcher

        data = _load("ashby_jobs.json")
        with respx.mock:
            respx.post("https://api.ashbyhq.com/posting-api/job-board/acme").mock(
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
    async def test_remote_flag_overrides_location(self) -> None:
        from jobassist.sources.ashby import AshbyFetcher

        data = _load("ashby_jobs.json")
        query = JobQuery(role="Data Analyst", job_type="full-time", companies=["Acme"])
        with respx.mock:
            respx.post("https://api.ashbyhq.com/posting-api/job-board/acme").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = AshbyFetcher(client)
                results = [p async for p in await fetcher.search(query)]

        assert results[0].location == "Remote"

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self) -> None:
        from jobassist.sources.ashby import AshbyFetcher

        data = _load("ashby_jobs.json")
        with respx.mock:
            respx.post("https://api.ashbyhq.com/posting-api/job-board/acme").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = AshbyFetcher(client)
                results = [p async for p in await fetcher.search(_QUERY_NONE)]

        assert results == []

    @pytest.mark.asyncio
    async def test_http_error_skips_company(self) -> None:
        from jobassist.sources.ashby import AshbyFetcher

        with respx.mock:
            respx.post("https://api.ashbyhq.com/posting-api/job-board/acme").mock(
                return_value=httpx.Response(404)
            )
            async with httpx.AsyncClient() as client:
                fetcher = AshbyFetcher(client)
                results = [p async for p in await fetcher.search(_QUERY_SE)]

        assert results == []

    @pytest.mark.asyncio
    async def test_all_postings_are_job_postings(self) -> None:
        from jobassist.sources.ashby import AshbyFetcher

        data = _load("ashby_jobs.json")
        query = JobQuery(role="", job_type="full-time", companies=["Acme"])
        with respx.mock:
            respx.post("https://api.ashbyhq.com/posting-api/job-board/acme").mock(
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
        from jobassist.sources.smartrecruiters import SmartRecruitersFetcher

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
        from jobassist.sources.smartrecruiters import SmartRecruitersFetcher

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
        assert p.company == "Acme Corp"
        assert "London" in p.location

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self) -> None:
        from jobassist.sources.smartrecruiters import SmartRecruitersFetcher

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
        from jobassist.sources.smartrecruiters import SmartRecruitersFetcher

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
        from jobassist.sources.smartrecruiters import SmartRecruitersFetcher

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
# Personio
# ---------------------------------------------------------------------------


class TestPersonioFetcher:
    @pytest.mark.asyncio
    async def test_returns_matching_postings(self) -> None:
        from jobassist.sources.personio import PersonioFetcher

        data = _load("personio_jobs.json")
        with respx.mock:
            respx.get("https://acme.jobs.personio.com/api/v1/positions").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = PersonioFetcher(client)
                results = [p async for p in await fetcher.search(_QUERY_SE)]

        assert len(results) == 1
        assert "Engineer" in results[0].role

    @pytest.mark.asyncio
    async def test_posting_fields(self) -> None:
        from jobassist.sources.personio import PersonioFetcher

        data = _load("personio_jobs.json")
        with respx.mock:
            respx.get("https://acme.jobs.personio.com/api/v1/positions").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = PersonioFetcher(client)
                results = [p async for p in await fetcher.search(_QUERY_SE)]

        p = results[0]
        assert p.source == "personio"
        assert p.company == "Acme"
        assert p.location == "London"
        assert "personio.com" in p.url

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self) -> None:
        from jobassist.sources.personio import PersonioFetcher

        data = _load("personio_jobs.json")
        with respx.mock:
            respx.get("https://acme.jobs.personio.com/api/v1/positions").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = PersonioFetcher(client)
                results = [p async for p in await fetcher.search(_QUERY_NONE)]

        assert results == []

    @pytest.mark.asyncio
    async def test_http_error_skips_company(self) -> None:
        from jobassist.sources.personio import PersonioFetcher

        with respx.mock:
            respx.get("https://acme.jobs.personio.com/api/v1/positions").mock(
                return_value=httpx.Response(404)
            )
            async with httpx.AsyncClient() as client:
                fetcher = PersonioFetcher(client)
                results = [p async for p in await fetcher.search(_QUERY_SE)]

        assert results == []


# ---------------------------------------------------------------------------
# Teamtailor
# ---------------------------------------------------------------------------


class TestTeamtailorFetcher:
    _API_KEY = "test-api-key"

    @pytest.mark.asyncio
    async def test_returns_matching_postings(self) -> None:
        from jobassist.sources.teamtailor import TeamtailorFetcher

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
        from jobassist.sources.teamtailor import TeamtailorFetcher

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
        from jobassist.sources.teamtailor import TeamtailorFetcher

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
        from jobassist.sources.teamtailor import TeamtailorFetcher

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
        from jobassist.sources.teamtailor import TeamtailorFetcher

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
        from jobassist.sources.teamtailor import TeamtailorFetcher

        with respx.mock:
            respx.get("https://api.teamtailor.com/v1/jobs").mock(
                return_value=httpx.Response(401)
            )
            async with httpx.AsyncClient() as client:
                fetcher = TeamtailorFetcher(client, self._API_KEY, "Acme")
                results = [p async for p in await fetcher.search(_QUERY_SE)]

        assert results == []


# ---------------------------------------------------------------------------
# BambooHR
# ---------------------------------------------------------------------------


class TestBambooHRFetcher:
    @pytest.mark.asyncio
    async def test_returns_matching_postings(self) -> None:
        from jobassist.sources.bamboohr import BambooHRFetcher

        data = _load("bamboohr_jobs.json")
        with respx.mock:
            respx.get("https://acme.bamboohr.com/careers/list").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = BambooHRFetcher(client)
                results = [p async for p in await fetcher.search(_QUERY_SE)]

        assert len(results) == 1
        assert results[0].role == "Software Engineer"

    @pytest.mark.asyncio
    async def test_posting_fields(self) -> None:
        from jobassist.sources.bamboohr import BambooHRFetcher

        data = _load("bamboohr_jobs.json")
        with respx.mock:
            respx.get("https://acme.bamboohr.com/careers/list").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = BambooHRFetcher(client)
                results = [p async for p in await fetcher.search(_QUERY_SE)]

        p = results[0]
        assert p.source == "bamboohr"
        assert p.company == "Acme"
        assert p.location == "London, UK"
        assert "bamboohr.com" in p.url

    @pytest.mark.asyncio
    async def test_salary_raw_populated_when_present(self) -> None:
        from jobassist.sources.bamboohr import BambooHRFetcher

        data = _load("bamboohr_jobs.json")
        query = JobQuery(role="Senior Data Analyst", job_type="full-time", companies=["Acme"])
        with respx.mock:
            respx.get("https://acme.bamboohr.com/careers/list").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = BambooHRFetcher(client)
                results = [p async for p in await fetcher.search(query)]

        assert results[0].salary_raw is not None
        assert "55000" in results[0].salary_raw

    @pytest.mark.asyncio
    async def test_salary_raw_none_when_absent(self) -> None:
        from jobassist.sources.bamboohr import BambooHRFetcher

        data = _load("bamboohr_jobs.json")
        with respx.mock:
            respx.get("https://acme.bamboohr.com/careers/list").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = BambooHRFetcher(client)
                results = [p async for p in await fetcher.search(_QUERY_SE)]

        assert results[0].salary_raw is None

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self) -> None:
        from jobassist.sources.bamboohr import BambooHRFetcher

        data = _load("bamboohr_jobs.json")
        with respx.mock:
            respx.get("https://acme.bamboohr.com/careers/list").mock(
                return_value=httpx.Response(200, json=data)
            )
            async with httpx.AsyncClient() as client:
                fetcher = BambooHRFetcher(client)
                results = [p async for p in await fetcher.search(_QUERY_NONE)]

        assert results == []

    @pytest.mark.asyncio
    async def test_http_error_skips_company(self) -> None:
        from jobassist.sources.bamboohr import BambooHRFetcher

        with respx.mock:
            respx.get("https://acme.bamboohr.com/careers/list").mock(
                return_value=httpx.Response(403)
            )
            async with httpx.AsyncClient() as client:
                fetcher = BambooHRFetcher(client)
                results = [p async for p in await fetcher.search(_QUERY_SE)]

        assert results == []
