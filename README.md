# JobAssist AI

Personal job aggregator that pulls postings from ATS boards and job aggregators, deduplicates them, and scores each one against your resume.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env   # add your API keys
```

## Usage

```bash
uv run jobassist search "Software Engineer" full-time --location "London, UK"
uv run jobassist search "Data Analyst" contract -c DeepMind -c Palantir -n 20
```

## Development

```bash
uv run pytest          # run tests
uv run ruff check .    # lint
uv run mypy jobassist/ # type-check
```

## Project structure

```
jobassist/
  schemas.py        # JobQuery, JobPosting, ScoredPosting, posting_hash
  cli.py            # typer CLI — wires sources, dedupe, scorer, rich table
  dedupe.py         # deduplication — ATS-direct beats aggregator
  scorer.py         # LLM scoring pipeline with prompt caching (Claude)
  store.py          # SQLite store for postings + LLM/HTTP response cache
  aliases.py         # Role alias generator (LLM, cached)
  extractor.py       # LLM extractor for unknown company pages (Claude + pydantic)
  report.py          # Markdown report generator
  sources/
    base.py            # Source protocol
    detector.py        # ATS detector — URL/HTML → ATS type
    greenhouse.py      # Greenhouse ATS fetcher
    lever.py           # Lever ATS fetcher
    workday.py         # Workday ATS fetcher
    adzuna.py          # Adzuna aggregator fetcher (UK)
    reed.py            # Reed UK job board fetcher
    company_page.py    # Generic company-page fetcher (httpx + trafilatura + Playwright)
tests/
  fixtures/
    greenhouse_acme.json
    lever_acme.json
    adzuna_search_p1.json
    adzuna_search_p2.json
    workday_jobs.json
    reed_search.json
  test_schemas.py
  test_source_protocol.py
  test_ats_fetchers.py
  test_adzuna.py
  test_dedupe.py
  test_store.py
  test_scorer.py
  test_cli.py
  test_detector.py
  test_workday.py
  test_reed.py
  test_company_page.py
  test_extractor.py
  test_report.py
  test_aliases.py
```
