"""Tests for the frontend service: page served, API proxy allow-list, service health."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from jobassist.Microservices.frontend.api import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def test_index_page_served(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "<title>JobAssist</title>" in resp.text
    assert resp.headers["content-type"].startswith("text/html")


def test_proxy_forwards_allowed_calls(client: TestClient) -> None:
    with respx.mock:
        route = respx.post("http://localhost:8003/runs").mock(
            return_value=httpx.Response(200, json={"run_id": "abc"})
        )
        resp = client.post("/api/runs", json={"query": {"role": "x", "job_type": "y"}})
    assert resp.json() == {"run_id": "abc"}
    assert b'"role"' in route.calls[0].request.content


def test_proxy_passes_through_errors(client: TestClient) -> None:
    with respx.mock:
        respx.get("http://localhost:8003/runs/zzz").mock(
            return_value=httpx.Response(404, json={"detail": "unknown run"})
        )
        resp = client.get("/api/runs/zzz")
    assert resp.status_code == 404 and resp.json()["detail"] == "unknown run"


def test_proxy_blocks_unlisted_paths(client: TestClient) -> None:
    with respx.mock:  # any upstream call would fail the test as unmocked
        assert client.post("/api/cache/set", json={"key": "k", "value": "v"}).status_code == 404
        assert client.get("/api/postings").status_code == 404


def test_proxy_explains_when_services_down(client: TestClient) -> None:
    with respx.mock:
        respx.post("http://localhost:8003/runs").mock(side_effect=httpx.ConnectError("refused"))
        resp = client.post("/api/runs", json={})
    assert resp.status_code == 503
    assert "start it again" in resp.json()["detail"]


def test_services_health_reports_each_service(client: TestClient) -> None:
    with respx.mock:
        respx.get("http://localhost:8003/health").mock(return_value=httpx.Response(200))
        respx.get("http://localhost:8001/health").mock(return_value=httpx.Response(200))
        respx.get("http://localhost:8002/health").mock(side_effect=httpx.ConnectError("x"))
        respx.get("http://localhost:8005/health").mock(return_value=httpx.Response(200))
        body = client.get("/api/health").json()
    assert body == {
        "ok": False,
        "services": {"job_recommender": True, "web_scraper": True, "data_cleaner": False,
                     "list_builder": True},
    }


def test_proxy_allows_saved_jobs(client: TestClient) -> None:
    with respx.mock:
        respx.post("http://localhost:8003/saved").mock(
            return_value=httpx.Response(200, json={"jobs": []})
        )
        assert client.post("/api/saved", json={}).json() == {"jobs": []}
