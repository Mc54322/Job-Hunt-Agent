"""The recommend pipeline — search → dedupe → cap → score → rank — with live run state.

Shared by the synchronous `/recommend` endpoint (CLI) and background `/runs` (web UI),
which polls the `RunState` for progress.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import anthropic
import httpx

from jobassist.Microservices.job_recommender.cache_client import LocalCacheClient
from jobassist.Microservices.job_recommender.clients import DataCleanerClient, WebScraperClient
from jobassist.Microservices.job_recommender.costs.meter import BudgetStop, CallFailed, CostMeter
from jobassist.Microservices.job_recommender.models import (
    CompanySearchStatus,
    CostLine,
    JobPosting,
    JobQuery,
    ScoredPosting,
)
from jobassist.Microservices.job_recommender.persistence.store import Store
from jobassist.Microservices.job_recommender.ranking.filters import (
    cap_for_scoring,
    top_per_company,
)
from jobassist.Microservices.job_recommender.scoring.scorer import ScoringPipeline

SCORING_CONCURRENCY = 5
DEFAULT_BUDGET_USD = 5.0
DEFAULT_COMPANY_BUDGET_USD = 0.50


@dataclass
class PipelineOptions:
    """Everything a run needs besides the services."""

    query: JobQuery
    resume: str
    one_per_company: bool = True
    expand_aliases: bool = True
    refresh: bool = False
    search_company_sites: bool = False
    budget_usd: float | None = DEFAULT_BUDGET_USD
    company_budget_usd: float | None = DEFAULT_COMPANY_BUDGET_USD


@dataclass
class RunState:
    """Progress and outcome of one pipeline run."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: str = "running"  # running | done | error
    phase: str = "starting"  # starting | searching | cleaning | scoring | done
    message: str = "Starting"
    done: int = 0
    total: int = 0
    results: list[ScoredPosting] = field(default_factory=list)
    companies: list[CompanySearchStatus] = field(default_factory=list)
    error: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    budget_usd: float | None = None
    spent_usd: float = 0.0
    costs: list[CostLine] = field(default_factory=list)
    stop_reason: str | None = None  # why the run finished early, if it did
    stop_requested: bool = False
    scoring_meter: CostMeter | None = None
    unscored: int = 0  # found but not scored (limit, stop, or failed calls)


def friendly_error(exc: BaseException) -> str:
    """A plain-English explanation of a pipeline failure, for non-technical users."""
    if isinstance(exc, httpx.ConnectError):
        return (
            "One of JobAssist's background services isn't running. "
            "Close JobAssist and start it again."
        )
    if isinstance(exc, httpx.TimeoutException):
        return "The search took too long and was stopped. Try fewer employers or try again."
    if isinstance(exc, anthropic.AuthenticationError):
        return "Your Anthropic API key was rejected. Check ANTHROPIC_API_KEY in the .env file."
    if isinstance(exc, anthropic.RateLimitError):
        return "Anthropic is limiting requests right now. Wait a minute and try again."
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code == 400:
        return f"Anthropic rejected a request: {exc.message}"
    return f"Something went wrong: {exc}"


async def run_pipeline(
    options: PipelineOptions,
    client: anthropic.AsyncAnthropic,
    web_scraper: WebScraperClient,
    data_cleaner: DataCleanerClient,
    store: Store,
    state: RunState,
) -> None:
    """Run the full pipeline, updating *state* as it goes.

    Spending limits, the Stop button and an empty Anthropic account end the run early
    but cleanly: everything found is saved, and whatever was scored is returned.
    Raises only for failures that leave nothing to show.
    """
    state.budget_usd = options.budget_usd
    state.phase = "searching"
    state.message = "Searching job boards and company websites"
    found = await web_scraper.search(
        options.query,
        expand_aliases=options.expand_aliases,
        refresh=options.refresh,
        search_company_sites=options.search_company_sites,
        run_id=state.id,
        budget_usd=options.budget_usd,
        company_budget_usd=options.company_budget_usd,
    )
    state.companies = found.companies
    state.spent_usd = found.spent_usd
    state.costs = list(found.costs)
    state.stop_reason = found.stopped
    # Save everything found now, so it shows under Saved jobs whatever happens next.
    for posting in found.postings:
        store.save(posting)

    state.phase = "cleaning"
    state.message = f"Removing duplicates from {len(found.postings)} jobs"
    state.done = state.total = 0
    unique = await data_cleaner.dedupe(found.postings)
    # Scoring is the dominant cost: cap the total, spread fairly across companies.
    unique = cap_for_scoring(unique, options.query.max_results)

    remaining = (
        max(0.0, options.budget_usd - found.spent_usd) if options.budget_usd is not None else None
    )
    meter = CostMeter(remaining)
    state.scoring_meter = meter
    if state.stop_requested:
        meter.cancel()
    elif found.stopped and "credit" in found.stopped.lower():
        meter.cancel(found.stopped)

    state.phase = "scoring"
    state.total = len(unique)
    state.message = f"Scoring {len(unique)} jobs against your CV"
    pipeline = ScoringPipeline(client, options.resume, LocalCacheClient(store), meter=meter)
    limit = asyncio.Semaphore(SCORING_CONCURRENCY)

    async def _score(posting: JobPosting) -> ScoredPosting | None:
        async with limit:
            try:
                return await pipeline.score(posting)
            except (BudgetStop, CallFailed, ValueError):
                return None  # limit/stop/credit (reason on the meter) or a bad reply
            finally:
                state.done += 1
                state.spent_usd = found.spent_usd + meter.spent_usd

    outcomes = await asyncio.gather(*(_score(p) for p in unique))
    scored = [s for s in outcomes if s is not None]
    state.unscored = len(unique) - len(scored)
    state.spent_usd = round(found.spent_usd + meter.spent_usd, 4)
    state.costs = sorted(state.costs + meter.lines(), key=lambda c: -c.usd)
    if meter.stopped and not state.stop_reason:
        state.stop_reason = meter.stopped
    if state.stop_requested and not state.stop_reason:
        state.stop_reason = "Stopped by you."
    if options.one_per_company:
        scored = top_per_company(scored)

    state.results = sorted(scored, key=lambda s: s.score, reverse=True)
    state.phase = "done"
    state.state = "done"
    state.message = f"Found {len(state.results)} jobs"
    state.finished_at = datetime.now(timezone.utc)
