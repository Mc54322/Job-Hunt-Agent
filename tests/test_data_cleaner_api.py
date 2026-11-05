"""Endpoint tests for the data_cleaner FastAPI service."""

from __future__ import annotations

from fastapi.testclient import TestClient

from jobassist.Microservices.data_cleaner.api import app

client = TestClient(app)


def _posting(company: str = "Acme", source: str = "greenhouse", **kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "company": company,
        "role": "Software Engineer",
        "location": "London, UK",
        "url": f"https://example.com/{company.lower()}",
        "source": source,
    }
    base.update(kw)
    return base


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "data_cleaner"


def test_dedupe_collapses_same_identity_preferring_ats() -> None:
    payload = {"postings": [_posting(source="adzuna"), _posting(source="greenhouse")]}
    resp = client.post("/dedupe", json=payload)
    assert resp.status_code == 200
    postings = resp.json()["postings"]
    assert len(postings) == 1
    assert postings[0]["source"] == "greenhouse"  # ATS-direct wins


def test_dedupe_keeps_distinct_postings() -> None:
    payload = {"postings": [_posting(company="Acme"), _posting(company="Beta")]}
    resp = client.post("/dedupe", json=payload)
    assert len(resp.json()["postings"]) == 2


def test_salary_normalises_range() -> None:
    resp = client.post("/salary", json={"raw": "£60,000 - £80,000"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["low"] == 60000
    assert body["high"] == 80000
    assert body["midpoint"] == 70000


def test_salary_returns_null_for_unparseable() -> None:
    resp = client.post("/salary", json={"raw": "competitive"})
    assert resp.status_code == 200
    assert resp.json() is None


def test_volume_returns_estimate() -> None:
    resp = client.post("/volume", json={"posting": _posting()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["label"] in {"low", "medium", "high"}
    assert body["seniority"] in {"junior", "mid", "senior"}
    assert isinstance(body["estimate"], int)
