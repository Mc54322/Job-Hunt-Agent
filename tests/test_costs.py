"""Tests for spending control: the cost meter, run and per-employer limits, running out
of credit, the Stop button, page trimming, and partial results. Claude and HTTP mocked."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from jobassist.Microservices.job_recommender.api import app as recommender_app
from jobassist.Microservices.job_recommender.api import get_anthropic as recommender_llm
from jobassist.Microservices.web_scraper import api as scraper_api
from jobassist.Microservices.web_scraper.costs.meter import (
    BudgetStop,
    CallFailed,
    CostMeter,
    EmployerLimit,
    metered_create,
    usage_cost,
)
from jobassist.Microservices.web_scraper.models.schemas import JobQuery
from jobassist.Microservices.web_scraper.orchestration.employer_search import (
    EmployerSearch,
    SearchProgress,
    SearchSettings,
)
from jobassist.Microservices.web_scraper.sources.company_pages.company_site import (
    PageContent,
    focus_for_roles,
)


def _usage(inp: int = 0, out: int = 0, searches: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=inp,
        output_tokens=out,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        server_tool_use=SimpleNamespace(web_search_requests=searches) if searches else None,
    )


def _reply(text: str, usage: SimpleNamespace | None = None) -> MagicMock:
    block = MagicMock(spec=anthropic.types.TextBlock)
    block.text = text
    response = MagicMock()
    response.content = [block]
    response.stop_reason = "end_turn"
    response.usage = usage or _usage(1000, 100)
    return response


def _llm(*replies: Any) -> anthropic.AsyncAnthropic:
    client = MagicMock(spec=anthropic.AsyncAnthropic)
    client.messages = MagicMock()
    client.messages.create = AsyncMock(side_effect=list(replies))
    return client  # type: ignore[return-value]


def _api_error(cls: type[anthropic.APIStatusError], status: int, message: str) -> Exception:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(message, response=httpx.Response(status, request=request), body=None)


class MemoryCache:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get_cached(self, key: str) -> str | None:
        return self.data.get(key)

    async def set_cached(self, key: str, value: str) -> None:
        self.data[key] = value


# ---------------------------------------------------------------------------
# Meter
# ---------------------------------------------------------------------------


def test_usage_cost_prices_tokens_and_searches() -> None:
    usd, searches = usage_cost(_usage(1_000_000, 100_000, searches=2))
    assert searches == 2
    assert usd == pytest.approx(3.00 + 1.50 + 0.02)


def test_meter_run_limit_stops_with_reason() -> None:
    meter = CostMeter(budget_usd=0.01)
    meter.check("Acme", "reading website")
    meter.record("Acme", "reading website", _usage(5000, 0))  # $0.015
    with pytest.raises(BudgetStop) as stop:
        meter.check("Beta", "reading website")
    assert "limit of $0.01 reached" in stop.value.reason
    # Once stopped, every later call is refused with the same reason.
    with pytest.raises(BudgetStop):
        meter.check("", "similar job titles")


def test_meter_employer_limit_skips_only_that_employer() -> None:
    meter = CostMeter(budget_usd=5.0, company_budget_usd=0.05)
    meter.record("Acme", "finding careers page", _usage(10_000, 0))  # $0.03
    with pytest.raises(EmployerLimit, match=r"\$0.05 limit"):
        meter.check("Acme", "reading website", estimate=0.03)
    meter.check("Beta", "reading website", estimate=0.03)  # other employers unaffected
    assert meter.stopped is None


def test_meter_cancel_and_breakdown() -> None:
    meter = CostMeter()
    meter.record("Acme", "scoring", _usage(1000, 100))
    meter.record("Acme", "scoring", _usage(1000, 100))
    meter.cancel()
    with pytest.raises(BudgetStop, match="Stopped by you"):
        meter.check("Acme", "scoring")
    (line,) = meter.lines()
    assert (line.company, line.step, line.calls) == ("Acme", "scoring", 2)
    assert meter.company_spent("Acme") == pytest.approx(line.usd, abs=1e-4)


@pytest.mark.asyncio
async def test_metered_create_records_cost() -> None:
    meter = CostMeter()
    llm = _llm(_reply("ok", _usage(2000, 200)))
    await metered_create(llm, meter, "Acme", "reading website", model="m", max_tokens=1,
                         messages=[])
    assert meter.spent_usd == pytest.approx(0.009)


@pytest.mark.asyncio
async def test_metered_create_out_of_credit_stops_run() -> None:
    meter = CostMeter()
    err = _api_error(anthropic.BadRequestError, 400,
                     "Your credit balance is too low to access the Anthropic API.")
    with pytest.raises(BudgetStop, match="credit ran out"):
        await metered_create(_llm(err), meter, "Acme", "reading website", model="m",
                             max_tokens=1, messages=[])
    assert meter.stopped is not None and "credit" in meter.stopped


@pytest.mark.asyncio
async def test_metered_create_other_errors_fail_one_call_only() -> None:
    meter = CostMeter()
    err = _api_error(anthropic.InternalServerError, 500, "overloaded")
    with pytest.raises(CallFailed):
        await metered_create(_llm(err), meter, "Acme", "reading website", model="m",
                             max_tokens=1, messages=[])
    assert meter.stopped is None


# ---------------------------------------------------------------------------
# Page trimming
# ---------------------------------------------------------------------------


def test_focus_skips_pages_without_the_role() -> None:
    content = PageContent("Welcome to Acme. Office Manager, Chef.", {"https://a/1": "Chef"})
    assert focus_for_roles(content, ["Data Analyst"]) is None


def test_focus_trims_long_pages_to_matching_parts() -> None:
    filler = "\n".join(f"About our culture paragraph {i}" for i in range(2000))
    text = filler + "\nData Analyst — London\nApply now\n" + filler
    links = {"https://a/jobs/1": "Data Analyst", "https://a/about": "About us",
             "https://a/jobs/2": "Chef"}
    focused = focus_for_roles(PageContent(text, links), ["data analyst"])
    assert focused is not None
    assert len(focused) < 20_000 and "Data Analyst — London" in focused
    assert "Data Analyst -> https://a/jobs/1" in focused
    assert "https://a/about" not in focused  # not a title match nor a job-looking link


# ---------------------------------------------------------------------------
# Employer search with limits
# ---------------------------------------------------------------------------


_PAGE = "<html><body>" + "".join(
    f'<p><a href="/jobs/{i}">Data Analyst {i}</a> London</p>' for i in range(10)
) + "<p>" + "We hire. " * 60 + "</p></body></html>"


def _routes() -> None:
    respx.get("https://acme.example/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://acme.example/careers").mock(return_value=httpx.Response(200, text=_PAGE))
    respx.get("https://boards-api.greenhouse.io/v1/boards/monzo/jobs").mock(
        return_value=httpx.Response(200, json={"jobs": [{
            "title": "Data Analyst", "location": {"name": "London"},
            "absolute_url": "https://job-boards.greenhouse.io/monzo/jobs/1",
            "updated_at": "2026-10-01T00:00:00Z"}]})
    )


_QUERY = JobQuery(
    role="Data Analyst", job_type="full-time", companies=["Acme", "Monzo"],
    company_urls={"Acme": "https://acme.example/careers"},
)


@pytest.mark.asyncio
@respx.mock
async def test_out_of_credit_keeps_free_results_and_explains() -> None:
    _routes()
    meter = CostMeter(budget_usd=5.0)
    err = _api_error(anthropic.BadRequestError, 400, "Your credit balance is too low")
    async with httpx.AsyncClient() as client:
        settings = SearchSettings(llm=_llm(err), company_sites=True, meter=meter)
        postings, statuses = await EmployerSearch(client, MemoryCache(), settings).search_companies(
            _QUERY, [_QUERY.role]
        )
    assert [p.company for p in postings] == ["Monzo"]  # the free job board still searched
    acme = next(s for s in statuses if s.company == "Acme")
    assert "search stopped early" in acme.notes[0]
    assert meter.stopped is not None and "credit ran out" in meter.stopped


@pytest.mark.asyncio
@respx.mock
async def test_employer_limit_skips_expensive_site_without_calling_claude() -> None:
    _routes()
    meter = CostMeter(budget_usd=5.0, company_budget_usd=0.0001)
    llm = _llm()
    async with httpx.AsyncClient() as client:
        settings = SearchSettings(llm=llm, company_sites=True, meter=meter)
        _, statuses = await EmployerSearch(client, MemoryCache(), settings).search_companies(
            _QUERY, [_QUERY.role]
        )
    acme = next(s for s in statuses if s.company == "Acme")
    assert "skipped reading website" in acme.notes[0] and "$0.00 limit" in acme.notes[0]
    assert llm.messages.create.await_count == 0  # type: ignore[attr-defined]


@pytest.mark.asyncio
@respx.mock
async def test_site_costs_reported_per_employer() -> None:
    _routes()
    meter = CostMeter(budget_usd=5.0, company_budget_usd=1.0)
    extracted = json.dumps({"postings": [
        {"role": "Data Analyst 1", "location": "London", "url": "https://acme.example/jobs/1"}]})
    llm = _llm(_reply(extracted, _usage(4000, 300)))
    async with httpx.AsyncClient() as client:
        settings = SearchSettings(llm=llm, company_sites=True, meter=meter)
        postings, statuses = await EmployerSearch(client, MemoryCache(), settings).search_companies(
            _QUERY, [_QUERY.role]
        )
    acme = next(s for s in statuses if s.company == "Acme")
    assert acme.cost_usd == pytest.approx(0.0165)
    assert {p.company for p in postings} == {"Acme", "Monzo"}
    sent = llm.messages.create.call_args.kwargs["messages"][0]["content"]  # type: ignore[attr-defined]
    assert "Only include jobs whose title matches" in sent


@pytest.mark.asyncio
@respx.mock
async def test_user_stop_skips_remaining_work() -> None:
    _routes()
    progress = SearchProgress(cancelled=True, meter=CostMeter())
    async with httpx.AsyncClient() as client:
        settings = SearchSettings(llm=_llm(), company_sites=True, meter=progress.meter)
        postings, statuses = await EmployerSearch(
            client, MemoryCache(), settings, progress
        ).search_companies(_QUERY, [_QUERY.role])
    assert postings == []
    assert all("stopped by you" in " ".join(s.notes) for s in statuses)


# ---------------------------------------------------------------------------
# web_scraper endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def scraper(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    cache = MemoryCache()
    monkeypatch.setattr(scraper_api, "_cache", lambda request: cache)
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    with TestClient(scraper_api.app) as c:
        yield c
    scraper_api.app.dependency_overrides.clear()


def test_scraper_stop_and_progress_report_spend(scraper: TestClient) -> None:
    progress = SearchProgress(total=3, done=1, meter=CostMeter())
    assert progress.meter is not None
    progress.meter.record("Acme", "scoring", _usage(1000, 0))
    scraper_api._PROGRESS["run-x"] = progress
    assert scraper.get("/search/progress/run-x").json()["spent_usd"] == pytest.approx(0.003)
    assert scraper.post("/search/stop/run-x").json() == {"ok": True}
    assert progress.cancelled and progress.meter.stopped == "Stopped by you."
    assert scraper.post("/search/stop/unknown").status_code == 404


def test_scraper_plan_counts_work_without_claude(scraper: TestClient) -> None:
    llm = _llm()
    scraper_api.app.dependency_overrides[scraper_api.get_anthropic] = lambda: llm
    body = scraper.post("/search/plan", json={
        "query": {"role": "x", "job_type": "y", "companies": ["Monzo", "Acme", "Beta"],
                  "company_urls": {"Beta": "https://beta.example/jobs"}},
        "search_company_sites": True,
    }).json()
    assert body == {"boards": 1, "adzuna": 0, "websites": 2, "careers_pages_to_find": 1}
    assert llm.messages.create.await_count == 0  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# job_recommender runs with limits
# ---------------------------------------------------------------------------


_POSTING = {"company": "Acme", "role": "Data Analyst", "location": "London",
            "url": "https://acme.example/1", "source": "company_page"}
_SCORE = '{"score": 0.8, "rationale": "Good."}'


@pytest.fixture
def recommender(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("JOBASSIST_DB", ":memory:")
    with TestClient(recommender_app) as c:
        yield c
    recommender_app.dependency_overrides.clear()


def _wait(client: TestClient, run_id: str) -> dict[str, Any]:
    for _ in range(200):
        body: dict[str, Any] = client.get(f"/runs/{run_id}").json()
        if body["state"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError("run did not finish")


def _start(client: TestClient, **extra: Any) -> str:
    resp = client.post("/runs", json={
        "query": {"role": "Data Analyst", "job_type": "full-time", "companies": ["Acme"]},
        "resume": "CV", "expand_aliases": False, **extra,
    })
    run_id: str = resp.json()["run_id"]
    return run_id


def _mock_services(search_body: dict[str, Any]) -> respx.Route:
    route = respx.post("http://localhost:8001/search").mock(
        return_value=httpx.Response(200, json=search_body)
    )
    respx.get(url__regex=r"http://localhost:8001/search/progress/.*").mock(
        return_value=httpx.Response(200, json={"total": 0, "done": 0, "current": "",
                                               "spent_usd": 0.0})
    )
    respx.post(url__regex=r"http://localhost:8001/search/stop/.*").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    respx.post("http://localhost:8002/dedupe").mock(
        return_value=httpx.Response(200, json={"postings": search_body["postings"]})
    )
    return route


def test_run_passes_limits_and_reports_costs(recommender: TestClient) -> None:
    recommender_app.dependency_overrides[recommender_llm] = lambda: _llm(
        _reply(_SCORE, _usage(1000, 100))
    )
    cost = {"company": "Acme", "step": "reading website", "usd": 0.02, "calls": 1,
            "web_searches": 0}
    with respx.mock:
        search = _mock_services({"postings": [_POSTING], "spent_usd": 0.02, "costs": [cost]})
        body = _wait(recommender, _start(recommender))
    sent = json.loads(search.calls[0].request.content)
    assert sent["budget_usd"] == 5.0 and sent["company_budget_usd"] == 0.2
    assert sent["deep_search"] is False
    assert body["state"] == "done" and body["budget_usd"] == 5.0
    assert body["spent_usd"] == pytest.approx(0.02 + 0.0045)
    assert {c["step"] for c in body["costs"]} == {"reading website", "scoring"}


def test_search_spending_whole_budget_leaves_jobs_unscored_but_saved(
    recommender: TestClient,
) -> None:
    llm = _llm()
    recommender_app.dependency_overrides[recommender_llm] = lambda: llm
    stopped = "Spending limit of $1.00 reached (spent $1.00). Everything found so far is kept."
    with respx.mock:
        _mock_services({"postings": [_POSTING], "spent_usd": 1.0, "stopped": stopped})
        body = _wait(recommender, _start(recommender, budget_usd=1.0))
    assert body["state"] == "done"
    assert body["results"] == [] and body["unscored"] == 1
    assert body["stop_reason"] == stopped
    assert llm.messages.create.await_count == 0  # type: ignore[attr-defined]
    saved = recommender.post("/saved", json={}).json()["jobs"]
    assert [j["posting"]["company"] for j in saved] == ["Acme"]


def test_out_of_credit_during_scoring_is_a_clean_finish(recommender: TestClient) -> None:
    err = _api_error(anthropic.BadRequestError, 400, "Your credit balance is too low")
    recommender_app.dependency_overrides[recommender_llm] = lambda: _llm(err)
    with respx.mock:
        _mock_services({"postings": [_POSTING]})
        body = _wait(recommender, _start(recommender))
    assert body["state"] == "done"
    assert "credit ran out" in body["stop_reason"]
    assert body["unscored"] == 1


def test_stop_endpoint_during_scoring_stops_scoring_only(recommender: TestClient) -> None:
    from jobassist.Microservices.job_recommender import api as recommender_api
    from jobassist.Microservices.job_recommender.costs.meter import CostMeter as ScoringMeter
    from jobassist.Microservices.job_recommender.orchestration.pipeline import RunState

    state = RunState(phase="scoring", scoring_meter=ScoringMeter())
    recommender_api._RUNS[state.id] = state
    with respx.mock:  # no search-service call is mocked: none may be made
        body = recommender.post(f"/runs/{state.id}/stop").json()
    assert state.stop_requested and body["message"] == "Stopping scoring…"
    assert state.scoring_meter is not None and state.scoring_meter.stopped == "Stopped by you."


def test_stop_endpoint_during_search_ends_search(recommender: TestClient) -> None:
    from jobassist.Microservices.job_recommender import api as recommender_api
    from jobassist.Microservices.job_recommender.orchestration.pipeline import RunState

    state = RunState(phase="searching")
    recommender_api._RUNS[state.id] = state
    with respx.mock:
        stop = respx.post(f"http://localhost:8001/search/stop/{state.id}").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        respx.get(f"http://localhost:8001/search/progress/{state.id}").mock(
            return_value=httpx.Response(200, json={"total": 1, "done": 0, "current": "ONS",
                                                   "spent_usd": 0.0})
        )
        recommender.post(f"/runs/{state.id}/stop")
        recommender.get(f"/runs/{state.id}")  # a later poll must not hide the stop
    assert stop.call_count == 1 and state.stop_requested
    assert "scoring the jobs found so far" in state.message


def test_estimate_uses_plan(recommender: TestClient) -> None:
    with respx.mock:
        respx.post("http://localhost:8001/search/plan").mock(
            return_value=httpx.Response(200, json={
                "boards": 3, "adzuna": 5, "websites": 5, "careers_pages_to_find": 5})
        )
        body = recommender.post("/estimate", json={
            "query": {"role": "x", "job_type": "y", "max_results": 50},
            "search_company_sites": True,
        }).json()
    assert 0 < body["low_usd"] < body["high_usd"] < 5
    assert body["websites"] == 5



# ---------------------------------------------------------------------------
# Hard caps, time limits and Stop (Nov 2026 fixes)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_employer_cap_blocks_web_search_before_it_runs() -> None:
    from jobassist.Microservices.web_scraper.sources.company_pages.discovery import (
        CareersPageFinder,
    )

    meter = CostMeter(budget_usd=5.0, company_budget_usd=0.20)
    llm = _llm(_reply('{"found": false}', _usage(500, 50)))
    finder = CareersPageFinder(llm, MemoryCache(), meter=meter, web_search=True)
    with pytest.raises(EmployerLimit, match=r"\$0.20 limit"):
        await finder.find("Expensive University")
    assert llm.messages.create.await_count == 1  # the guess ran; the web search never did


@pytest.mark.asyncio
@respx.mock
async def test_slow_website_is_skipped_after_time_limit() -> None:
    import asyncio

    _routes()
    query = JobQuery(role="Data Analyst", job_type="full-time", companies=["Acme"],
                     company_urls={"Acme": "https://acme.example/careers"})

    async def slow(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(5)
        return _reply("{}")

    llm = MagicMock(spec=anthropic.AsyncAnthropic)
    llm.messages = MagicMock()
    llm.messages.create = slow
    async with httpx.AsyncClient() as client:
        settings = SearchSettings(llm=llm, company_sites=True, meter=CostMeter(),  # type: ignore[arg-type]
                                  site_timeout=0.2)
        postings, statuses = await EmployerSearch(client, MemoryCache(), settings).search_companies(
            query, [query.role]
        )
    assert postings == []
    assert "took longer than 0 seconds" in statuses[0].notes[0]


@pytest.mark.asyncio
@respx.mock
async def test_stop_cancels_work_in_progress_and_keeps_finished_results() -> None:
    import asyncio

    _routes()
    started = asyncio.Event()

    async def hang(*args: Any, **kwargs: Any) -> Any:
        started.set()
        await asyncio.sleep(60)
        return _reply("{}")

    llm = MagicMock(spec=anthropic.AsyncAnthropic)
    llm.messages = MagicMock()
    llm.messages.create = hang
    progress = SearchProgress(meter=CostMeter())
    async with httpx.AsyncClient() as client:
        settings = SearchSettings(llm=llm, company_sites=True, meter=progress.meter)  # type: ignore[arg-type]
        search = EmployerSearch(client, MemoryCache(), settings, progress)
        task = asyncio.create_task(search.search_companies(_QUERY, [_QUERY.role]))
        await asyncio.wait_for(started.wait(), 5)
        await asyncio.sleep(1.5)  # let the free job-board fetch finish its politeness pause
        progress.stop()
        postings, statuses = await asyncio.wait_for(task, 5)  # returns promptly, not in 60s
    assert [p.company for p in postings] == ["Monzo"]  # finished board result kept
    acme = next(s for s in statuses if s.company == "Acme")
    assert "stopped by you" in " ".join(acme.notes)
    monzo = next(s for s in statuses if s.company == "Monzo")
    assert "stopped by you" not in " ".join(monzo.notes)  # it was searched


def test_stopped_run_lists_unscored_jobs(recommender: TestClient) -> None:
    llm = _llm(RuntimeError("unexpected failure scoring this job"))
    recommender_app.dependency_overrides[recommender_llm] = lambda: llm
    with respx.mock:
        _mock_services({"postings": [_POSTING], "stopped": "Stopped by you."})
        run_id = _start(recommender)
        body = _wait(recommender, run_id)
    assert body["results"] == []
    assert [p["company"] for p in body["unscored_postings"]] == ["Acme"]


def test_estimate_respects_caps_and_deep_search(recommender: TestClient) -> None:
    plan = {"boards": 0, "adzuna": 0, "websites": 10, "careers_pages_to_find": 10}
    with respx.mock:
        respx.post("http://localhost:8001/search/plan").mock(
            return_value=httpx.Response(200, json=plan)
        )
        base = {"query": {"role": "x", "job_type": "y", "max_results": 10},
                "search_company_sites": True}
        normal = recommender.post("/estimate", json=base).json()
        deep_blocked = recommender.post("/estimate", json={**base, "deep_search": True}).json()
        deep = recommender.post("/estimate", json={
            **base, "deep_search": True, "company_budget_usd": 1.0, "budget_usd": 2.0}).json()
    assert normal["high_usd"] == deep_blocked["high_usd"] < 1.0  # $0.20 cap: no web search
    assert deep["high_usd"] == 2.0  # capped by the run limit



# ---------------------------------------------------------------------------
# Stop during the search → straight to scoring
# ---------------------------------------------------------------------------


class _StopDuringSearch:
    """A web_scraper client whose search is 'stopped' by the user mid-way."""

    def __init__(self, state: Any, postings: list[Any]) -> None:
        self._state = state
        self._postings = postings

    async def search(self, *args: Any, **kwargs: Any) -> Any:
        from jobassist.Microservices.job_recommender.clients import SearchResult

        self._state.stop_requested = True  # the user pressed Stop while searching
        return SearchResult(postings=self._postings, stopped="Stopped by you.")


class _PassThroughCleaner:
    async def dedupe(self, postings: list[Any]) -> list[Any]:
        return postings


@pytest.mark.asyncio
async def test_stop_during_search_still_scores_found_jobs() -> None:
    from jobassist.Microservices.job_recommender.models import JobPosting
    from jobassist.Microservices.job_recommender.orchestration.pipeline import (
        PipelineOptions,
        RunState,
        run_pipeline,
    )
    from jobassist.Microservices.job_recommender.persistence.store import Store

    postings = [JobPosting.model_validate({**_POSTING, "company": c}) for c in ("A", "B")]
    state = RunState()
    llm = _llm(_reply(_SCORE, _usage(1000, 100)), _reply(_SCORE, _usage(1000, 100)))
    await run_pipeline(
        PipelineOptions(query=JobQuery(role="x", job_type="y"), resume="CV"),  # type: ignore[arg-type]
        llm,
        _StopDuringSearch(state, postings),  # type: ignore[arg-type]
        _PassThroughCleaner(),  # type: ignore[arg-type]
        Store(":memory:"),
        state,
    )
    assert state.state == "done"
    assert [r.posting.company for r in state.results] == ["A", "B"]
    assert state.unscored == 0
    assert state.stop_reason == "Search stopped by you — scored the 2 jobs found so far."
