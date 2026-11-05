"""Tests for the list_builder service: text-list parsing, the workbook layout, the API,
the command line, and that JobAssist reads the result back."""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import httpx
import openpyxl
import pytest
import respx
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from jobassist.Microservices.frontend.api import app as frontend_app
from jobassist.Microservices.job_recommender.orchestration.employers_file import load_employers
from jobassist.Microservices.list_builder.api import XLSX_MEDIA_TYPE, app
from jobassist.Microservices.list_builder.cli import app as cli_app
from jobassist.Microservices.list_builder.parsing.text_list import (
    SAMPLE_TEXT,
    parse_text_list,
)
from jobassist.Microservices.list_builder.workbook.builder import (
    BUCKET_COLOURS,
    MIN_TABLE_ROWS,
    build_workbook,
)

_LIST = """\
# my companies
University: Leeds
CV versions: Data, Software

London tech:
Google
Monzo, Y
- Ocado Technology *
Wise, https://wise.jobs, yes

Government and public sector:
Bank of England, Y
Kainos, suggested
Accenture, Consulting
"""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parse_groups_stars_links_and_settings() -> None:
    parsed = parse_text_list(_LIST)
    rows = [(e.name, e.bucket, e.starred) for e in parsed.employers]
    assert rows == [
        ("Google", "London tech", False),
        ("Monzo", "London tech", True),
        ("Ocado Technology", "London tech", True),
        ("Wise", "London tech", True),
        ("Bank of England", "Government and public sector", True),
        ("Kainos", "Government and public sector", False),
        ("Accenture", "Consulting", False),
    ]
    assert parsed.employers[3].careers_url == "https://wise.jobs"
    assert parsed.employers[5].suggested
    assert parsed.settings.university == "Leeds"
    assert parsed.settings.cv_versions == ["Data", "Software"]
    assert parsed.buckets == ["London tech", "Government and public sector", "Consulting"]
    assert parsed.warnings == []


def test_parse_tab_separated_paste_from_spreadsheet() -> None:
    parsed = parse_text_list("Monzo\tLondon finance\tY\nWise\tLondon finance\n")
    assert [(e.name, e.bucket, e.starred) for e in parsed.employers] == [
        ("Monzo", "London finance", True),
        ("Wise", "London finance", False),
    ]


def test_parse_warns_about_duplicates_missing_groups_and_extra_text() -> None:
    parsed = parse_text_list("Google\nMonzo, Finance, extra bit\ngoogle\n")
    assert [e.name for e in parsed.employers] == ["Google", "Monzo"]
    assert parsed.employers[0].bucket == "Other"
    joined = " ".join(parsed.warnings)
    assert "already on line 1" in joined
    assert 'ignored extra text "extra bit"' in joined
    assert '1 company has no group' in joined and "Google" in joined


def test_parse_empty_list_warns() -> None:
    assert parse_text_list("# nothing here\n\n").warnings == [
        "No companies found. Put one company per line."
    ]


def test_sample_text_parses_cleanly() -> None:
    parsed = parse_text_list(SAMPLE_TEXT)
    assert len(parsed.employers) == 6 and parsed.warnings == []


# ---------------------------------------------------------------------------
# Workbook
# ---------------------------------------------------------------------------


def _workbook(text: str = _LIST) -> openpyxl.Workbook:
    return openpyxl.load_workbook(io.BytesIO(build_workbook(parse_text_list(text))))


def test_workbook_sheets_and_employer_table() -> None:
    wb = _workbook()
    assert wb.sheetnames == ["How to use", "Employers", "Summary"]
    ws = wb["Employers"]
    headers = [ws.cell(1, c).value for c in range(1, 20)]
    assert headers[:3] == ["#", "Company", "Bucket"]
    assert headers[10:12] == ["My star (Y)", "Careers page link"]
    assert headers[14] == "Leeds alumni"
    assert ws["A1"].fill.fgColor.rgb == "FF1F3864" and ws["K1"].fill.fgColor.rgb == "FF7F6000"
    assert [ws.cell(r, 2).value for r in range(2, 9)][:3] == ["Google", "Monzo", "Ocado Technology"]
    assert ws["K3"].value == "Y" and ws["K2"].value is None
    assert ws["L5"].value == "https://wise.jobs"
    assert ws["J7"].value == "Y" and ws["J7"].font.color.rgb == "FFC00000"
    assert ws["P2"].value == "Not started"
    assert ws["K2"].fill.fgColor.rgb == "FFFFF2CC"
    assert ws["C2"].fill.fgColor.rgb == BUCKET_COLOURS[0]
    assert ws["C6"].fill.fgColor.rgb == BUCKET_COLOURS[1]
    assert ws.freeze_panes == "C2" and ws.auto_filter.ref == "A1:S8"
    validations = {dv.formula1: str(dv.sqref) for dv in ws.data_validations.dataValidation}
    assert validations['"Y"'] == f"K2:K{MIN_TABLE_ROWS}"
    assert validations['"Data,Software"'] == f"G2:G{MIN_TABLE_ROWS}"
    assert any(f.startswith('"Not started,') for f in validations)


def test_workbook_summary_formulas_per_bucket() -> None:
    ws = _workbook()["Summary"]
    assert [ws.cell(r, 1).value for r in range(2, 6)] == [
        "London tech", "Government and public sector", "Consulting", "Total"
    ]
    rng = f"Employers!$C$2:$C${MIN_TABLE_ROWS}"
    assert ws["B2"].value == f"=COUNTIF({rng},A2)"
    assert ws["D3"].value == f'=COUNTIFS({rng},A3,Employers!$K$2:$K${MIN_TABLE_ROWS},"Y")'
    assert ws["B5"].value == "=SUM(B2:B4)"


def test_workbook_without_university_uses_generic_alumni_column() -> None:
    wb = _workbook("Google\n")
    assert wb["Employers"]["O1"].value == "Alumni contacts"
    assert "your university" in wb["How to use"]["B11"].value


def test_jobassist_reads_the_built_workbook(tmp_path: Path) -> None:
    path = tmp_path / "list.xlsx"
    path.write_bytes(build_workbook(parse_text_list(_LIST)))
    employers = load_employers(path)
    assert [e.name for e in employers][:2] == ["Google", "Monzo"]
    assert sum(e.starred for e in employers) == 4
    assert employers[3].careers_url == "https://wise.jobs"
    assert [e.name for e in load_employers(path, starred_only=True)] == [
        "Monzo", "Ocado Technology", "Wise", "Bank of England"
    ]


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def test_preview_and_university_override(client: TestClient) -> None:
    body = client.post("/preview", json={"text": _LIST, "university": "York"}).json()
    assert body["starred"] == 4 and body["university"] == "York"
    assert body["buckets"][0] == "London tech"


def test_build_returns_xlsx_download(client: TestClient) -> None:
    resp = client.post("/build", json={"text": _LIST, "filename": "My list!.xlsx"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == XLSX_MEDIA_TYPE
    assert resp.headers["content-disposition"] == 'attachment; filename="My list.xlsx"'
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert wb["Employers"]["B2"].value == "Google"


def test_build_empty_list_is_400(client: TestClient) -> None:
    resp = client.post("/build", json={"text": "# nothing"})
    assert resp.status_code == 400 and "one company per line" in resp.json()["detail"]


def test_template(client: TestClient) -> None:
    assert "London tech:" in client.get("/template").json()["text"]


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def test_cli_builds_workbook_next_to_text_file(tmp_path: Path) -> None:
    source = tmp_path / "companies.txt"
    source.write_text(_LIST)
    result = CliRunner().invoke(cli_app, [str(source), "--university", "Bath"])
    assert result.exit_code == 0, result.output
    assert "7 employers in 3 groups, 4 starred" in result.output
    wb = openpyxl.load_workbook(tmp_path / "companies.xlsx")
    assert wb["Employers"]["O1"].value == "Bath alumni"


def test_cli_example_and_missing_file(tmp_path: Path) -> None:
    assert "London tech:" in CliRunner().invoke(cli_app, ["--example"]).output
    result = CliRunner().invoke(cli_app, [str(tmp_path / "missing.txt")])
    assert result.exit_code == 1 and "--example" in result.output


# ---------------------------------------------------------------------------
# Web page forwarding
# ---------------------------------------------------------------------------


def test_frontend_forwards_list_calls_with_download_name() -> None:
    with TestClient(frontend_app) as web, respx.mock:
        respx.post("http://localhost:8005/build").mock(
            return_value=httpx.Response(
                200,
                content=b"xlsx-bytes",
                headers={"content-type": XLSX_MEDIA_TYPE,
                         "content-disposition": 'attachment; filename="L.xlsx"'},
            )
        )
        resp = web.post("/api/lists/build", json={"text": "Google"})
        assert resp.content == b"xlsx-bytes"
        assert resp.headers["content-disposition"] == 'attachment; filename="L.xlsx"'
        assert web.post("/api/lists/other", json={}).status_code == 404
