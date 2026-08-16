"""Endpoint tests for the cv_feedback_provider FastAPI service."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import anthropic
import pytest
from fastapi.testclient import TestClient

from jobassist.Microservices.cv_feedback_provider.api import app, get_anthropic


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


_POSTING = {
    "company": "Acme",
    "role": "Software Engineer",
    "location": "London, UK",
    "url": "https://example.com/acme",
    "source": "greenhouse",
    "description": "Build things.",
}


def test_health(client: TestClient) -> None:
    assert client.get("/health").json()["service"] == "cv_feedback_provider"


def test_draft_returns_cover_letter_and_bullets(client: TestClient) -> None:
    combined = '{"cover_letter": "Dear Acme,", "bullets": ["Built X", "Led Y"]}'
    app.dependency_overrides[get_anthropic] = lambda: _mock_anthropic(combined)
    resp = client.post("/draft", json={"posting": _POSTING, "resume": "My resume."})
    assert resp.status_code == 200
    body = resp.json()
    assert body["cover_letter"] == "Dear Acme,"
    assert body["bullets"] == ["Built X", "Led Y"]


def test_draft_503_without_anthropic(client: TestClient) -> None:
    app.dependency_overrides[get_anthropic] = lambda: None
    resp = client.post("/draft", json={"posting": _POSTING, "resume": "My resume."})
    assert resp.status_code == 503
