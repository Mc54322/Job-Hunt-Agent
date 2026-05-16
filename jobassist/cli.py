"""CLI entry point — no business logic lives here."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import AsyncIterator, Optional

import anthropic
import httpx
import typer
from rich.console import Console
from rich.table import Table

from jobassist.dedupe import deduplicate
from jobassist.schemas import JobPosting, JobQuery, ScoredPosting
from jobassist.scorer import ScoringPipeline
from jobassist.sources.adzuna import AdzunaFetcher
from jobassist.sources.base import Source
from jobassist.sources.greenhouse import GreenhouseFetcher
from jobassist.store import Store

app = typer.Typer(
    name="jobassist",
    help="Personal job aggregator — search, score, and surface the best-fit postings.",
    no_args_is_help=True,
)

_console = Console()


def _score_colour(score: float) -> str:
    if score >= 0.7:
        return "green"
    if score >= 0.5:
        return "yellow"
    return "red"


def _render_table(results: list[ScoredPosting]) -> Table:
    """Build a Rich table from *results* sorted by score descending."""
    table = Table(
        show_header=True,
        header_style="bold cyan",
        show_lines=False,
        expand=True,
    )
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


async def _run_pipeline(
    query: JobQuery,
    resume: str,
    adzuna_id: str | None,
    adzuna_key: str | None,
    db_path: str,
) -> list[ScoredPosting]:
    """Fetch, deduplicate, and score postings for *query*."""
    store = Store(db_path)
    anthropic_client = anthropic.AsyncAnthropic()
    scorer = ScoringPipeline(anthropic_client, resume, store)

    async with httpx.AsyncClient() as http:
        sources: list[Source] = []

        # One Greenhouse fetcher covers all named companies via query.companies
        if query.companies:
            sources.append(GreenhouseFetcher(http))

        # Adzuna for broad search (only when credentials are available)
        if adzuna_id and adzuna_key:
            sources.append(AdzunaFetcher(http, adzuna_id, adzuna_key))

        async def _merged() -> AsyncIterator[JobPosting]:
            for source in sources:
                async for posting in await source.search(query):
                    yield posting

        scored: list[ScoredPosting] = []
        async for posting in deduplicate(_merged()):
            _console.print(
                f"  Scoring [bold]{posting.company}[/bold] — {posting.role}…",
                highlight=False,
            )
            sp = await scorer.score(posting)
            scored.append(sp)
            store.save(posting)

    store.close()
    return scored


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
    db: str = typer.Option(
        str(Path.home() / ".jobassist" / "data.db"),
        "--db",
        help="Path to the SQLite store",
        envvar="JOBASSIST_DB",
    ),
) -> None:
    """Search for job postings and score them against your resume."""
    if resume is None or not resume.exists():
        _console.print("[red]Error:[/red] --resume / JOBASSIST_RESUME must point to a file.")
        raise typer.Exit(1)

    resume_text = resume.read_text()

    adzuna_id = os.environ.get("ADZUNA_APP_ID")
    adzuna_key = os.environ.get("ADZUNA_APP_KEY")

    query = JobQuery(
        role=role,
        job_type=job_type,
        location=location,
        companies=company or [],
        max_results=max_results,
    )

    _console.print(f"\nSearching for [bold]{query.role}[/bold] ({query.job_type})")
    if query.location:
        _console.print(f"Location: {query.location}")
    if query.companies:
        _console.print(f"Companies: {', '.join(query.companies)}")
    _console.print()

    if not adzuna_id or not adzuna_key:
        _console.print(
            "[yellow]Warning:[/yellow] ADZUNA_APP_ID / ADZUNA_APP_KEY not set — "
            "Adzuna search skipped."
        )

    if not query.companies and (not adzuna_id or not adzuna_key):
        _console.print("[red]Error:[/red] No sources available. Set Adzuna credentials or "
                       "supply at least one --company.")
        raise typer.Exit(1)

    results = asyncio.run(
        _run_pipeline(query, resume_text, adzuna_id, adzuna_key, db)
    )

    if not results:
        _console.print("No postings found.")
        raise typer.Exit(0)

    _console.print()
    _console.print(_render_table(results))
    _console.print(f"\n[dim]{len(results)} postings scored.[/dim]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
