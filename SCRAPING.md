# Running the scrapers

WorkVista's job listings come from six scrapers, each a Django
management command. This covers how to run each one and the current
state of each source. All six use plain HTTP and need no browser.

## 1. Prerequisites

```bash
cd /Users/syed/workvista
source venv311/bin/activate   # the project's venv
brew services start mysql     # if not already running
```

That's it for all six scrapers — they use plain HTTP or a public API.

## 2. Running a scraper

Each is a normal `manage.py` command:

```bash
python manage.py scrape_python       # python.org — fast, no browser window
python manage.py scrape_njp          # njp.gov.pk — fast, no browser window
python manage.py scrape_ppsc         # ppsc.gop.pk — fast, no browser window
python manage.py scrape_mustakbil    # mustakbil.com — fast, no browser window
python manage.py scrape_remoteok     # remoteok.com — public API, no browser window
python manage.py scrape_brightspyre  # current jobs only; skips expired deadlines
```

`scrape_python` finishes in a few seconds. `scrape_njp` takes a couple
of minutes for ~60 jobs — it deliberately pauses 1.5s between requests
rather than hammering a government service. Two flags worth knowing:

```bash
python manage.py scrape_njp --max-pages 5   # how many listing pages to walk
python manage.py scrape_njp --skip-details  # skip per-job description fetches
```

`--skip-details` cuts the run to a handful of requests, at the cost of
saving the jobs without their description.

`scrape_ppsc` is a single request — it finishes instantly.
`scrape_mustakbil` takes one request per posting:

```bash
python manage.py scrape_mustakbil --limit 60   # how many recent postings (default 60)
```
**From the app itself**, without touching a terminal: sign in as an
Admin or Super Admin → **Manage Scraper** → click *Run* next to the
source you want. This calls the same command via
`django.core.management.call_command` (`jobs/views.py::run_scraper`).

## 3. What actually works right now

| Source | Status | Notes |
|---|---|---|
| `scrape_njp` | ✅ Works reliably | National Job Portal (njp.gov.pk) — live federal/provincial government vacancies. Server-rendered HTML, no browser needed. `robots.txt` is `Disallow:` (everything permitted). Mostly public-sector administrative posts, so it fills the Administration & Government category. Parsing is pinned by tests against saved real pages (`jobs/tests_data/`, `jobs/tests.py::NjpParsingTests`) so markup changes fail loudly instead of silently returning 0. |
| `scrape_python` | ✅ Works reliably | No anti-bot friction, plain HTTP requests. Technology jobs only — that's genuinely all python.org lists. |
| `scrape_mustakbil` | ✅ Works | Rewritten — no browser. Reads the sitemap Mustakbil advertises in its own robots.txt (newest first, via `<lastmod>`) and then each posting's schema.org `JobPosting` JSON-LD, which even carries a numeric salary range the old card-scraping never got. Covers Mustakbil's regional sites (`pk.`/`in.`/`qa.`) as the sitemap lists them. |
| `scrape_ppsc` | ✅ Works reliably | Punjab Public Service Commission. One request, one HTML table, ~23 live advertisements. No per-job URLs exist (the POST NAME cells are ASP.NET `__doPostBack` handlers), so the unique CASE NO keys the upsert. |
| `scrape_remoteok` | ✅ Works | Remote OK public jobs API. Saves the existing WorkVista job fields and links each listing to its Remote OK posting; runs without a browser. |
| `scrape_brightspyre` | ✅ Works | Reads all paginated public job listings. Skips postings with a passed or missing application deadline. |

**Glassdoor was removed.** It was blocked by Cloudflare's bot check,
and working around that means circumventing an access control on a site
we don't operate — which also breaks again on every update. The effort
belongs on sources that permit automated access instead.

**How to add a source, in preference order.** Check `robots.txt` first.
Then look for, in order: a published feed or API (Remote OK is an example);
schema.org JSON-LD on
the posting pages (`JobPosting` — this is what Mustakbil gives us, and
it is a standard, so it survives redesigns); a sitemap; and only then
server-rendered HTML with CSS selectors. Reach for Selenium last — all
six current scrapers run without a browser.

**Whatever you use, pin the parsing with a fixture.** Save a real page
into `jobs/tests_data/`, keep the parse step a pure function, and test
it. The old Mustakbil scraper silently returned 0 results for every
query for months because nothing failed when its selectors went
stale — it just quietly found nothing.

## 4. After scraping: categories

New jobs get auto-categorized at save time — see `TRENDING.md` §4.
The keyword rules cover both broad fields (Healthcare, Finance, HR) and
the narrower software ones (AI & Machine Learning, Web, Mobile, Data,
DevOps), plus Administration & Government for public-sector posts.

**Order is what makes it work.** `categorize_job()` takes the *first*
match, so the list runs narrowest-first: `ai` before `research` (or
"Deep Learning Researcher" files as research), `mobile` before `web`
(or "React Native Developer" is caught by web's `react`), the whole
software block before the general `technology` bucket, and
`administration` dead last (its `manager`/`officer`/`assistant` terms
would otherwise swallow "Marketing Manager"). Add keywords with that in
mind, and add a case to `jobs/tests.py::CategorizeJobTests`. If you ever change the keyword
rules in `jobs/recommender/categorize.py`, recompute existing jobs'
categories with:

```bash
python manage.py backfill_categories
```

## 5. Automatic refresh

You don't have to run any of this by hand. WorkVista re-scrapes stale
sources in the background, triggered by ordinary web traffic — there is
no worker process or task queue to keep running, which is what makes it
work on a laptop and on a plain host alike.

**How it works** (`jobs/refresh.py`). A middleware asks, at most once
every few minutes per process, whether the shared
`JOB_REFRESH_INTERVAL_HOURS` cooldown (default 24) has elapsed since the
last automatic batch. If so, it starts one background batch containing
all six scrapers; the visitor's page is never held up. The cooldown
starts after the whole batch finishes, even if a scraper failed or was
blocked. The next run time is reserved before scraping starts, so an
interrupted batch cannot be retried automatically sooner than 24 hours;
after a normal finish, the next batch is due 24 hours after completion.
Admin and Super Admin can still manually run an individual scraper at
any time; manual runs do not split or move the automatic all-scraper
batch schedule.

Three things keep it safe:

- **One at a time.** `ScrapeLock` is a single row claimed with a
  conditional `UPDATE`, which the database settles atomically, so two
  web workers deciding "a refresh is due" in the same instant can't both
  start one.
- **A crash can't wedge it.** The lock carries an expiry rather than a
  boolean, so a killed process frees it after `LOCK_TTL` (45 min).
- **It can't break a page.** Every call the middleware makes is wrapped;
  a failure is invisible to the visitor and recorded in `ScrapeRun`.

**Seeing what happened.** Every attempt writes a `ScrapeRun` row — source,
status, duration, how many new jobs, and the error if it failed. The
admin and super admin dashboards show each scraper's last run next to its
Run button, so a source that has quietly started failing is visible
rather than silent. That was the failure mode of the old Mustakbil
scraper: broken for months, and nothing ever said so.

**Running it yourself:**

```bash
python manage.py refresh_jobs                      # anything stale
python manage.py refresh_jobs --force              # ignore the interval
python manage.py refresh_jobs --sources njp,ppsc   # just these
```

**Driving it from a scheduler.** Schedule the command to check every
minute. It only starts the complete scraper batch when the shared
24-hour cooldown has elapsed, so the check frequency does not make
scrapes run more often. Both the scheduler and traffic trigger take the
same lock:

```cron
* * * * *  cd /path/to/workvista && venv311/bin/python manage.py refresh_jobs
```

On Windows, create a Task Scheduler task to run
`<venv>\Scripts\python.exe` with arguments
`manage.py refresh_jobs`, set **Start in** to the project directory, and
repeat the task every minute indefinitely. It must have the same
environment variables and database access as the web app. A task
configured to run only while the user is logged on will not run after
that user logs off; on a server, configure it to run unattended under
an account with the required project and database access. For Linux,
install the cron entry on the deployed server. A minute-based scheduler
starts a due refresh on its next check (within about a minute); no
application can guarantee an exact wall-clock start if its server or
scheduler is stopped.

The scheduler is an operating-system/hosting setting, not something
that is installed by deploying Django. Configure it on each machine
where the app runs. Without it, the web-traffic trigger is only a
fallback and waits for a page request.

The trigger is switched off automatically while the test suite runs —
otherwise every test that fetches a page would scrape four live sites.

## 6. Deduplication

All five scrapers key on `job_link` (`Job.objects.update_or_create(job_link=...)`)
— re-scraping a posting you already have updates it in place rather
than creating a duplicate.
doesn't affect correctness of trending/recommendations — see
`TRENDING.md` §5 for how duplicate postings are deduped for display.
