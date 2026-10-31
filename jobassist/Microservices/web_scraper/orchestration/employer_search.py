"""Search orchestration for the web_scraper `/search` endpoint.

Named employers are searched one by one, each as small cached units:

- **ATS board** — when the company's public jobs board is known (registry or sheet URL).
- **Adzuna** — filtered to that employer, for companies with no known board.
- **Company website** — the company's own careers page (from the sheet, or found by
  web search), scraped and read by the LLM extractor; if the site turns out to be an
  ATS board, that board's JSON feed is used instead.

Without named employers it is a broad Adzuna + Reed keyword search. Every unit goes
through `ResultsCache` (24h); `refresh` forces fresh fetches.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Callable, Mapping

import anthropic
import httpx

from jobassist.Microservices.web_scraper.cache_client import CacheClient
from jobassist.Microservices.web_scraper.caching.results_cache import ResultsCache
from jobassist.Microservices.web_scraper.contracts.base import Source
from jobassist.Microservices.web_scraper.costs.meter import (
    BudgetStop,
    CallFailed,
    CostMeter,
    EmployerLimit,
)
from jobassist.Microservices.web_scraper.employers.registry import (
    Board,
    adzuna_employer_name,
    plan_employers,
)
from jobassist.Microservices.web_scraper.filtering.location import location_matches
from jobassist.Microservices.web_scraper.models.schemas import (
    CompanySearchStatus,
    JobPosting,
    JobQuery,
)
from jobassist.Microservices.web_scraper.politeness.robots import RobotsChecker
from jobassist.Microservices.web_scraper.sources.aggregators.adzuna.adzuna import AdzunaFetcher
from jobassist.Microservices.web_scraper.sources.aggregators.reed.reed import ReedFetcher
from jobassist.Microservices.web_scraper.sources.ats.ashby.ashby import AshbyFetcher
from jobassist.Microservices.web_scraper.sources.ats.greenhouse.greenhouse import GreenhouseFetcher
from jobassist.Microservices.web_scraper.sources.ats.lever.lever import LeverFetcher
from jobassist.Microservices.web_scraper.sources.ats.smartrecruiters.smartrecruiters import (
    SmartRecruitersFetcher,
)
from jobassist.Microservices.web_scraper.sources.ats.workable.workable import WorkableFetcher
from jobassist.Microservices.web_scraper.sources.company_pages.company_site import (
    CompanySiteSearcher,
)
from jobassist.Microservices.web_scraper.sources.company_pages.discovery import (
    CareersPage,
    CareersPageFinder,
)
from jobassist.Microservices.web_scraper.sources.company_pages.extractor import PageExtractor

ATS_FETCHERS: dict[str, Callable[[httpx.AsyncClient, Mapping[str, str]], Source]] = {
    "greenhouse": lambda http, slugs: GreenhouseFetcher(http, slugs=slugs),
    "lever": lambda http, slugs: LeverFetcher(http, slugs=slugs),
    "ashby": lambda http, slugs: AshbyFetcher(http, slugs=slugs),
    "smartrecruiters": lambda http, slugs: SmartRecruitersFetcher(http, slugs=slugs),
    "workable": lambda http, slugs: WorkableFetcher(http, slugs=slugs),
}
AGGREGATORS = {"adzuna", "reed"}
# Adzuna's free tier allows ~25 calls/minute; one call per employer, spaced to stay under.
EMPLOYER_SEARCH_DELAY = 3.0
EMPLOYER_MAX_RESULTS = 20
# Company websites are separate domains, so a few can be read at once.
SITE_CONCURRENCY = 4


@dataclass
class SearchProgress:
    """Live progress of one search, polled by the job_recommender for the UI."""

    total: int = 0
    done: int = 0
    current: str = ""
    cancelled: bool = False  # the user pressed Stop
    meter: CostMeter | None = None

    def tick(self, label: str) -> None:
        self.done += 1
        self.current = label


@dataclass
class SearchSettings:
    """Credentials and switches for one search."""

    adzuna: tuple[str, str] | None = None
    reed_key: str | None = None
    llm: anthropic.AsyncAnthropic | None = None
    refresh: bool = False
    company_sites: bool = False
    employer_delay: float = EMPLOYER_SEARCH_DELAY
    meter: CostMeter | None = None


async def collect(source: Source, queries: list[JobQuery]) -> list[JobPosting]:
    """Run *source* over each query in turn (sequential — same domain, same rate limit)."""
    postings: list[JobPosting] = []
    for q in queries:
        async for posting in await source.search(q):
            postings.append(posting)
    return postings


@dataclass
class _Notes:
    by_company: dict[str, list[str]] = field(default_factory=dict)

    def add(self, company: str, note: str) -> None:
        if note:
            self.by_company.setdefault(company, []).append(note)


class EmployerSearch:
    """One search run across employers or broad aggregator keywords."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        cache: CacheClient,
        settings: SearchSettings,
        progress: SearchProgress | None = None,
    ) -> None:
        self._http = http
        self._settings = settings
        self._results = ResultsCache(cache, refresh=settings.refresh)
        self._progress = progress or SearchProgress()
        self._notes = _Notes()
        self._meter = settings.meter
        self._finder: CareersPageFinder | None = None
        self._sites: CompanySiteSearcher | None = None
        if settings.llm is not None:
            robots = RobotsChecker(http)
            self._finder = CareersPageFinder(
                settings.llm, cache, http=http, robots=robots, meter=self._meter
            )
            self._sites = CompanySiteSearcher(
                http, PageExtractor(settings.llm, cache, meter=self._meter), robots
            )

    def _skip_if_cancelled(self, company: str, label: str) -> bool:
        if not self._progress.cancelled:
            return False
        self._notes.add(company, "not searched — stopped by you")
        self._progress.tick(label)
        return True

    # --- Broad search -------------------------------------------------------

    async def search_broad(self, query: JobQuery, roles: list[str]) -> list[JobPosting]:
        """Keyword search across Adzuna + Reed for every role variant."""
        variants = [query.model_copy(update={"role": r}) for r in roles]
        key = ["|".join(roles), query.location or "", str(query.max_results)]
        jobs = []
        if self._settings.adzuna:
            app_id, app_key = self._settings.adzuna
            fetcher = AdzunaFetcher(self._http, app_id, app_key)
            jobs.append(self._results.get_or_fetch(["broad", "adzuna", *key],
                                                   lambda: collect(fetcher, variants)))
        if self._settings.reed_key:
            reed = ReedFetcher(self._http, self._settings.reed_key)
            jobs.append(self._results.get_or_fetch(["broad", "reed", *key],
                                                   lambda: collect(reed, variants)))
        self._progress.total = len(jobs)
        postings: list[JobPosting] = []
        for batch, _ in await asyncio.gather(*jobs):
            postings.extend(batch)
            self._progress.tick("job sites")
        return postings

    # --- Named employers ----------------------------------------------------

    async def search_companies(
        self, query: JobQuery, roles: list[str]
    ) -> tuple[list[JobPosting], list[CompanySearchStatus]]:
        """Search each employer in *query.companies*; return postings and per-company status."""
        q = query.model_copy(update={"role_aliases": roles[1:]})
        boards, unresolved = plan_employers(query.companies, query.company_urls)
        do_sites = self._settings.company_sites
        if do_sites and self._sites is None:
            for company in unresolved:
                self._notes.add(company, "website search needs the Anthropic API key")
            do_sites = False

        self._progress.total = (
            sum(len(slugs) for slugs in boards.values())
            + (len(unresolved) if self._settings.adzuna else 0)
            + (len(unresolved) if do_sites else 0)
        )

        jobs = [self._boards_in_turn(ats, slugs, q) for ats, slugs in boards.items()]
        if self._settings.adzuna and unresolved:
            jobs.append(self._adzuna_in_turn(unresolved, query))
        if do_sites and unresolved:
            jobs.append(self._sites_concurrently(unresolved, q))
        postings = [p for batch in await asyncio.gather(*jobs) for p in batch]

        if query.location:
            wanted = query.location
            postings = [
                p for p in postings
                if p.source in AGGREGATORS or location_matches(p.location, wanted)
            ]
        return postings, self._statuses(query.companies, postings)

    async def _board(self, company: str, board: Board, q: JobQuery) -> list[JobPosting]:
        fetcher = ATS_FETCHERS[board.ats](self._http, {company: board.slug})
        board_query = q.model_copy(update={"companies": [company]})
        key = ["ats", board.ats, board.slug, company, "|".join(q.role_terms()).lower()]
        postings, _ = await self._results.get_or_fetch(
            key, lambda: collect(fetcher, [board_query])
        )
        return postings

    async def _boards_in_turn(
        self, ats: str, slugs: dict[str, str], q: JobQuery
    ) -> list[JobPosting]:
        postings: list[JobPosting] = []
        for company, slug in slugs.items():
            if self._skip_if_cancelled(company, company):
                continue
            postings.extend(await self._board(company, Board(ats, slug), q))
            self._notes.add(company, f"searched their {ats.title()} jobs board")
            self._progress.tick(company)
        return postings

    async def _adzuna_in_turn(self, companies: list[str], query: JobQuery) -> list[JobPosting]:
        assert self._settings.adzuna is not None
        app_id, app_key = self._settings.adzuna
        employer_query = query.model_copy(
            update={"max_results": min(query.max_results, EMPLOYER_MAX_RESULTS)}
        )
        postings: list[JobPosting] = []
        paced = False
        for company in companies:
            if self._skip_if_cancelled(company, company):
                continue
            fetcher = AdzunaFetcher(
                self._http, app_id, app_key,
                employer=adzuna_employer_name(company), employer_label=company,
            )
            key = ["adzuna", company, query.role, query.location or ""]

            async def fetch(f: AdzunaFetcher = fetcher) -> list[JobPosting]:
                nonlocal paced
                if paced:
                    await asyncio.sleep(self._settings.employer_delay)
                paced = True
                return await collect(f, [employer_query])

            batch, _ = await self._results.get_or_fetch(key, fetch)
            postings.extend(batch)
            self._progress.tick(company)
        return postings

    async def _sites_concurrently(self, companies: list[str], q: JobQuery) -> list[JobPosting]:
        limit = asyncio.Semaphore(SITE_CONCURRENCY)

        async def one(company: str) -> list[JobPosting]:
            async with limit:
                label = f"{company} website"
                if self._skip_if_cancelled(company, label):
                    return []
                self._progress.current = label
                try:
                    return await self._site(company, q)
                except BudgetStop:
                    self._notes.add(company, "website not searched — search stopped early")
                except EmployerLimit as exc:
                    self._notes.add(company, str(exc))
                except CallFailed as exc:
                    self._notes.add(company, f"website reading failed ({exc})")
                finally:
                    self._progress.tick(label)
                return []

        return [p for batch in await asyncio.gather(*(one(c) for c in companies)) for p in batch]

    async def _site(self, company: str, q: JobQuery) -> list[JobPosting]:
        assert self._finder is not None and self._sites is not None
        url = q.company_urls.get(company)
        page = CareersPage(listing_url=url) if url else await self._finder.find(company)
        if page is None:
            self._notes.add(company, "couldn't find a careers website")
            return []
        sites = self._sites

        async def fetch() -> list[JobPosting]:
            outcome = await sites.search(company, page, q)
            self._notes.add(company, outcome.note)
            if outcome.board is not None:
                return await self._board(company, outcome.board, q)
            return outcome.postings

        key = ["site", company, page.url_for(q.role), "|".join(q.role_terms()).lower()]
        postings, from_cache = await self._results.get_or_fetch(key, fetch)
        if from_cache:
            self._notes.add(company, "website: using results saved in the last 24 hours")
        return postings

    def _statuses(
        self, companies: list[str], postings: list[JobPosting]
    ) -> list[CompanySearchStatus]:
        found: dict[str, dict[str, int]] = {c: {} for c in companies}
        for p in postings:
            counts = found.setdefault(p.company, {})
            counts[p.source] = counts.get(p.source, 0) + 1
        return [
            CompanySearchStatus(
                company=c,
                found=found.get(c, {}),
                notes=self._notes.by_company.get(c, []),
                cost_usd=round(self._meter.company_spent(c), 4) if self._meter else 0.0,
            )
            for c in companies
        ]
