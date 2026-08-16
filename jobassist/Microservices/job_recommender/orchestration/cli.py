"""CLI entry point — a thin client of the job_recommender `/recommend` API.

This is a temporary front-end stand-in: it collects arguments, calls the running
services over HTTP, and renders the results. It will be replaced by the real front
end. No business logic lives here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import httpx
import typer
from rich.console import Console
from rich.table import Table

from jobassist.Microservices.job_recommender.models import JobQuery, ScoredPosting
from jobassist.Microservices.job_recommender.reporting.report import generate_report

app = typer.Typer(
    name="jobassist",
    help="Personal job aggregator — search, score, and surface the best-fit postings.",
    no_args_is_help=True,
)

_console = Console()

_JOB_RECOMMENDER_URL = os.environ.get("JOB_RECOMMENDER_URL", "http://localhost:8003")
_WEB_SCRAPER_URL = os.environ.get("WEB_SCRAPER_URL", "http://localhost:8001")


@app.callback()
def _callback() -> None:
    """JobAssist — personal job search, deduplication, and LLM scoring."""


def _score_colour(score: float) -> str:
    if score >= 0.7:
        return "green"
    if score >= 0.5:
        return "yellow"
    return "red"


def _render_table(results: list[ScoredPosting]) -> Table:
    """Build a Rich table from *results* sorted by score descending."""
    table = Table(show_header=True, header_style="bold cyan", show_lines=False, expand=True)
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Score", width=6, justify="center")
    table.add_column("Company", min_width=12)
    table.add_column("Role", min_width=16)
    table.add_column("Location", min_width=12)
    table.add_column("Salary", min_width=10)
    table.add_column("Source", width=11)
    table.add_column("URL")

    sorted_results = sorted(results, key=lambda r: r.score, reverse=True)
    for i, sp in enumerate(sorted_results, 1):
        colour = _score_colour(sp.score)
        table.add_row(
            str(i),
            f"[{colour}]{sp.score:.2f}[/{colour}]",
            sp.posting.company,
            sp.posting.role,
            sp.posting.location,
            sp.posting.salary_raw or "—",
            sp.posting.source,
            sp.posting.url,
        )
    return table


def _resolve_index(index: str) -> list[str]:
    """Resolve an index name to its constituent companies via the web_scraper API."""
    resp = httpx.get(f"{_WEB_SCRAPER_URL}/companies/{index}", timeout=30.0)
    resp.raise_for_status()
    companies: list[str] = resp.json()["companies"]
    return companies


@app.command()
def search(
    role: str = typer.Argument(..., help="Job title to search for, e.g. 'Software Engineer'"),
    job_type: str = typer.Argument(
        ..., help="Employment type: full-time, part-time, contract, internship"
    ),
    location: Optional[str] = typer.Option(
        None, "--location", "-l", help="Geographic filter, e.g. 'London, UK'"
    ),
    company: Optional[list[str]] = typer.Option(
        None, "--company", "-c", help="Target a specific company (repeatable)"
    ),
    max_results: int = typer.Option(50, "--max-results", "-n", help="Max postings to return"),
    resume: Optional[Path] = typer.Option(
        None,
        "--resume",
        "-r",
        help="Path to your resume (plain text). Overrides JOBASSIST_RESUME env var.",
        envvar="JOBASSIST_RESUME",
    ),
    report: Optional[Path] = typer.Option(
        None, "--report", help="Write a Markdown report to this path."
    ),
    index: Optional[str] = typer.Option(
        None, "--index", help="Expand companies from a stock index (e.g. 'ftse100')."
    ),
    aliases: bool = typer.Option(
        True, "--aliases/--no-aliases", help="Expand role to synonyms before searching."
    ),
    one_per_company: bool = typer.Option(
        True,
        "--one-per-company/--all-per-company",
        help="Show only the highest-scored posting per company (default: on).",
    ),
) -> None:
    """Search for job postings and score them against your resume."""
    if resume is None or not resume.exists():
        _console.print("[red]Error:[/red] --resume / JOBASSIST_RESUME must point to a file.")
        raise typer.Exit(1)

    resume_text = resume.read_text()

    resolved_companies: list[str] = list(company or [])
    if index is not None:
        try:
            resolved_companies.extend(_resolve_index(index))
        except httpx.HTTPError as exc:
            _console.print(f"[red]Error:[/red] could not resolve index '{index}': {exc}")
            raise typer.Exit(1) from exc

    query = JobQuery(
        role=role,
        job_type=job_type,
        location=location,
        companies=resolved_companies,
        max_results=max_results,
    )

    _console.print(f"\nSearching for [bold]{query.role}[/bold] ({query.job_type})")
    if query.location:
        _console.print(f"Location: {query.location}")
    if query.companies:
        _console.print(f"Companies: {', '.join(query.companies)}")
    _console.print()

    try:
        resp = httpx.post(
            f"{_JOB_RECOMMENDER_URL}/recommend",
            json={
                "query": query.model_dump(mode="json"),
                "resume": resume_text,
                "one_per_company": one_per_company,
                "expand_aliases": aliases,
            },
            timeout=300.0,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        _console.print(
            f"[red]Error:[/red] could not reach job_recommender at "
            f"{_JOB_RECOMMENDER_URL}: {exc}"
        )
        raise typer.Exit(1) from exc

    results = [ScoredPosting.model_validate(r) for r in resp.json()["results"]]

    if not results:
        _console.print("No postings found.")
        raise typer.Exit(0)

    _console.print()
    _console.print(_render_table(results))
    _console.print(f"\n[dim]{len(results)} postings scored.[/dim]")

    if report is not None:
        generate_report(results, query, report)
        _console.print(f"[dim]Report written to {report}[/dim]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
