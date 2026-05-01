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
  schemas.py     # JobQuery, JobPosting, ScoredPosting
  cli.py         # typer CLI entry point
  sources/       # one file per job source
tests/
  test_schemas.py
```
