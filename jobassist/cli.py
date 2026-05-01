"""CLI entry point — no business logic lives here."""

from __future__ import annotations

from typing import Optional

import typer

from jobassist.schemas import JobQuery

app = typer.Typer(
    name="jobassist",
    help="Personal job aggregator — search, score, and surface the best-fit postings.",
    no_args_is_help=True,
)


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
) -> None:
    """Search for job postings and score them against your resume."""
    query = JobQuery(
        role=role,
        job_type=job_type,
        location=location,
        companies=company or [],
        max_results=max_results,
    )
    typer.echo(f"Searching for: {query.role} ({query.job_type})")
    if query.location:
        typer.echo(f"Location: {query.location}")
    if query.companies:
        typer.echo(f"Companies: {', '.join(query.companies)}")
    typer.echo("(pipeline not yet implemented)")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
