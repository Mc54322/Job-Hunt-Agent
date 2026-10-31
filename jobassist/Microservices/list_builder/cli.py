"""Command line for the list_builder: text list in, employer workbook out.

Works on its own (no other JobAssist services needed):
    uv run jobassist-make-list my-companies.txt -o "My employers.xlsx" --university Leeds
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from jobassist.Microservices.list_builder.parsing.text_list import SAMPLE_TEXT, parse_text_list
from jobassist.Microservices.list_builder.workbook.builder import build_workbook

app = typer.Typer(help="Turn a text list of companies into a JobAssist employer workbook.")


@app.command()
def make(
    text_file: Optional[Path] = typer.Argument(
        None, help="Text file: one company per line; 'Bucket:' lines start a group."
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Where to save the .xlsx (default: next to the text file)."
    ),
    university: Optional[str] = typer.Option(
        None, "--university", "-u", help="Names the alumni column, e.g. 'Leeds'."
    ),
    example: bool = typer.Option(False, "--example", help="Print an example text list and exit."),
) -> None:
    """Build the employer workbook from TEXT_FILE."""
    if example:
        typer.echo(SAMPLE_TEXT)
        raise typer.Exit(0)
    if text_file is None or not text_file.exists():
        typer.echo("Give the text file to convert, e.g.: jobassist-make-list companies.txt")
        typer.echo("Run with --example to see the format.")
        raise typer.Exit(1)

    parsed = parse_text_list(text_file.read_text(encoding="utf-8", errors="replace"))
    if university:
        parsed.settings.university = university
    for warning in parsed.warnings:
        typer.echo(f"Note: {warning}")
    if not parsed.employers:
        raise typer.Exit(1)

    target = output or text_file.with_suffix(".xlsx")
    target.write_bytes(build_workbook(parsed))
    starred = sum(e.starred for e in parsed.employers)
    typer.echo(
        f"Saved {target} — {len(parsed.employers)} employers in {len(parsed.buckets)} groups, "
        f"{starred} starred."
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
