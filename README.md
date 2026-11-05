# JobAssist AI

JobAssist finds jobs that fit your CV. You give it a job title and (optionally) a list of
employers; it searches job sites, employers' own job boards and company careers websites,
removes duplicates, and uses Claude to score every job against your CV and explain why it
fits. It runs on your own computer — your CV and results stay there. Built for UK job
hunting.

## What it does

1. **Searches** Adzuna and Reed (UK job sites), employers' public job boards (Greenhouse,
   Lever, Ashby, SmartRecruiters, Workable, Teamtailor) and companies' own careers websites
   — for your job title plus similar titles with overlapping skills.
2. **Targets your employers** from an Excel list (or one you type in), with stars and groups.
3. **Removes duplicates**, preferring the copy straight from the employer.
4. **Scores** each job against your CV with Claude and explains the score.
5. **Shows** ranked results in a web page (or the terminal), with spreadsheet and report
   downloads, under spending limits you set.

## Install

### What you need

- A Mac (macOS 12+) or a Windows 10/11 PC, with internet.
- An **Anthropic API key** — create one at <https://console.anthropic.com> and add a few
  dollars of credit. JobAssist uses it to read job pages and score jobs (see
  [Cost and spending limits](#cost-and-spending-limits)).
- Optional but recommended, both free: **Adzuna** keys (<https://developer.adzuna.com>)
  and a **Reed** key (<https://www.reed.co.uk/developers>) for many more listings.

You don't need to install Python or anything else yourself — JobAssist sets itself up the
first time it runs.

### Option 1 — the download (Mac or Windows, no coding)

1. Download **`JobAssist.zip`** from the
   [latest release](https://github.com/Mc54322/Job-Hunt-Agent/releases/latest) (under
   **Assets**) and **unzip it**. Keep everything in the `JobAssist` folder together.

   > GitHub's green **Code → Download ZIP** button gives you the source code only, without
   > the programs below — use the release download instead.
2. Double-click the program for your computer inside that folder:
   - **Windows:** `JobAssist for Windows.exe`
   - **Mac:** `JobAssist for Mac`
3. The first time, your computer may warn you because JobAssist isn't from an app store:
   - **Windows** — on "Windows protected your PC", click **More info**, then **Run anyway**.
   - **Mac** — if it says it can't be opened, right-click (or Control-click) it, choose
     **Open**, then **Open** again. Or: System Settings → Privacy & Security → **Open Anyway**.
4. **First run only:** a window asks for your Anthropic key (and the optional Adzuna/Reed
   keys) and saves them in a `.env` file in the folder. It then spends a few minutes
   installing what JobAssist needs: a small tool called `uv`, the app's components, and a
   browser used to read company websites.
5. Your web browser opens JobAssist at **<http://localhost:8000>**. Keep the JobAssist window
   open while you use it; close it to stop JobAssist.

After the first time it starts in a few seconds. If you double-click it while it's already
running, it just opens the page again. The folder also contains a plain-English
`READ ME FIRST.txt`.

### Option 2 — from GitHub on a Mac

```bash
git clone https://github.com/Mc54322/Job-Hunt-Agent.git
```

Then, in Finder, open the `Job-Hunt-Agent` folder and **double-click
`Start JobAssist.command`** (if macOS won't open it: right-click → **Open** → **Open**). It
does the same first-run setup as the download and opens <http://localhost:8000>. On
Windows, use Option 1 (or the developer setup below).

### Option 3 — developer setup

See [For developers](#for-developers).

### Uninstall

Delete the JobAssist folder, and the `.jobassist` folder in your home folder (saved
results, scores and logs).

## Using JobAssist

On the page at <http://localhost:8000>:

1. **Your CV** — choose your CV (PDF, Word or text). It's remembered for next time.
2. **What job** — job title, type, and where (e.g. `UK` or `London`). Under the title,
   **Also search for** lists similar titles with overlapping skills (e.g. for "AI
   Engineer": Machine Learning Engineer, Data Scientist, Applied Scientist…). Untick any, or
   add your own. Each title is looked up once (about $0.002) and saved permanently.
3. **Where to look** — your Excel employer list (tick "Only my starred employers" or pick
   groups), or all job sites. Leave **"Also search each company's own website"** on to have
   JobAssist read each employer's careers site too.
4. Press **Find jobs**. A progress bar shows what it's doing and what it has spent; you can
   leave the page and come back. **Stop searching & score what's found** ends the search at
   once and scores the jobs found so far; pressing it again during scoring stops the
   scoring.
5. Results are ranked by how well they match your CV — press **Why?** for the reasoning,
   **Download spreadsheet** to open them in Excel, and expand **"What was searched at each
   employer"** to see where JobAssist looked and what each employer cost. Jobs that weren't
   scored (after a Stop or a limit) are still listed as "Not scored".
6. **Saved jobs** (bottom of the page) lists every job found in earlier searches, with match
   scores already worked out for your current CV — instant and free. Filter it, or
   download it as a spreadsheet.

### Your employer list

JobAssist reads an Excel sheet with a **Company** column. It also uses, if present:
**Bucket** (groups), **My star (Y)** (starred employers) and **Careers page link** (a link
to an employer's job board or careers page — set it yourself to point JobAssist at the
right page).

**No list yet?** Use **Make an employer list** at the bottom of the page (free — no
Claude). Write one company per line; a line ending with `:` starts a group; `Y` or `*` stars
a company; a link after a name fills its careers page:

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

Then **Download Excel file** (the employer-tracking spreadsheet: How to use, Employers with
stars/status/contacts columns and dropdowns, and a Summary tab), or **Use this list for my
search**. From a terminal: `uv run jobassist-make-list my-companies.txt --university Leeds`
(add `--example` to see the format).

### Saved results

Every search is saved for 24 hours, so running the same search again is almost instant and
free. To force a fresh search, open **More options** and tick **"Search again from
scratch"**. Each company's careers-page address is remembered for 30 days, and similar job
titles permanently.

### Cost and spending limits

Claude is used to find careers pages, read company websites and score jobs against your
CV. Before you start, the page shows an estimate next to **Find jobs**. Limits (under
**More options**):

- **Per search:** $5 by default, **$2 when searching only your starred employers**.
- **Per employer: a hard cap of $0.20.** An employer whose website would cost more is
  skipped and flagged.
- **Per website: 60 seconds.** A slow site is skipped rather than waited on.

When a limit is reached, or your Anthropic credit runs out, JobAssist stops using Claude,
keeps everything found and says why. Costs shown are JobAssist's estimates from published
prices — your Anthropic console is the official record.

To keep costs down, JobAssist asks Claude for each careers page from memory, checks it with
a free fetch, and otherwise follows the "Careers" link on the company's homepage. Web search
is **off** by default ("Deep search" in More options): in testing it cost $0.10–$0.80 per
employer and rarely found more, so it only runs if you raise the per-employer cap to at
least $0.40. JobAssist also skips any website that never mentions your job title, and only
asks Claude for the matching jobs on a page.

## Sharing JobAssist with others

Build a download anyone can use (run on a Mac):

```bash
bash packaging/build.sh
```

This makes `dist/JobAssist.zip` (about 8 MB) — attach it to a
[GitHub release](https://github.com/Mc54322/Job-Hunt-Agent/releases) so others can
download it (`gh release create vX.Y.Z dist/JobAssist.zip`). It contains **JobAssist for Windows.exe**,
**JobAssist for Mac** (Apple Silicon and Intel), **READ ME FIRST.txt**, **Example employer
list.txt**, the app's source and this README. Each person enters their own API keys on
first run (saved only in their own copy's `.env`).

Personal files are never included: the folder is built from an explicit list, and the build
refuses to finish if it finds a `.env`, CV, spreadsheet, database or API key. The Go
compiler is downloaded into `packaging/.toolchain/` (checksum-verified) the first time, so
nothing needs installing. The launcher's source is in `packaging/launcher/`.

The programs aren't code-signed, so first-time users see the warnings described in
[Option 1](#option-1--the-download-mac-or-windows-no-coding). The Windows build is
cross-compiled from macOS and hasn't yet been tested on a Windows PC.

## For developers

### Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Mc54322/Job-Hunt-Agent.git
cd Job-Hunt-Agent
uv sync
uv run playwright install chromium   # browser for JavaScript careers sites
cp .env.example .env
```

Edit `.env` and fill in your keys:

```
ANTHROPIC_API_KEY=sk-ant-...
ADZUNA_APP_ID=...            # free at developer.adzuna.com
ADZUNA_APP_KEY=...
REED_API_KEY=...             # free at reed.co.uk/developers
```

### Start the services

JobAssist is six small services. `Start JobAssist.command` (Mac) or the packaged launchers
start them all; to run them by hand, use one terminal each (or `docker compose up --build`):

```bash
uv run --env-file .env uvicorn jobassist.Microservices.job_recommender.api:app --port 8003
uv run --env-file .env uvicorn jobassist.Microservices.web_scraper.api:app --port 8001
uv run --env-file .env uvicorn jobassist.Microservices.data_cleaner.api:app --port 8002
uv run --env-file .env uvicorn jobassist.Microservices.cv_feedback_provider.api:app --port 8004
uv run --env-file .env uvicorn jobassist.Microservices.list_builder.api:app --port 8005
uv run --env-file .env uvicorn jobassist.Microservices.frontend.api:app --port 8000
```

The web page is then at <http://localhost:8000>. Saved data lives in
`~/.jobassist/data.db` (override with `JOBASSIST_DB`); logs from the launchers go to
`~/.jobassist/logs/`.

### Command line

With the services running, the CLI is an alternative to the web page (your resume must be
a plain-text file):

```bash
# Basic search — Adzuna + Reed, scored against your resume
uv run --env-file .env jobassist search "Software Engineer" full-time \
  --location "London, UK" --resume resume.txt

# Target specific companies
uv run --env-file .env jobassist search "Data Analyst" full-time \
  -c DeepMind -c Palantir --resume resume.txt

# Search every employer in your Excel list, including their own websites
uv run --env-file .env jobassist search "Data Analyst" full-time \
  --location UK --employers Target_Employers.xlsx --company-sites --resume resume.txt -n 100

# ...only the rows starred "Y" in "My star" ($2 limit by default), or only some buckets
uv run --env-file .env jobassist search "Data Analyst" full-time \
  --employers Target_Employers.xlsx --starred --resume resume.txt
uv run --env-file .env jobassist search "ML Engineer" full-time \
  --employers Target_Employers.xlsx --bucket "AI startups" --resume resume.txt

# Search across all FTSE 100 companies
uv run --env-file .env jobassist search "Software Engineer" full-time \
  --index ftse100 --resume resume.txt

# Export a Markdown report; show every matching role per company
uv run --env-file .env jobassist search "Engineer" full-time \
  --resume resume.txt --report results.md --all-per-company
```

| Flag | Default | Description |
|---|---|---|
| `--location`, `-l` | none | Geographic filter, e.g. `"London, UK"` or `UK` |
| `--company`, `-c` | none | Target a specific company (repeatable) |
| `--index` | none | Expand companies from `ftse100` or `aim100` |
| `--employers`, `-e` | none | Excel employer list (`.xlsx`) — search those employers |
| `--starred` | off | With `--employers`: only rows marked `Y` in `My star` |
| `--bucket`, `-b` | all | With `--employers`: only this `Bucket` (repeatable) |
| `--company-sites/--no-company-sites` | off | Also search each named company's own careers website |
| `--max-results`, `-n` | 50 | Max postings to score in total, shared fairly across companies |
| `--resume`, `-r` | `$JOBASSIST_RESUME` | Path to your resume (plain text) |
| `--report` | none | Write a Markdown report to this path |
| `--aliases/--no-aliases` | on | Also search similar job titles (looked up once, saved) |
| `--one-per-company/--all-per-company` | on | Show only the best-scoring role per company |
| `--refresh` | off | Ignore results saved in the last 24 hours and search again |
| `--budget` | 5.0 (2.0 with `--starred`) | Claude spending limit for this search, in US dollars |
| `--deep-search` | off | Use web search for careers pages Claude can't find (needs a per-employer limit ≥ $0.40) |

### Tests and checks

```bash
uv run pytest                    # run all 479 tests (offline: HTTP and Claude are mocked)
uv run ruff check .              # lint
uv run mypy jobassist/           # type-check (strict)
```

## Sources

| Source | Type | Auth required | Coverage |
|---|---|---|---|
| Greenhouse | Employer job board | None | Broad UK/global tech |
| Lever | Employer job board | None | Broad UK/global tech |
| Ashby | Employer job board | None | UK/US startups |
| SmartRecruiters | Employer job board | None | Mid-market enterprise |
| Workable | Employer job board | None | UK SMEs and consultancies |
| Teamtailor | Employer job board | API token | European startups |
| Company websites | Careers pages, read by Claude | Anthropic key | Any employer with a readable careers page |
| Adzuna | Job site | App ID + Key (free) | UK broad market |
| Reed | Job site | API key (free) | UK broad market |

Postings straight from an employer are preferred over job-site copies when the same job
appears in both.

## Targeting named employers

When companies are given (an employer list, `--company` or `--index`), each one is
searched directly rather than via a broad keyword search:

1. **Careers page link** — if the sheet's `Careers page link` points at a job board
   (`jobs.lever.co/…`, `boards.greenhouse.io/…`, `jobs.ashbyhq.com/…`,
   `careers.smartrecruiters.com/…`, `apply.workable.com/…`), that board is used.
2. **Known boards** — ~40 UK employers whose public boards were verified against the live
   APIs (Monzo, Palantir, Spotify, Wise, ASOS, Faculty, ElevenLabs, Wayve, i.AI, AISI, …).
   See `web_scraper/employers/registry.py`.
3. **Adzuna** — every other employer is searched on Adzuna, filtered to that employer, for
   your title and its top two similar titles. Calls are paced ~3 s apart to stay inside
   Adzuna's free-tier rate limit, so a 100-employer list takes several minutes;
   `--starred` keeps it to your top employers.
4. **Company website** (on by default in the web page; `--company-sites` on the CLI) — the
   careers page comes from the sheet, or Claude names it and a free fetch checks it, or the
   homepage's "Careers" link is followed. The page is fetched (in a headless browser when
   its job list loads by script; `robots.txt` is respected) and Claude extracts the
   matching jobs. If the site turns out to use a known job board, that board's feed is
   used instead.

Board slugs are never guessed from names — guessed slugs often hit an unrelated company.
Job boards are global, so their postings are filtered by location (`UK` keeps anything in
the UK; `London` keeps London only).

Some sites can't be read: Civil Service Jobs (ONS, HMRC and other departments) returns an
almost empty page to automated tools, some employers block them, and a few ask tools not to
visit in `robots.txt` (which JobAssist respects). Those employers are still searched via
Adzuna.

## Project structure

```
Start JobAssist.command        # Mac launcher (starts everything, opens the page)
packaging/                     # build.sh, Go launcher source, READ ME FIRST, example list
jobassist/Microservices/
  frontend/                    # web page (static/index.html) + proxy to the services   :8000
  web_scraper/                 # finding jobs                                            :8001
    sources/ats/                 # Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Teamtailor
    sources/aggregators/         # Adzuna, Reed
    sources/company_pages/       # careers-page finder, site reader, Claude extractor
    employers/registry.py        # verified employer job boards; careers-link parsing
    orchestration/               # per-employer search, Stop, time limits
    query_expansion/             # similar job titles; FTSE 100 / AIM 100 lists
    caching/ costs/ filtering/ politeness/   # saved results, spending meter, location, robots.txt
  data_cleaner/                # de-duplication, salary normalising, applicant volume    :8002
  job_recommender/             # runs the pipeline; scoring; SQLite store; CLI           :8003
    orchestration/               # pipeline, CLI, Excel and CV readers
    scoring/ ranking/ reporting/ persistence/ costs/
  cv_feedback_provider/        # cover letter + CV bullet drafts (facts-only)            :8004
  list_builder/                # text list → employer-tracking spreadsheet               :8005
tests/                         # 30 test files; fixtures/ holds captured API responses
```

## Design decisions

- **No LinkedIn, no Indeed scraping** — LinkedIn's Jobs API is closed to new partners;
  Indeed's Publisher API is deprecated. Both violate their terms if scraped. Coverage loss
  is small because companies cross-post to their own job boards.
- **Claude calls are cached** — keyed by content and stored in SQLite, so the same page,
  title or job is never paid for twice; search results are reused for 24 hours.
- **Spending is capped** — every Claude call goes through a meter that enforces the
  per-search and per-employer limits and records the cost from Anthropic's reported usage.
- **CV sent once per run** — the CV goes into the system prompt with prompt caching, so
  scoring each job re-reads it from the cache.
- **Employer data beats job-site copies** — if the same job is on Greenhouse and Adzuna, the
  Greenhouse copy is kept: richer data, and it links straight to the apply page.
- **Polite fetching** — 1 request/second per job board with jitter, a real User-Agent,
  and `robots.txt` respected for company websites.
