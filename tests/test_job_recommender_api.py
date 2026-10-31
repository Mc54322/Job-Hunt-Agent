"""Endpoint tests for the job_recommender FastAPI service (incl. orchestration)."""

from __future__ import annotations

import base64
import io
import json
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import anthropic
import docx
import httpx
import openpyxl
import pytest
import respx
from fastapi.testclient import TestClient

from jobassist.Microservices.job_recommender.api import app, get_anthropic


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("JOBASSIST_DB", ":memory:")
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _mock_anthropic(text: str) -> anthropic.AsyncAnthropic:
    block = MagicMock(spec=anthropic.types.TextBlock)
    block.text = text
    response = MagicMock()
    response.content = [block]
    c = MagicMock(spec=anthropic.AsyncAnthropic)
    c.messages = MagicMock()
    c.messages.create = AsyncMock(return_value=response)
    return c  # type: ignore[return-value]


_POSTING = {
    "company": "Acme",
    "role": "Software Engineer",
    "location": "London, UK",
    "url": "https://example.com/acme",
    "source": "greenhouse",
    "description": "Build things.",
}
_SCORE = '{"score": 0.8, "rationale": "Strong match."}'


def test_health(client: TestClient) -> None:
    assert client.get("/health").json()["service"] == "job_recommender"


def test_cache_roundtrip(client: TestClient) -> None:
    assert client.post("/cache/set", json={"key": "k1", "value": "v1"}).json()["ok"] is True
    assert client.post("/cache/get", json={"key": "k1"}).json()["value"] == "v1"
    assert client.post("/cache/get", json={"key": "missing"}).json()["value"] is None


def test_postings_save_and_list(client: TestClient) -> None:
    assert client.post("/postings", json=_POSTING).json()["ok"] is True
    listed = client.get("/postings").json()["postings"]
    assert len(listed) == 1
    assert listed[0]["company"] == "Acme"


def test_score(client: TestClient) -> None:
    app.dependency_overrides[get_anthropic] = lambda: _mock_anthropic(_SCORE)
    resp = client.post("/score", json={"posting": _POSTING, "resume": "My resume."})
    assert resp.status_code == 200
    body = resp.json()
    assert body["score"] == 0.8
    assert body["posting"]["company"] == "Acme"


def test_report_renders_markdown(client: TestClient) -> None:
    scored = {"posting": _POSTING, "score": 0.8, "rationale": "Strong match."}
    query = {"role": "Software Engineer", "job_type": "full-time"}
    resp = client.post("/report", json={"results": [scored], "query": query})
    assert resp.status_code == 200
    assert "Acme" in resp.json()["markdown"]


def test_recommend_orchestrates_services(client: TestClient) -> None:
    app.dependency_overrides[get_anthropic] = lambda: _mock_anthropic(_SCORE)
    with respx.mock:
        respx.post("http://localhost:8001/search").mock(
            return_value=httpx.Response(200, json={"postings": [_POSTING]})
        )
        respx.post("http://localhost:8002/dedupe").mock(
            return_value=httpx.Response(200, json={"postings": [_POSTING]})
        )
        resp = client.post(
            "/recommend",
            json={
                "query": {"role": "Software Engineer", "job_type": "full-time"},
                "resume": "My resume.",
                "expand_aliases": False,
            },
        )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 1
    assert results[0]["score"] == 0.8
    assert results[0]["posting"]["company"] == "Acme"


def test_recommend_caps_total_scored_at_max_results(client: TestClient) -> None:
    llm = _mock_anthropic(_SCORE)
    app.dependency_overrides[get_anthropic] = lambda: llm
    postings = [
        {**_POSTING, "company": f"Co{i}", "url": f"https://example.com/{i}"} for i in range(8)
    ]
    with respx.mock:
        respx.post("http://localhost:8001/search").mock(
            return_value=httpx.Response(200, json={"postings": postings})
        )
        respx.post("http://localhost:8002/dedupe").mock(
            return_value=httpx.Response(200, json={"postings": postings})
        )
        resp = client.post(
            "/recommend",
            json={
                "query": {"role": "Software Engineer", "job_type": "full-time", "max_results": 3},
                "resume": "My resume.",
                "expand_aliases": False,
            },
        )
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 3
    assert llm.messages.create.call_count == 3  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Background runs (web UI)
# ---------------------------------------------------------------------------


def _wait_for_run(client: TestClient, run_id: str) -> dict:  # type: ignore[type-arg]
    for _ in range(200):
        body = client.get(f"/runs/{run_id}").json()
        if body["state"] != "running":
            return body  # type: ignore[no-any-return]
        time.sleep(0.02)
    raise AssertionError("run did not finish")


def test_run_completes_with_results_and_company_status(client: TestClient) -> None:
    app.dependency_overrides[get_anthropic] = lambda: _mock_anthropic(_SCORE)
    status = {"company": "Acme", "found": {"greenhouse": 1}, "notes": ["searched"],
              "cost_usd": 0.0}
    with respx.mock:
        search = respx.post("http://localhost:8001/search").mock(
            return_value=httpx.Response(200, json={"postings": [_POSTING], "companies": [status]})
        )
        respx.get(url__regex=r"http://localhost:8001/search/progress/.*").mock(
            return_value=httpx.Response(200, json={"total": 1, "done": 0, "current": ""})
        )
        respx.post("http://localhost:8002/dedupe").mock(
            return_value=httpx.Response(200, json={"postings": [_POSTING]})
        )
        started = client.post(
            "/runs",
            json={
                "query": {"role": "Software Engineer", "job_type": "full-time",
                          "companies": ["Acme"]},
                "resume": "My resume.",
                "expand_aliases": False,
                "refresh": True,
                "search_company_sites": True,
            },
        )
        assert started.status_code == 200
        body = _wait_for_run(client, started.json()["run_id"])

    assert body["state"] == "done", body
    assert body["results"][0]["score"] == 0.8
    assert body["companies"] == [status]
    sent = json.loads(search.calls[0].request.content)
    assert sent["refresh"] is True and sent["search_company_sites"] is True
    assert sent["run_id"] == started.json()["run_id"]


def test_run_failure_is_explained_in_plain_english(client: TestClient) -> None:
    app.dependency_overrides[get_anthropic] = lambda: _mock_anthropic(_SCORE)
    with respx.mock:
        respx.post("http://localhost:8001/search").mock(
            side_effect=httpx.ConnectError("refused")
        )
        started = client.post(
            "/runs",
            json={"query": {"role": "X", "job_type": "full-time"}, "resume": "r"},
        )
        body = _wait_for_run(client, started.json()["run_id"])
    assert body["state"] == "error"
    assert "background services" in body["error"]


def test_run_requires_anthropic_key(client: TestClient) -> None:
    app.dependency_overrides[get_anthropic] = lambda: None
    resp = client.post("/runs", json={"query": {"role": "X", "job_type": "y"}, "resume": "r"})
    assert resp.status_code == 503
    assert "ANTHROPIC_API_KEY" in resp.json()["detail"]


def test_unknown_run_404(client: TestClient) -> None:
    assert client.get("/runs/nope").status_code == 404


# ---------------------------------------------------------------------------
# File helpers (web UI)
# ---------------------------------------------------------------------------


def _upload(name: str, data: bytes) -> dict[str, str]:
    return {"filename": name, "content_base64": base64.b64encode(data).decode()}


def test_parse_employers_xlsx(client: TestClient, tmp_path: Path) -> None:
    wb = openpyxl.Workbook()
    sheet = wb.active
    assert sheet is not None
    sheet.append(["Company", "Bucket", "My star (Y)", "Careers page link"])
    sheet.append(["Monzo", "Finance", "Y", None])
    sheet.append(["Acme", "AI", None, "https://acme.example/careers"])
    path = tmp_path / "e.xlsx"
    wb.save(path)
    resp = client.post("/employers/parse", json=_upload("e.xlsx", path.read_bytes()))
    assert resp.status_code == 200
    body = resp.json()
    assert body["buckets"] == ["AI", "Finance"]
    assert body["employers"][0] == {
        "name": "Monzo", "careers_url": None, "bucket": "Finance", "starred": True
    }


def test_parse_employers_rejects_non_spreadsheet(client: TestClient) -> None:
    resp = client.post("/employers/parse", json=_upload("e.xlsx", b"not a spreadsheet"))
    assert resp.status_code == 400
    assert "Company" in resp.json()["detail"]


def test_parse_resume_text_and_docx(client: TestClient) -> None:
    assert client.post("/resume/parse", json=_upload("cv.txt", b"Jane Doe\nPython")).json() == {
        "text": "Jane Doe\nPython"
    }
    document = docx.Document()
    document.add_paragraph("Jane Doe")
    document.add_paragraph("Data analysis with SQL")
    buffer = io.BytesIO()
    document.save(buffer)
    text = client.post("/resume/parse", json=_upload("cv.docx", buffer.getvalue())).json()["text"]
    assert "Data analysis with SQL" in text


def test_parse_resume_rejects_unsupported_and_empty(client: TestClient) -> None:
    resp = client.post("/resume/parse", json=_upload("cv.pages", b"x"))
    assert resp.status_code == 400 and "unsupported" in resp.json()["detail"]
    resp = client.post("/resume/parse", json=_upload("cv.txt", b"   "))
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Saved jobs
# ---------------------------------------------------------------------------


def test_saved_lists_jobs_with_cached_scores_only(client: TestClient) -> None:
    llm = _mock_anthropic(_SCORE)
    app.dependency_overrides[get_anthropic] = lambda: llm
    other = {**_POSTING, "company": "Beta", "url": "https://example.com/beta"}
    client.post("/postings", json=_POSTING)
    client.post("/postings", json=other)
    # Score only Acme against this CV (fills the score cache).
    client.post("/score", json={"posting": _POSTING, "resume": "My resume."})
    calls_before = llm.messages.create.call_count  # type: ignore[attr-defined]

    jobs = client.post("/saved", json={"resume": "My resume."}).json()["jobs"]

    by_company = {j["posting"]["company"]: j for j in jobs}
    assert set(by_company) == {"Acme", "Beta"}
    assert by_company["Acme"]["score"] == 0.8
    assert by_company["Acme"]["rationale"] == "Strong match."
    assert by_company["Beta"]["score"] is None
    assert by_company["Acme"]["first_seen"]
    # Viewing saved jobs never calls Claude.
    assert llm.messages.create.call_count == calls_before  # type: ignore[attr-defined]


def test_saved_without_resume_or_with_other_cv_has_no_scores(client: TestClient) -> None:
    app.dependency_overrides[get_anthropic] = lambda: _mock_anthropic(_SCORE)
    client.post("/postings", json=_POSTING)
    client.post("/score", json={"posting": _POSTING, "resume": "My resume."})
    assert client.post("/saved", json={}).json()["jobs"][0]["score"] is None
    other_cv = client.post("/saved", json={"resume": "A different CV."}).json()
    assert other_cv["jobs"][0]["score"] is None


def test_saved_scores_survive_cv_formatting_differences(client: TestClient) -> None:
    app.dependency_overrides[get_anthropic] = lambda: _mock_anthropic(_SCORE)
    client.post("/postings", json=_POSTING)
    # Scored from a .txt file with trailing blank lines (as the CLI reads it)...
    client.post("/score", json={"posting": _POSTING, "resume": "Jane Doe\nPython  SQL\n\n"})
    # ...found again from an uploaded copy whose whitespace was trimmed/reflowed.
    jobs = client.post("/saved", json={"resume": "Jane Doe Python\nSQL"}).json()["jobs"]
    assert jobs[0]["score"] == 0.8


@pytest.mark.asyncio
async def test_scorer_reads_scores_saved_under_legacy_exact_text_key() -> None:
    import hashlib

    from jobassist.Microservices.job_recommender.cache_client import cache_key
    from jobassist.Microservices.job_recommender.models import JobPosting
    from jobassist.Microservices.job_recommender.scoring.scorer import ScoringPipeline

    class _Cache:
        def __init__(self) -> None:
            self.data: dict[str, str] = {}

        async def get_cached(self, key: str) -> str | None:
            return self.data.get(key)

        async def set_cached(self, key: str, value: str) -> None:
            self.data[key] = value

    posting = JobPosting.model_validate(_POSTING)
    resume = "My resume.\n\n"
    cache = _Cache()
    legacy = hashlib.sha256(resume.encode()).hexdigest()
    cache.data[cache_key(legacy, posting.hash)] = _SCORE
    llm = _mock_anthropic(_SCORE)
    scored = await ScoringPipeline(llm, resume, cache).cached_score(posting)
    assert scored is not None and scored.score == 0.8
