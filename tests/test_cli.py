"""Tests for the CLI — table rendering and argument handling."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from jobassist.cli import _render_table, app
from jobassist.schemas import JobPosting, ScoredPosting

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


def test_search_exits_with_error_when_no_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resume = tmp_path / "resume.txt"
    resume.write_text("My resume.")
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    result = runner.invoke(
        app,
        ["search", "Engineer", "full-time", "--resume", str(resume)],
    )
    assert result.exit_code != 0
