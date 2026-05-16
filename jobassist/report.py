"""Markdown report generator for scored job postings."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from jobassist.schemas import JobQuery, ScoredPosting


def generate_report(
    results: list[ScoredPosting],
    query: JobQuery,
    path: Path,
) -> None:
    """Write a Markdown report of *results* to *path*, sorted by score descending."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(results, query), encoding="utf-8")


def _render(results: list[ScoredPosting], query: JobQuery) -> str:
    sorted_results = sorted(results, key=lambda r: r.score, reverse=True)
    lines: list[str] = []

    # --- Header ---
    title_parts = [query.role, f"({query.job_type})"]
    if query.location:
        title_parts.append(f"— {query.location}")
    lines += [
        f"# Job Search Report — {' '.join(title_parts)}",
        f"Generated: {date.today().isoformat()}",
        "",
    ]

    if not sorted_results:
        lines.append("_No postings scored._")
        return "\n".join(lines)

    # --- Summary table ---
    lines += [
        "## Summary",
        "",
        "| # | Score | Company | Role | Location | Salary | Source |",
        "|---|-------|---------|------|----------|--------|--------|",
    ]
    for i, sp in enumerate(sorted_results, 1):
        p = sp.posting
        salary = p.salary_raw or "—"
        lines.append(
            f"| {i} | {sp.score:.2f} | {p.company} | {p.role} "
            f"| {p.location} | {salary} | {p.source} |"
        )

    lines.append("")

    # --- Detailed sections ---
    lines.append("## Postings")
    lines.append("")
    for i, sp in enumerate(sorted_results, 1):
        p = sp.posting
        lines += [
            f"### {i}. {p.role} at {p.company} — {sp.score:.2f}",
            "",
            f"**Location:** {p.location}  ",
        ]
        if p.salary_raw:
            lines.append(f"**Salary:** {p.salary_raw}  ")
        lines += [
            f"**Source:** {p.source}  ",
            f"**URL:** {p.url}",
            "",
        ]
        if p.description:
            lines += [
                "**Description:**  ",
                p.description,
                "",
            ]
        lines += [
            "**Why this fits:**  ",
            sp.rationale,
            "",
            "---",
            "",
        ]

    return "\n".join(lines)
