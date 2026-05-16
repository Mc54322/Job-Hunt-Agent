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
  sources/
    base.py         # Source protocol
    greenhouse.py   # Greenhouse ATS fetcher
    lever.py        # Lever ATS fetcher
    adzuna.py       # Adzuna aggregator fetcher (UK)
tests/
  fixtures/
    greenhouse_acme.json
    lever_acme.json
    adzuna_search_p1.json
    adzuna_search_p2.json
  test_schemas.py
  test_source_protocol.py
  test_ats_fetchers.py
  test_adzuna.py
  test_dedupe.py
  test_store.py
  test_scorer.py
  test_cli.py
```
