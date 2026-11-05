"""Load a target-employer list from an Excel workbook (.xlsx).

Columns are found by header text, not position, so the sheet can be reordered or
extended freely. Recognised headers (case-insensitive, matched by prefix):

- ``Company`` (required) — employer name
- ``Careers page`` — careers URL; an ATS board link pins that board for the search
- ``My star`` — ``Y`` marks a starred employer (used by ``--starred``)
- ``Bucket`` — grouping such as "London tech" (used by ``--bucket``)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import openpyxl

_HEADER_SCAN_ROWS = 10
_PREFERRED_SHEET = "employers"


@dataclass(frozen=True)
class TargetEmployer:
    """One row of the employer list."""

    name: str
    careers_url: str | None = None
    bucket: str | None = None
    starred: bool = False


def _cell_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _find_columns(header: tuple[Any, ...]) -> dict[str, int]:
    """Map logical column names to indexes in *header* by prefix match."""
    prefixes = {
        "company": "company",
        "careers_url": "careers page",
        "starred": "my star",
        "bucket": "bucket",
    }
    columns: dict[str, int] = {}
    for i, cell in enumerate(header):
        text = _cell_text(cell).lower()
        for key, prefix in prefixes.items():
            if key not in columns and text.startswith(prefix):
                columns[key] = i
    return columns


def _locate_table(
    workbook: openpyxl.Workbook,
) -> tuple[list[tuple[Any, ...]], dict[str, int]]:
    """Return the data rows and column map of the sheet holding the employer table."""
    sheets = sorted(workbook.worksheets, key=lambda ws: ws.title.lower() != _PREFERRED_SHEET)
    for sheet in sheets:
        rows = list(sheet.iter_rows(values_only=True))
        for i, row in enumerate(rows[:_HEADER_SCAN_ROWS]):
            columns = _find_columns(row)
            # A real header row has "Company" plus at least one other known column —
            # this skips instruction sheets that merely mention the word "Company".
            if "company" in columns and len(columns) > 1:
                return rows[i + 1 :], columns
    raise ValueError("no sheet has a header row with a 'Company' column")


def load_employers(
    path: Path,
    *,
    starred_only: bool = False,
    buckets: list[str] | None = None,
) -> list[TargetEmployer]:
    """Read target employers from the workbook at *path*.

    *starred_only* keeps rows whose ``My star`` cell is ``Y``/``yes``. *buckets*, when
    given, keeps rows whose ``Bucket`` matches one of them (case-insensitive).
    """
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows, columns = _locate_table(workbook)
    finally:
        workbook.close()

    def cell(row: tuple[Any, ...], key: str) -> str:
        index = columns.get(key)
        return _cell_text(row[index]) if index is not None and index < len(row) else ""

    wanted_buckets = {b.strip().lower() for b in buckets or []}
    employers: list[TargetEmployer] = []
    for row in rows:
        name = cell(row, "company")
        if not name:
            continue
        employer = TargetEmployer(
            name=name,
            careers_url=cell(row, "careers_url") or None,
            bucket=cell(row, "bucket") or None,
            starred=cell(row, "starred").lower() in ("y", "yes"),
        )
        if starred_only and not employer.starred:
            continue
        if wanted_buckets and (employer.bucket or "").lower() not in wanted_buckets:
            continue
        employers.append(employer)
    return employers
