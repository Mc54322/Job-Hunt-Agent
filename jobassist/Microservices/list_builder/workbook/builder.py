"""Build the employer-tracking workbook (.xlsx) from a parsed list.

Recreates the original JobAssist tracker: a "How to use" sheet, the "Employers" table
(navy pre-filled columns A–J, gold "yours to fill in" columns K–S, a colour per bucket,
Status / My star dropdowns, frozen panes, filters) and a "Summary" sheet whose formulas
count stars and progress per bucket. Dropdowns and formulas reach well past the last
company so rows added by hand later are included.
"""

from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from jobassist.Microservices.list_builder.models import ParsedList

FONT_NAME = "Arial"
NAVY = "FF1F3864"
GOLD = "FF7F6000"
YOURS = "FFFFF2CC"
BORDER_GREY = "FFD0D0D0"
SUGGESTED_RED = "FFC00000"
DATE_FORMAT = "dd\\ mmm\\ yyyy"
# The original tracker's bucket colours, then more for longer lists.
BUCKET_COLOURS = (
    "FFDDEBF7", "FFE2EFDA", "FFFCE4D6", "FFEDE7F6", "FFFFF9C4", "FFE0F2F1",
    "FFF8BBD0", "FFD7CCC8", "FFCFD8DC", "FFFFE0B2",
)
STATUSES = (
    "Not started", "Researching", "Contact found", "Approached", "Applied", "Interview",
    "Rejected", "Offer", "Not a fit",
)
# Rows covered by dropdowns and Summary formulas, so hand-added rows count too.
MIN_TABLE_ROWS = 500

_THIN_BOTTOM = Border(bottom=Side(style="thin", color=BORDER_GREY))
_WRAP_TOP = Alignment(wrap_text=True, vertical="top")
_HEADER_ALIGN = Alignment(wrap_text=True, vertical="center")


def _alumni_header(parsed: ParsedList) -> str:
    university = parsed.settings.university
    return f"{university} alumni" if university else "Alumni contacts"


def _columns(parsed: ParsedList) -> list[tuple[str, float | None, bool]]:
    """(header, width, is_yours) for columns A–S."""
    return [
        ("#", 5.0, False),
        ("Company", 26.0, False),
        ("Bucket", 18.0, False),
        ("Location", 26.0, False),
        ("Why it's on the list", 40.0, False),
        ("Roles to search for", 34.0, False),
        ("CV version", 15.0, False),
        ("Entry route", 24.0, False),
        ("Odds", 10.0, False),
        ("Suggested star", 13.0, False),
        ("My star (Y)", 9.0, True),
        ("Careers page link", 22.0, True),
        ("Recruiter / talent contact", 13.0, True),
        ("Team member contact", 13.0, True),
        (_alumni_header(parsed), 20.0, True),
        ("Status", 14.0, True),
        ("Last action date", 13.0, True),
        ("Next action", 22.0, True),
        ("Notes", 24.0, True),
    ]


def _font(size: float = 10, bold: bool = False, colour: str | None = None) -> Font:
    return Font(name=FONT_NAME, size=size, bold=bold, color=colour)


def _how_to_use(ws: Worksheet, parsed: ParsedList) -> None:
    university = parsed.settings.university
    alumni = _alumni_header(parsed)
    alumni_search = (
        f"any {university} alumni (LinkedIn search: company name + {university})"
        if university
        else "any alumni from your university (LinkedIn search: company name + your university)"
    )
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 100
    rows: list[tuple[int, str, str | None, float, bool]] = [
        (1, "How to use this list", None, 12, True),
        (3, "Yellow columns (K to S) are yours to fill in. Everything else can be filled in "
            "or edited as you research.", None, 10, False),
        (4, "Suggested star (column J) is optional — for example a pick from a mentor or "
            "careers adviser. Column K is your own star, which is what counts.", None, 10, False),
        (5, "Odds: Realistic = graduate or junior hires are normal there. Stretch = very "
            "competitive or rarely hires at your level. Keep stretches to 3 or 4 of your 20.",
         None, 10, False),
        (6, "Status options: " + ", ".join(STATUSES) + ".", None, 10, False),
        (8, "Which day uses which columns", None, 11, True),
        (9, "Week 1 Day 3", "Read through the list. Delete obvious misfits, add any companies "
            "you already know (aim to stay at 100+). Fill in Careers page link as you go.",
         10, False),
        (10, "Week 1 Day 4", "Put Y in My star for your top 20. Sort by My star so they sit "
             "at the top.", 10, False),
        (11, "Week 2 Day 1", "For each starred company, find one recruiter or talent person, "
             f"one person on the relevant team, and {alumni_search}. Fill columns M, N, O and "
             "set Status to Contact found.", 10, False),
        (12, "Week 2 Day 2", "Message 5 of those people. Set Status to Approached and fill "
             "Last action date and Next action (e.g. 'follow up 3 Nov').", 10, False),
        (13, "Every week", "When you apply anywhere on the list, set Status to Applied with the "
             "date. Use Next action for 7-day follow-ups. The Summary tab counts this for the "
             "weekly review.", 10, False),
        (15, "Example of a filled-in row", None, 11, True),
        (16, "Company", "Made Tech", 10, False),
        (17, "My star", "Y", 10, False),
        (18, "Careers page link", "the company's careers page URL", 10, False),
        (19, "Recruiter / talent contact", "Jane Smith, Talent Partner (LinkedIn)", 10, False),
        (20, "Team member contact", "Ali Khan, Data Engineer", 10, False),
        (21, alumni, "Sam Lee, CS 2022", 10, False),
        (22, "Status", "Approached", 10, False),
        (23, "Last action date", "27 Oct 2026", 10, False),
        (24, "Next action", "Follow up 3 Nov if no reply", 10, False),
        (25, "Notes", "Asked about junior data engineer intake; mentioned their DWP work",
         10, False),
        (27, "The example names above are made up to show the format.", None, 10, False),
    ]
    for row, a, b, size, bold in rows:
        ws.cell(row, 1, a).font = _font(size, bold)
        ws.cell(row, 1).alignment = _WRAP_TOP
        if b is not None:
            ws.cell(row, 2, b).font = _font(size, bold)
            ws.cell(row, 2).alignment = _WRAP_TOP
        elif row in (3, 4, 5, 6, 27):
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)


def _employers(ws: Worksheet, parsed: ParsedList, last_row: int) -> None:
    columns = _columns(parsed)
    for col, (header, width, yours) in enumerate(columns, start=1):
        cell = ws.cell(1, col, header)
        cell.font = _font(11, True, "FFFFFFFF")
        cell.fill = PatternFill("solid", fgColor=GOLD if yours else NAVY)
        cell.alignment = _HEADER_ALIGN
        if width:
            ws.column_dimensions[cell.column_letter].width = width
    ws.row_dimensions[1].height = 31.5

    colours = {b: BUCKET_COLOURS[i % len(BUCKET_COLOURS)] for i, b in enumerate(parsed.buckets)}
    yours_fill = PatternFill("solid", fgColor=YOURS)
    for i, employer in enumerate(parsed.employers, start=1):
        row = i + 1
        values: dict[int, str | int | None] = {
            1: i,
            2: employer.name,
            3: employer.bucket,
            10: "Y" if employer.suggested else None,
            11: "Y" if employer.starred else None,
            12: employer.careers_url,
            16: "Not started",
        }
        for col, (_, _, yours) in enumerate(columns, start=1):
            cell = ws.cell(row, col, values.get(col))
            cell.font = _font(10, bold=col in (2, 11))
            cell.alignment = _WRAP_TOP
            cell.border = _THIN_BOTTOM
            if yours:
                cell.fill = yours_fill
            if col == 17:
                cell.number_format = DATE_FORMAT
            if col == 10 and employer.suggested:
                cell.font = _font(10, True, SUGGESTED_RED)
        ws.cell(row, 3).fill = PatternFill("solid", fgColor=colours[employer.bucket])

    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:S{max(2, len(parsed.employers) + 1)}"

    status = DataValidation(type="list", formula1='"' + ",".join(STATUSES) + '"',
                            allow_blank=True)
    status.add(f"P2:P{last_row}")
    star = DataValidation(type="list", formula1='"Y"', allow_blank=True)
    star.add(f"K2:K{last_row}")
    ws.add_data_validation(status)
    ws.add_data_validation(star)
    if parsed.settings.cv_versions:
        cv = DataValidation(
            type="list", formula1='"' + ",".join(parsed.settings.cv_versions) + '"',
            allow_blank=True,
        )
        cv.add(f"G2:G{last_row}")
        ws.add_data_validation(cv)


def _summary(ws: Worksheet, parsed: ParsedList, last_row: int) -> None:
    headers = ("Bucket", "Companies", "Suggested stars", "My stars", "Contact found or later",
               "Approached", "Applied", "Interviews")
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(1, col, header)
        cell.font = _font(11, True, "FFFFFFFF")
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.alignment = Alignment(wrap_text=True, vertical="bottom")
    ws.row_dimensions[1].height = 30
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 14

    rng = f"Employers!$C$2:$C${last_row}"

    def column_range(letter: str) -> str:
        return f"Employers!${letter}$2:${letter}${last_row}"

    buckets = parsed.buckets
    for i, bucket in enumerate(buckets, start=2):
        a = f"A{i}"
        formulas = [
            bucket,
            f"=COUNTIF({rng},{a})",
            f'=COUNTIFS({rng},{a},{column_range("J")},"Y")',
            f'=COUNTIFS({rng},{a},{column_range("K")},"Y")',
            f'=COUNTIFS({rng},{a},{column_range("P")},"Contact found")+F{i}+G{i}+H{i}',
            f'=COUNTIFS({rng},{a},{column_range("P")},"Approached")',
            f'=COUNTIFS({rng},{a},{column_range("P")},"Applied")+H{i}',
            f'=COUNTIFS({rng},{a},{column_range("P")},"Interview")',
        ]
        for c, value in enumerate(formulas, start=1):
            ws.cell(i, c, value).font = _font(10)

    total = len(buckets) + 2
    ws.cell(total, 1, "Total").font = _font(11, True)
    for c in range(2, 9):
        letter = get_column_letter(c)
        ws.cell(total, c, f"=SUM({letter}2:{letter}{total - 1})").font = _font(11, True)
    ws.cell(total + 2, 1,
            "Note: 'Applied' counts Applied plus Interview. 'Contact found or later' counts "
            "Contact found, Approached, Applied and Interview. My stars should total 20 by "
            "the end of Day 4.").font = _font(10)


def build_workbook(parsed: ParsedList) -> bytes:
    """Return the .xlsx file for *parsed* as bytes."""
    wb = Workbook()
    how = wb.active
    assert how is not None
    how.title = "How to use"
    _how_to_use(how, parsed)
    last_row = max(len(parsed.employers) + 1, MIN_TABLE_ROWS)
    _employers(wb.create_sheet("Employers"), parsed, last_row)
    _summary(wb.create_sheet("Summary"), parsed, last_row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
