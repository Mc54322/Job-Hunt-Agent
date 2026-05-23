# JobAssist AI

A personal job aggregator that pulls postings from ATS boards and job aggregators, deduplicates them, and scores each one against your resume using Claude. Built for UK job hunting.

## What it does

1. **Fetches** postings from multiple sources in parallel — Greenhouse, Lever, Ashby, SmartRecruiters, Teamtailor (direct ATS), plus Adzuna and Reed (UK aggregators)
2. **Deduplicates** across sources, preferring ATS-direct postings over aggregator copies, and collapsing same-role/multi-location spam
3. **Scores** each posting against your resume using Claude, with prompt caching so your resume is only embedded once per run
4. **Filters** to one result per company by default (the best-scoring role), keeping the table scannable
5. **Outputs** a scored Rich table in the terminal, with optional Markdown report export

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- An [Anthropic API key](https://console.anthropic.com/) (required — used for scoring)
- At least one job source: Adzuna credentials, a Reed API key, or one or more `--company` targets

## Setup

```bash
git clone <repo>
cd job-hunt-agent
uv sync
cp .env.example .env
```

Edit `.env` and fill in your keys:

```
ANTHROPIC_API_KEY=sk-ant-...
ADZUNA_APP_ID=...            # free at developer.adzuna.com
ADZUNA_APP_KEY=...
REED_API_KEY=...             # free at reed.co.uk/developers
```

Save your resume as plain text and point to it with `--resume` or the `JOBASSIST_RESUME` env var.

## Usage

```bash
# Basic search — Reed + Adzuna, scored against your resume
uv run --env-file .env jobassist search "Software Engineer" full-time \
  --location "London, UK" --resume resume.txt

# Target specific companies directly via their ATS boards
uv run --env-file .env jobassist search "Data Analyst" full-time \
  -c DeepMind -c Palantir --resume resume.txt

# Search across all FTSE 100 companies on Greenhouse/Lever
uv run --env-file .env jobassist search "Software Engineer" full-time \
  --index ftse100 --resume resume.txt

# Export a Markdown report
uv run --env-file .env jobassist search "Engineer" full-time \
  --resume resume.txt --report results.md

# Show every matching role per company, not just the best-scoring one
uv run --env-file .env jobassist search "Software Engineer" full-time \
  --resume resume.txt --all-per-company

# Skip role alias expansion (faster, fewer LLM calls)
uv run --env-file .env jobassist search "Graduate Engineer" full-time \
  --resume resume.txt --no-aliases
```

### All options

| Flag | Default | Description |
|---|---|---|
| `--location`, `-l` | none | Geographic filter, e.g. `"London, UK"` |
| `--company`, `-c` | none | Target a specific company (repeatable) |
| `--index` | none | Expand companies from `ftse100` or `aim100` |
| `--max-results`, `-n` | 50 | Max postings to fetch across all sources |
| `--resume`, `-r` | `$JOBASSIST_RESUME` | Path to your resume (plain text) |
| `--report` | none | Write a Markdown report to this path |
| `--aliases/--no-aliases` | on | Expand role to synonyms before searching |
| `--one-per-company/--all-per-company` | on | Show only best-scoring role per company |
| `--db` | `~/.jobassist/data.db` | SQLite store path |

## Sources

| Source | Type | Auth required | Coverage |
|---|---|---|---|
| Greenhouse | ATS direct | None | Broad UK/global tech |
| Lever | ATS direct | None | Broad UK/global tech |
| Ashby | ATS direct | None | UK/US startups |
| SmartRecruiters | ATS direct | None | Mid-market enterprise |
| Teamtailor | ATS direct | API token | European startups |
| Adzuna | Aggregator | App ID + Key (free) | UK broad market |
| Reed | Aggregator | API key (free) | UK broad market |

ATS-direct sources are always preferred over aggregator copies when the same job appears in both.

## Development

```bash
uv run pytest                    # run all 289 tests
uv run pytest --tb=short -q      # quiet mode
uv run ruff check .              # lint
uv run mypy jobassist/           # type-check (strict)
```

## Project structure

```
jobassist/
  schemas.py        # JobQuery, JobPosting, ScoredPosting, posting_hash
  cli.py            # Typer CLI — wires sources, dedupe, scorer, rich table
  dedupe.py         # Two-pass deduplication: exact hash + soft key (company+role)
  scorer.py         # LLM scoring pipeline with prompt caching (Claude)
  store.py          # SQLite store for postings + LLM/HTTP response cache
  aliases.py        # Role alias generator (LLM, cached by role+job_type)
  extractor.py      # LLM extractor for unknown company pages (Claude + Pydantic)
  report.py         # Markdown report generator
  index.py          # FTSE 100 / AIM 100 company lists
  drafter.py        # Cover letter + CV bullet drafter (Claude, facts-only)
  salary.py         # Salary normaliser — parses raw strings to SalaryRange
  volume.py         # Applicant-volume estimate heuristic
  filters.py        # Post-scoring filters (top-per-company)
  sources/
    base.py             # Source protocol (structural subtyping)
    detector.py         # ATS detector — URL/HTML → ATS type
    greenhouse.py       # Greenhouse ATS fetcher
    lever.py            # Lever ATS fetcher
    ashby.py            # Ashby ATS fetcher
    smartrecruiters.py  # SmartRecruiters ATS fetcher
    teamtailor.py       # Teamtailor ATS fetcher
    adzuna.py           # Adzuna aggregator (UK)
    reed.py             # Reed UK job board
    company_page.py     # Generic company-page fetcher (httpx + trafilatura + Playwright)
tests/
  fixtures/             # Captured API responses used by unit tests
  test_schemas.py
  test_source_protocol.py
  test_ats_fetchers.py
  test_additional_ats.py
  test_adzuna.py
  test_dedupe.py
  test_store.py
  test_scorer.py
  test_cli.py
  test_detector.py
  test_reed.py
  test_company_page.py
  test_extractor.py
  test_report.py
  test_aliases.py
  test_index.py
  test_drafter.py
  test_salary.py
  test_volume.py
  test_filters.py
```

## Design decisions

- **No LinkedIn, no Indeed scraping** — LinkedIn's Jobs API is closed to new partners; Indeed's Publisher API is deprecated. Both violate ToS if scraped. Coverage loss is minimal because companies cross-post to their ATS boards anyway.
- **LLM calls are cached** — every Claude call is keyed by content hash and stored in SQLite. Re-running the same search costs nothing after the first run.
- **Resume embedded once** — the full resume text goes into the system prompt once per session using prompt caching. Individual scoring calls only reference it by cache pointer.
- **ATS-direct beats aggregator** — if the same job appears on both Greenhouse and Adzuna, the Greenhouse copy is kept. ATS postings contain richer data and link directly to the apply page.
- **Rate limiting** — 1 req/sec ± 200ms jitter per domain, real User-Agent with contact URL. `robots.txt` respected.
