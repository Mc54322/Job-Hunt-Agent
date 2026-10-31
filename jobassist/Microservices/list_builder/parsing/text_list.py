"""Read an employer list written as plain text.

Format (forgiving, meant to be typed by hand)::

    # Lines starting with # are notes and are ignored. Blank lines are ignored.
    University: Leeds                  <- optional settings
    CV versions: Data, Software

    London tech:                       <- a line ending with ":" starts a bucket
    Google
    Monzo, Y                           <- Y (or yes, *, star) marks "My star"
    Ocado Technology *
    Wise, https://wise.jobs            <- a link fills "Careers page link"
    Kainos, suggested                  <- fills "Suggested star" (e.g. a mentor's pick)

    Bank of England, Government, Y     <- or give the bucket on the line itself

Fields on a line may be separated by commas, tabs (pasting from a spreadsheet) or "|".
List bullets ("- ", "• ", "1. ") are ignored.
"""

from __future__ import annotations

import re

from jobassist.Microservices.list_builder.models import EmployerEntry, ListSettings, ParsedList

DEFAULT_BUCKET = "Other"
_STAR_WORDS = {"y", "yes", "*", "star", "starred", "my star"}
_NOT_STAR_WORDS = {"n", "no", "-"}
_SUGGESTED_WORDS = {"suggested", "suggested star", "s"}
_SEPARATORS = re.compile(r"\s*[,\t|]\s*")
_BULLET = re.compile(r"^(?:[-•–]\s+|\*\s+|\d+[.)]\s+)")
_SETTING = re.compile(r"^(university|cv versions?)\s*:\s*(.+)$", re.I)


def _key(name: str) -> str:
    return " ".join(name.lower().split())


def _is_link(text: str) -> bool:
    return text.lower().startswith(("http://", "https://", "www."))


def parse_text_list(text: str) -> ParsedList:
    """Parse *text* into employers, settings and plain-English warnings."""
    settings = ListSettings()
    employers: list[EmployerEntry] = []
    warnings: list[str] = []
    seen: dict[str, int] = {}
    no_bucket: list[str] = []
    bucket: str | None = None

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip().lstrip("﻿")
        if not line or line.startswith("#"):
            continue

        setting = _SETTING.match(line)
        if setting:
            key, value = setting.group(1).lower(), setting.group(2).strip()
            if key == "university":
                settings.university = value
            else:
                settings.cv_versions = [v for v in _SEPARATORS.split(value) if v]
            continue

        if line.endswith(":") and not _SEPARATORS.search(line[:-1]):
            bucket = line[:-1].strip() or None
            continue

        line = _BULLET.sub("", line)
        fields = [f for f in _SEPARATORS.split(line) if f]
        if not fields:
            continue
        name, starred, suggested = fields[0], False, False
        if name.endswith("*"):
            name, starred = name.rstrip("* ").strip(), True
        if not name:
            continue

        line_bucket: str | None = None
        careers_url: str | None = None
        for field in fields[1:]:
            lowered = field.lower()
            if lowered in _STAR_WORDS:
                starred = True
            elif lowered in _SUGGESTED_WORDS:
                suggested = True
            elif lowered in _NOT_STAR_WORDS:
                continue
            elif _is_link(field):
                careers_url = field if lowered.startswith("http") else f"https://{field}"
            elif line_bucket is None:
                line_bucket = field
            else:
                warnings.append(f"Line {number}: ignored extra text \"{field}\" after {name}.")

        key = _key(name)
        if key in seen:
            warnings.append(
                f"Line {number}: {name} is already on line {seen[key]} — kept the first one."
            )
            continue
        seen[key] = number

        chosen = line_bucket or bucket
        if chosen is None:
            no_bucket.append(name)
            chosen = DEFAULT_BUCKET
        employers.append(
            EmployerEntry(
                name=name,
                bucket=chosen,
                starred=starred,
                suggested=suggested,
                careers_url=careers_url,
                line=number,
            )
        )

    if no_bucket:
        shown = ", ".join(no_bucket[:5]) + ("…" if len(no_bucket) > 5 else "")
        warnings.append(
            f"{len(no_bucket)} compan{'y has' if len(no_bucket) == 1 else 'ies have'} no group, "
            f"so {'it was' if len(no_bucket) == 1 else 'they were'} put in "
            f"\"{DEFAULT_BUCKET}\": {shown}"
        )
    if not employers:
        warnings.append("No companies found. Put one company per line.")
    return ParsedList(employers=employers, settings=settings, warnings=warnings)


SAMPLE_TEXT = """\
# JobAssist employer list — one company per line.
# A line ending with ":" starts a group (bucket). Put Y or * after a company to star it.
# Optional: a careers page link after the company name. Lines starting with # are ignored.

University: Leeds

London tech:
Google
Monzo, Y
Ocado Technology *

Government and public sector:
Bank of England, Y
Office for National Statistics, https://careers.ons.gov.uk

# You can also give the group on the same line:
Accenture, Consulting
"""
