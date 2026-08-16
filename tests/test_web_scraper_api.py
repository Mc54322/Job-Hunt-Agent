"""Endpoint tests for the web_scraper FastAPI service."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import anthropic
import pytest
from fastapi.testclient import TestClient

from jobassist.Microservices.web_scraper import api
from jobassist.Microservices.web_scraper.api import app, get_anthropic


@pytest.fixture
def client() -> Iterator[TestClient]:
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


def test_health(client: TestClient) -> None:
    assert client.get("/health").json()["service"] == "web_scraper"


def test_indices_lists_known(client: TestClient) -> None:
    body = client.get("/indices").json()
    assert isinstance(body["indices"], list)
    assert len(body["indices"]) > 0


def test_companies_unknown_index_404(client: TestClient) -> None:
    assert client.get("/companies/not-a-real-index").status_code == 404


def test_aliases_returns_llm_terms(client: TestClient) -> None:
    app.dependency_overrides[get_anthropic] = lambda: _mock_anthropic(
        '["Junior Engineer", "Software Developer"]'
    )
    resp = client.post("/aliases", json={"role": "Software Engineer", "job_type": "full-time"})
    assert resp.status_code == 200
    assert resp.json()["aliases"] == ["Junior Engineer", "Software Developer"]


def test_aliases_503_without_anthropic(client: TestClient) -> None:
    app.dependency_overrides[get_anthropic] = lambda: None
    resp = client.post("/aliases", json={"role": "Engineer", "job_type": "full-time"})
    assert resp.status_code == 503


def test_search_empty_when_no_sources(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    monkeypatch.delenv("REED_API_KEY", raising=False)
    payload = {
        "query": {"role": "Engineer", "job_type": "full-time", "companies": []},
        "expand_aliases": False,
    }
    resp = client.post("/search", json=payload)
    assert resp.status_code == 200
    assert resp.json()["postings"] == []


def test_module_exposes_main() -> None:
    assert callable(api.main)
