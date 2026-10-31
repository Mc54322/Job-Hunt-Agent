"""Tests for the CLI — table rendering and argument handling."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import openpyxl
import respx
from typer.testing import CliRunner

from jobassist.Microservices.job_recommender.models import JobPosting, ScoredPosting
from jobassist.Microservices.job_recommender.orchestration.cli import _render_table, app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

runner = CliRunner()


def _sp(
    company: str = "Acme",
    role: str = "Software Engineer",
    location: str = "London, UK",
    score: float = 0.8,
    source: str = "greenhouse",
    salary: str | None = None,
) -> ScoredPosting:
    return ScoredPosting(
        posting=JobPosting(
            company=company,
            role=role,
            location=location,
            url=f"https://example.com/{company.lower()}",
            source=source,
            salary_raw=salary,
        ),
        score=score,
        rationale="Test rationale.",
    )


# ---------------------------------------------------------------------------
# _render_table
# ---------------------------------------------------------------------------


def test_render_table_has_headers() -> None:
    table = _render_table([_sp()])
    assert table.columns[1].header == "Score"
    assert table.columns[2].header == "Company"
    assert table.columns[3].header == "Role"


def test_render_table_row_count() -> None:
    results = [_sp(company="Acme"), _sp(company="Beta", score=0.6)]
    table = _render_table(results)
    assert table.row_count == 2


def test_render_table_sorted_by_score_descending() -> None:
    low = _sp(company="Low", score=0.3)
    high = _sp(company="High", score=0.9)
    mid = _sp(company="Mid", score=0.6)
    table = _render_table([low, high, mid])
    # First row should be the highest score
    first_cell = table.columns[2]._cells[0]  # type: ignore[attr-defined]
    assert "High" in first_cell


def test_render_table_empty() -> None:
    table = _render_table([])
    assert table.row_count == 0


def test_render_table_salary_dash_when_none() -> None:
    table = _render_table([_sp(salary=None)])
    salary_cell = table.columns[5]._cells[0]  # type: ignore[attr-defined]
    assert "—" in salary_cell


def test_render_table_salary_shown_when_present() -> None:
    table = _render_table([_sp(salary="£50,000")])
    salary_cell = table.columns[5]._cells[0]  # type: ignore[attr-defined]
    assert "£50,000" in salary_cell


# ---------------------------------------------------------------------------
# CLI argument handling via Typer test runner
# ---------------------------------------------------------------------------


def test_help_exits_cleanly() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "search" in result.output.lower()


def test_search_help() -> None:
    result = runner.invoke(app, ["search", "--help"])
    assert result.exit_code == 0
    assert "--resume" in result.output


def test_search_exits_with_error_when_no_resume(tmp_path: Path) -> None:
    result = runner.invoke(app, ["search", "Engineer", "full-time"])
    assert result.exit_code != 0


def test_search_exits_with_error_when_resume_missing(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["search", "Engineer", "full-time", "--resume", str(tmp_path / "nonexistent.txt")],
    )
    assert result.exit_code != 0


def test_search_exits_with_error_when_recommender_unreachable(tmp_path: Path) -> None:
    resume = tmp_path / "resume.txt"
    resume.write_text("My resume.")
    # Mocked so the test never reaches a real service that happens to be running locally.
    with respx.mock:
        respx.post("http://localhost:8003/recommend").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        result = runner.invoke(
            app,
            ["search", "Engineer", "full-time", "--resume", str(resume)],
        )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# --employers
# ---------------------------------------------------------------------------


def _employer_book(path: Path) -> None:
    wb = openpyxl.Workbook()
    sheet = wb.active
    assert sheet is not None
    sheet.title = "Employers"
    sheet.append(["Company", "Bucket", "My star (Y)", "Careers page link"])
    sheet.append(["Monzo", "London finance", "Y", None])
    sheet.append(["Acme", "AI startups", None, "https://jobs.lever.co/acme"])
    wb.save(path)


def test_search_with_employers_sends_companies_and_urls(tmp_path: Path) -> None:
    resume = tmp_path / "resume.txt"
    resume.write_text("My resume.")
    book = tmp_path / "employers.xlsx"
    _employer_book(book)
    with respx.mock:
        route = respx.post("http://localhost:8003/recommend").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        result = runner.invoke(
            app,
            ["search", "Data Analyst", "full-time", "--resume", str(resume),
             "--employers", str(book)],
        )
    assert result.exit_code == 0, result.output
    sent = json.loads(route.calls[0].request.content)["query"]
    assert sent["companies"] == ["Monzo", "Acme"]
    assert sent["company_urls"] == {"Acme": "https://jobs.lever.co/acme"}


def test_search_with_employers_starred_only(tmp_path: Path) -> None:
    resume = tmp_path / "resume.txt"
    resume.write_text("My resume.")
    book = tmp_path / "employers.xlsx"
    _employer_book(book)
    with respx.mock:
        route = respx.post("http://localhost:8003/recommend").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        runner.invoke(
            app,
            ["search", "Data Analyst", "full-time", "--resume", str(resume),
             "--employers", str(book), "--starred"],
        )
    assert json.loads(route.calls[0].request.content)["query"]["companies"] == ["Monzo"]


def test_search_with_employers_no_match_exits(tmp_path: Path) -> None:
    resume = tmp_path / "resume.txt"
    resume.write_text("My resume.")
    book = tmp_path / "employers.xlsx"
    _employer_book(book)
    result = runner.invoke(
        app,
        ["search", "Data Analyst", "full-time", "--resume", str(resume),
         "--employers", str(book), "--bucket", "Nope"],
    )
    assert result.exit_code == 1
    assert "no employers matched" in result.output


def test_search_sends_refresh_and_company_sites(tmp_path: Path) -> None:
    resume = tmp_path / "resume.txt"
    resume.write_text("My resume.")
    with respx.mock:
        route = respx.post("http://localhost:8003/recommend").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        runner.invoke(
            app,
            ["search", "Data Analyst", "full-time", "--resume", str(resume),
             "-c", "Acme", "--company-sites", "--refresh"],
        )
    sent = json.loads(route.calls[0].request.content)
    assert sent["refresh"] is True and sent["search_company_sites"] is True
