# JobAssist AI

A personal job aggregator that pulls postings from ATS boards and job aggregators, deduplicates them, and scores each one against your resume using Claude. Built for UK job hunting.

## What it does

1. **Fetches** postings from multiple sources in parallel — Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Teamtailor (direct ATS), plus Adzuna and Reed (UK aggregators). Can target a list of named employers loaded from an Excel sheet
2. **Deduplicates** across sources, preferring ATS-direct postings over aggregator copies, and collapsing same-role/multi-location spam
3. **Scores** each posting against your resume using Claude, with prompt caching so your resume is only embedded once per run
4. **Filters** to one result per company by default (the best-scoring role), keeping the table scannable
5. **Outputs** a scored Rich table in the terminal, with optional Markdown report export

## The easy way: the JobAssist web page (no coding needed)

1. In Finder, open this folder and **double-click `Start JobAssist.command`**.
   (If macOS says it can't be opened, right-click it → **Open** → **Open**.)
2. The first time only, it asks for your **Anthropic API key** (and optional free Adzuna /
   Reed keys), then spends a few minutes installing what it needs.
3. Your browser opens **http://localhost:8000**. Then:
   - **Your CV** — choose your CV (PDF, Word or text). It's remembered for next time.
   - **What job** — job title, type, and where (e.g. `UK` or `London`).
   - **Where to look** — your Excel employer list (tick "Only my starred employers" or pick
     groups), or all job sites. Leave **"Also search each company's own website"** on to
     have JobAssist visit each employer's careers site too.
   - Press **Find jobs**. A progress bar shows what it's doing; you can leave the page and
     come back.
4. Results are ranked by how well they match your CV — press **Why?** for the reasoning,
   **Download spreadsheet** to open them in Excel, and expand **"What was searched at each
   employer"** to see where JobAssist looked.
5. **Saved jobs** (bottom of the page) lists every job found in earlier searches, with match
   scores already worked out for your current CV — instant and free, nothing is searched
   or scored. Filter it, or download it as a spreadsheet.
6. To stop JobAssist, close the Terminal window that opened in step 1.

**Make an employer list.** Anyone can create the employer-tracking spreadsheet from a
plain text list in the **Make an employer list** section of the page (free — no Claude).
Write one company per line; a line ending with `:` starts a group; `Y` or `*` stars a
company; a link after a name fills its careers page:

```
University: Leeds          (optional — names the alumni column)

London tech:
Google
Monzo, Y
Ocado Technology *

Government and public sector:
Bank of England, Y
Office for National Statistics, https://careers.ons.gov.uk
```

Then **Download Excel file** (same layout as the original tracker: How to use, Employers
with stars/status/contacts columns and dropdowns, and a Summary tab), or **Use this list
for my search**. Without the web page:
`uv run jobassist-make-list my-companies.txt --university Leeds` (add `--example` to see
the format).

**Saved results.** Every search is saved for 24 hours, so running the same search again is
almost instant and free. To force a completely fresh search, open **More options** and tick
**"Search again from scratch"**. Each company's careers-page address is remembered for 30
days (so the web search to find it isn't repeated); put a link in your sheet's
`Careers page link` column to set it yourself.

**Cost and spending limits.** Claude is used to find careers pages, read company
websites and score jobs against your CV. Before you start, the page shows an estimate
next to **Find jobs**. Every search has a **spending limit ($5 by default)** and a
**limit per employer website ($0.50)** — both under **More options**. When a limit is
reached, or your Anthropic credit runs out, JobAssist stops using Claude, keeps and shows
everything found so far, and says why; an employer whose website would cost more than
its limit is skipped and flagged. **Stop search** on the progress bar stops at any time.
The results show what the search cost, and "What was searched at each employer" shows the
cost per employer. Costs are JobAssist's estimates from published prices — your Anthropic
console is the official record.

To keep costs down, JobAssist asks Claude for each careers page from memory and checks it
with a free fetch (web search only if that fails), skips any website that never mentions
your job title, and only asks Claude for the matching jobs on a page.

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

## Start the services

The CLI is a thin client of four local services — start them first, in separate terminals
(or run `docker compose up --build`):

```bash
uv run --env-file .env uvicorn jobassist.Microservices.web_scraper.api:app --port 8001
uv run --env-file .env uvicorn jobassist.Microservices.data_cleaner.api:app --port 8002
uv run --env-file .env uvicorn jobassist.Microservices.job_recommender.api:app --port 8003
uv run --env-file .env uvicorn jobassist.Microservices.cv_feedback_provider.api:app --port 8004
```

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

# Search every employer in your own Excel list (needs a "Company" column)
uv run --env-file .env jobassist search "Data Analyst" full-time \
  --location UK --employers Target_Employers.xlsx --resume resume.txt -n 100

# ...only the rows starred "Y" in the "My star" column, or only some buckets
uv run --env-file .env jobassist search "Data Analyst" full-time \
  --employers Target_Employers.xlsx --starred --resume resume.txt
uv run --env-file .env jobassist search "ML Engineer" full-time \
  --employers Target_Employers.xlsx --bucket "AI startups" --resume resume.txt

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
| `--employers`, `-e` | none | Excel employer list (`.xlsx`) — search those employers |
| `--starred` | off | With `--employers`: only rows marked `Y` in `My star` |
| `--bucket`, `-b` | all | With `--employers`: only this `Bucket` (repeatable) |
| `--max-results`, `-n` | 50 | Max postings to score in total, shared fairly across companies |
| `--resume`, `-r` | `$JOBASSIST_RESUME` | Path to your resume (plain text) |
| `--report` | none | Write a Markdown report to this path |
| `--aliases/--no-aliases` | on | Expand role to synonyms before searching |
| `--one-per-company/--all-per-company` | on | Show only best-scoring role per company |
| `--db` | `~/.jobassist/data.db` | SQLite store path |
| `--company-sites` | off | Also search each named company's own careers website |
| `--refresh` | off | Ignore results saved in the last 24 hours and search again |
| `--budget` | 5.0 | Claude spending limit for this search, in US dollars |

## Sources

| Source | Type | Auth required | Coverage |
|---|---|---|---|
| Greenhouse | ATS direct | None | Broad UK/global tech |
| Lever | ATS direct | None | Broad UK/global tech |
| Ashby | ATS direct | None | UK/US startups |
| SmartRecruiters | ATS direct | None | Mid-market enterprise |
| Workable | ATS direct | None | UK SMEs and consultancies |
| Teamtailor | ATS direct | API token | European startups |
| Adzuna | Aggregator | App ID + Key (free) | UK broad market |
| Reed | Aggregator | API key (free) | UK broad market |

ATS-direct sources are always preferred over aggregator copies when the same job appears in both.

## Targeting named employers

When companies are given (`--company`, `--index` or `--employers`), each one is searched
directly rather than via a broad keyword search:

1. **Careers page link** — if your sheet's `Careers page link` column points at an ATS
   board (`jobs.lever.co/…`, `boards.greenhouse.io/…`, `jobs.ashbyhq.com/…`,
   `careers.smartrecruiters.com/…`, `apply.workable.com/…`), that board is used.
2. **Known boards** — ~40 UK employers whose public boards were verified against the live
   APIs (Monzo, Palantir, Spotify, Wise, ASOS, Faculty, ElevenLabs, Wayve, i.AI, AISI, …).
   See `web_scraper/employers/registry.py`.
3. **Adzuna fallback** — everyone else (big-tech portals, banks, consultancies, public
   sector) is searched on Adzuna filtered to that employer.
4. **Company website** (`--company-sites`, on by default in the web page) — for the same
   employers, the careers page is found by Claude with web search (or taken from the
   sheet), fetched (in a headless browser when it needs JavaScript; `robots.txt` is
   respected), and its jobs extracted by Claude. If the site turns out to use a known ATS,
   that board's JSON feed is used instead. Calls are paced ~3s apart to
   stay inside Adzuna's free-tier rate limit, so a 100-employer list takes ~5 minutes and
   uses ~100 of the free tier's daily calls; `--starred` keeps it to your top 20.

Board slugs are never guessed from names — guessed slugs often hit an unrelated company.
ATS boards are global, so their postings are filtered by `--location` (`UK` keeps anything
in the UK; `London` keeps London only).

## Development

```bash
uv run pytest                    # run all 457 tests
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
