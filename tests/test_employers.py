"""Tests for employer-targeted search: registry, careers-URL parsing, location filter,
Excel employer-list loader, and the web_scraper `/search` routing. HTTP mocked via respx."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import openpyxl
import pytest
import respx
from fastapi.testclient import TestClient

from jobassist.Microservices.job_recommender.orchestration.employers_file import (
    TargetEmployer,
    load_employers,
)
from jobassist.Microservices.web_scraper import api as scraper_api
from jobassist.Microservices.web_scraper.api import app, get_anthropic
from jobassist.Microservices.web_scraper.employers.registry import (
    Board,
    adzuna_employer_name,
    board_from_url,
    normalise_company,
    plan_employers,
    resolve_board,
)
from jobassist.Microservices.web_scraper.filtering.location import location_matches

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_normalise_company_strips_notes_and_case() -> None:
    assert normalise_company("Cohere (London office)") == "cohere"
    assert normalise_company("  Isomorphic   Labs ") == "isomorphic labs"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://boards.greenhouse.io/monzo", Board("greenhouse", "monzo")),
        ("https://job-boards.greenhouse.io/deliveroo/jobs/123", Board("greenhouse", "deliveroo")),
        (
            "https://boards.greenhouse.io/embed/job_board?for=prolific",
            Board("greenhouse", "prolific"),
        ),
        ("https://jobs.lever.co/palantir", Board("lever", "palantir")),
        ("https://jobs.ashbyhq.com/faculty/abc-123", Board("ashby", "faculty")),
        ("https://careers.smartrecruiters.com/ASOS", Board("smartrecruiters", "ASOS")),
        ("https://jobs.smartrecruiters.com/Experian/7440001", Board("smartrecruiters", "Experian")),
        ("https://apply.workable.com/starling-bank/", Board("workable", "starling-bank")),
    ],
)
def test_board_from_url_recognises_ats_links(url: str, expected: Board) -> None:
    assert board_from_url(url) == expected


def test_board_from_url_ignores_non_ats_and_route_segments() -> None:
    assert board_from_url("https://careers.google.com/jobs") is None
    assert board_from_url("https://apply.workable.com/j/55FA38E458") is None


def test_resolve_board_known_employer() -> None:
    assert resolve_board("Ocado Technology") == Board("greenhouse", "ocadogroup")
    assert resolve_board("Cohere (London office)") == Board("ashby", "cohere")


def test_resolve_board_careers_url_takes_precedence() -> None:
    board = resolve_board("Monzo", "https://jobs.lever.co/monzo-new")
    assert board == Board("lever", "monzo-new")


def test_resolve_board_unknown_employer_is_none() -> None:
    # No guessing: unknown names must not resolve to a lookalike board.
    assert resolve_board("National Physical Laboratory") is None
    assert resolve_board("Barclays", "https://search.jobs.barclays/") is None


def test_adzuna_employer_name_aliases_and_default() -> None:
    assert adzuna_employer_name("LSEG") == "London Stock Exchange Group"
    assert adzuna_employer_name("Amazon / AWS") == "Amazon"
    assert adzuna_employer_name("QuantumBlack (McKinsey)") == "QuantumBlack"
    assert adzuna_employer_name("Barclays") == "Barclays"


def test_plan_employers_groups_by_ats() -> None:
    boards, unresolved = plan_employers(
        ["Monzo", "Palantir", "Barclays", "Acme"],
        {"Acme": "https://jobs.ashbyhq.com/acme"},
    )
    assert boards == {
        "greenhouse": {"Monzo": "monzo"},
        "lever": {"Palantir": "palantir"},
        "ashby": {"Acme": "acme"},
    }
    assert unresolved == ["Barclays"]


# ---------------------------------------------------------------------------
# Location filter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("posting", "wanted", "expected"),
    [
        ("London", "London, UK", True),
        ("Hatfield, United Kingdom", "London, UK", True),
        ("Remote (UK)", "London, UK", True),
        ("Tokyo, Japan", "London, UK", False),
        ("Kyiv, Ukraine", "UK", False),
        ("Manchester, United Kingdom", "London", False),
        ("Unknown", "London", True),
        ("New London, CT", "London", True),
    ],
)
def test_location_matches(posting: str, wanted: str, expected: bool) -> None:
    assert location_matches(posting, wanted) is expected


# ---------------------------------------------------------------------------
# Excel employer list
# ---------------------------------------------------------------------------


def _write_workbook(path: Path) -> None:
    wb = openpyxl.Workbook()
    guide = wb.active
    assert guide is not None
    guide.title = "How to use"
    guide.append(["How to use this list", None])
    guide.append(["Company", "Made Tech"])  # mentions "Company" but is not the table
    sheet = wb.create_sheet("Employers")
    sheet.append(["#", "Company", "Bucket", "Suggested star", "My star (Y)", "Careers page link"])
    sheet.append([1, "Monzo", "London finance", "Y", "Y", None])
    sheet.append([2, "Barclays", "London finance", None, None, "https://search.jobs.barclays/"])
    sheet.append([3, "Faculty", "Consulting", None, "y", "https://jobs.ashbyhq.com/faculty"])
    sheet.append([None, None, None, None, None, None])
    wb.save(path)


def test_load_employers_reads_employer_sheet(tmp_path: Path) -> None:
    path = tmp_path / "employers.xlsx"
    _write_workbook(path)
    employers = load_employers(path)
    assert [e.name for e in employers] == ["Monzo", "Barclays", "Faculty"]
    assert employers[2] == TargetEmployer(
        name="Faculty",
        careers_url="https://jobs.ashbyhq.com/faculty",
        bucket="Consulting",
        starred=True,
    )


def test_load_employers_uses_my_star_not_suggested(tmp_path: Path) -> None:
    path = tmp_path / "employers.xlsx"
    _write_workbook(path)
    assert [e.name for e in load_employers(path, starred_only=True)] == ["Monzo", "Faculty"]


def test_load_employers_bucket_filter(tmp_path: Path) -> None:
    path = tmp_path / "employers.xlsx"
    _write_workbook(path)
    names = [e.name for e in load_employers(path, buckets=["london FINANCE"])]
    assert names == ["Monzo", "Barclays"]


def test_load_employers_without_company_header_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.xlsx"
    wb = openpyxl.Workbook()
    sheet = wb.active
    assert sheet is not None
    sheet.append(["Name", "URL"])
    wb.save(path)
    with pytest.raises(ValueError):
        load_employers(path)


# ---------------------------------------------------------------------------
# web_scraper /search routing
# ---------------------------------------------------------------------------


class MemoryCache:
    """In-memory stand-in for the job_recommender cache service."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get_cached(self, key: str) -> str | None:
        return self.data.get(key)

    async def set_cached(self, key: str, value: str) -> None:
        self.data[key] = value


@pytest.fixture
def memory_cache() -> MemoryCache:
    return MemoryCache()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, memory_cache: MemoryCache) -> Iterator[TestClient]:
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    monkeypatch.delenv("REED_API_KEY", raising=False)
    monkeypatch.setattr(scraper_api, "_EMPLOYER_SEARCH_DELAY", 0.0)
    monkeypatch.setattr(scraper_api, "_cache", lambda request: memory_cache)
    with TestClient(app) as c:
        yield c


def _greenhouse_job(title: str, location: str) -> dict[str, Any]:
    return {
        "title": title,
        "location": {"name": location},
        "absolute_url": f"https://job-boards.greenhouse.io/monzo/jobs/{title}/{location}",
        "updated_at": "2026-10-01T00:00:00Z",
    }


def _mock_anthropic(text: str) -> anthropic.AsyncAnthropic:
    block = MagicMock(spec=anthropic.types.TextBlock)
    block.text = text
    response = MagicMock()
    response.content = [block]
    c = MagicMock(spec=anthropic.AsyncAnthropic)
    c.messages = MagicMock()
    c.messages.create = AsyncMock(return_value=response)
    return c  # type: ignore[return-value]


def _adzuna_job(company: str, title: str) -> dict[str, Any]:
    return {
        "title": title,
        "company": {"display_name": company},
        "location": {"display_name": "London"},
        "redirect_url": f"https://adzuna.example/{company}/{title}",
        "created": "2026-10-01T00:00:00Z",
    }


def test_search_routes_known_employer_to_ats_and_rest_to_adzuna(client: TestClient) -> None:
    with respx.mock:
        greenhouse = respx.get("https://boards-api.greenhouse.io/v1/boards/monzo/jobs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jobs": [
                        _greenhouse_job("Data Analyst", "London"),
                        _greenhouse_job("Data Analyst", "Barcelona"),
                        _greenhouse_job("Junior Analytics Engineer", "London"),
                        _greenhouse_job("Product Designer", "London"),
                    ]
                },
            )
        )
        adzuna = respx.get("https://api.adzuna.com/v1/api/jobs/gb/search/1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        _adzuna_job("Barclays", "Data Analyst"),
                        _adzuna_job("Barclays Execution Services", "Data Analyst II"),
                        _adzuna_job("Barclaycard Recruitment Partner", "Data Analyst"),
                    ]
                },
            )
        )
        resp = client.post(
            "/search",
            json={
                "query": {
                    "role": "Data Analyst",
                    "job_type": "full-time",
                    "location": "London",
                    "companies": ["Monzo", "Barclays"],
                },
                "expand_aliases": False,
            },
        )

    assert resp.status_code == 200
    postings = resp.json()["postings"]
    by_source: dict[str, list[tuple[str, str]]] = {}
    for p in postings:
        by_source.setdefault(p["source"], []).append((p["company"], p["role"]))

    # Board fetched once; Barcelona dropped by the location filter; designer not a match.
    assert greenhouse.call_count == 1
    assert by_source["greenhouse"] == [("Monzo", "Data Analyst")]
    # Adzuna called with the employer filter; lookalike employer names dropped; the
    # kept postings carry the spreadsheet's company name.
    assert adzuna.call_count == 1
    assert adzuna.calls[0].request.url.params["company"] == "Barclays"
    assert by_source["adzuna"] == [("Barclays", "Data Analyst"), ("Barclays", "Data Analyst II")]


def test_search_matches_board_titles_against_role_aliases(client: TestClient) -> None:
    app.dependency_overrides[get_anthropic] = lambda: _mock_anthropic('["Analytics Engineer"]')
    try:
        with respx.mock:
            board = respx.get("https://boards-api.greenhouse.io/v1/boards/monzo/jobs").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "jobs": [
                            _greenhouse_job("Data Analyst", "London"),
                            _greenhouse_job("Junior Analytics Engineer", "London"),
                        ]
                    },
                )
            )
            resp = client.post(
                "/search",
                json={
                    "query": {
                        "role": "Data Analyst",
                        "job_type": "full-time",
                        "companies": ["Monzo"],
                    },
                    "expand_aliases": True,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert board.call_count == 1  # one fetch serves the role and every alias
    roles = sorted(p["role"] for p in resp.json()["postings"])
    assert roles == ["Data Analyst", "Junior Analytics Engineer"]


def test_search_careers_url_pins_board(client: TestClient) -> None:
    with respx.mock:
        route = respx.get("https://api.lever.co/v0/postings/acme-labs?mode=json").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "text": "Data Analyst",
                        "categories": {"location": "London"},
                        "hostedUrl": "https://jobs.lever.co/acme-labs/1",
                        "createdAt": 1767225600000,
                    }
                ],
            )
        )
        resp = client.post(
            "/search",
            json={
                "query": {
                    "role": "Data Analyst",
                    "job_type": "full-time",
                    "companies": ["Acme"],
                    "company_urls": {"Acme": "https://jobs.lever.co/acme-labs"},
                },
                "expand_aliases": False,
            },
        )
    assert route.call_count == 1
    assert [p["company"] for p in resp.json()["postings"]] == ["Acme"]


@pytest.mark.parametrize(
    ("posting", "expected"),
    [
        ("London", True),
        ("Exeter", True),
        ("Cardiff, London or Remote (UK)", True),
        ("Home worker, Australia (Victoria / New South Wales / Western Australia)", False),
        ("London, ON", False),
        ("Boston, MA", False),
    ],
)
def test_location_uk_includes_uk_places_but_not_lookalikes(posting: str, expected: bool) -> None:
    assert location_matches(posting, "UK") is expected
