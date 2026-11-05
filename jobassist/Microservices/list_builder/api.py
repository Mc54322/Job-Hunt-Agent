"""FastAPI app for the list_builder service.

Turns a plain-text list of employers (names, buckets, stars) into the JobAssist
employer-tracking workbook. Stateless, no LLM calls.
Run standalone: `uvicorn jobassist.Microservices.list_builder.api:app --port 8005`.
"""

from __future__ import annotations

import os
import re

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

from jobassist.Microservices.list_builder.models import EmployerEntry, ParsedList
from jobassist.Microservices.list_builder.parsing.text_list import SAMPLE_TEXT, parse_text_list
from jobassist.Microservices.list_builder.workbook.builder import build_workbook

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_MAX_TEXT_CHARS = 500_000

app = FastAPI(title="JobAssist — List Builder", version="0.1.0")


class ListRequest(BaseModel):
    text: str = Field(..., max_length=_MAX_TEXT_CHARS)
    university: str | None = None  # overrides a "University:" line in the text
    filename: str | None = None  # name for the downloaded file


class PreviewResponse(BaseModel):
    employers: list[EmployerEntry]
    buckets: list[str]
    starred: int
    university: str | None
    warnings: list[str]


def _parse(req: ListRequest) -> ParsedList:
    parsed = parse_text_list(req.text)
    if req.university and req.university.strip():
        parsed.settings.university = req.university.strip()
    return parsed


def _safe_filename(name: str | None) -> str:
    stem = re.sub(r"[^\w\- ]+", "", (name or "").removesuffix(".xlsx")).strip()
    return f"{stem or 'Employer list'}.xlsx"


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "list_builder"}


@app.get("/template", response_model=dict[str, str])
async def template() -> dict[str, str]:
    """An example text list showing the format."""
    return {"text": SAMPLE_TEXT}


@app.post("/preview", response_model=PreviewResponse)
async def preview(req: ListRequest) -> PreviewResponse:
    """What the workbook would contain, without building it."""
    parsed = _parse(req)
    return PreviewResponse(
        employers=parsed.employers,
        buckets=parsed.buckets,
        starred=sum(e.starred for e in parsed.employers),
        university=parsed.settings.university,
        warnings=parsed.warnings,
    )


@app.post("/build")
async def build(req: ListRequest) -> Response:
    """Return the employer-tracking workbook (.xlsx) for the text list."""
    parsed = _parse(req)
    if not parsed.employers:
        raise HTTPException(status_code=400, detail="No companies found. Put one company per line.")
    filename = _safe_filename(req.filename)
    return Response(
        content=build_workbook(parsed),
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8005")))
