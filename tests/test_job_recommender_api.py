"""Endpoint tests for the job_recommender FastAPI service (incl. orchestration)."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
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
