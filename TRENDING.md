# How WorkVista finds and ranks jobs

This covers two separate things that are easy to conflate:

1. **How "all jobs" get into the database at all** — the scrapers.
2. **How "Trending Jobs" picks which of those jobs to show, and in
   what order** — the ranking formula.

It also covers the filters available on the Trending Jobs and Search
Jobs pages.

## 1. Where jobs come from

Every `Job` row is written by one of four scrapers, each a Django
management command under `jobs/management/commands/`:

| Command             | Source          | Technique                          |
|----------------------|-----------------|-------------------------------------|
| `scrape_python`       | python.org/jobs | `requests` + BeautifulSoup (static HTML) |
| `scrape_indeed`       | Indeed          | Selenium (renders JS, drives a real browser) |
| `scrape_glassdoor`    | Glassdoor       | Selenium |
| `scrape_mustakbil`    | Mustakbil       | Selenium |

Run one directly:

```bash
python manage.py scrape_python
```

Or trigger any of them from the app itself: **Super Admin → Manage
Scraper** (or **Admin → Manage Scraper**) has a *Run* button per
source, which calls the same management command via
`django.core.management.call_command` from `views.run_scraper`.

Every scraper ends the same way regardless of source: it calls

```python
Job.objects.update_or_create(job_link=..., defaults={...})
```

`job_link` is the dedupe key. Scraping the same posting twice
**updates** the existing row (so title/salary/location edits on the
source site get picked up) rather than creating a duplicate. This
matters for the next section: it's *why* `scraped_at` can't be used
to answer "how old is this posting."

The `scrape_python` scraper (plain `requests`, no browser) is the
most reliable — no anti-bot friction, verified working live while
building this feature (pulled 30 real current listings in one run).
The three Selenium-based scrapers open a real Chrome window (via
Selenium 4's built-in driver manager, no separate chromedriver
install needed) and are inherently more fragile: they depend on the
target site's current HTML structure and can be slowed or blocked by
anti-scraping measures. If one stops returning jobs, that's the
first thing to check — the site likely changed its markup.

## 2. Two different timestamps, two different jobs

`Job` has both:

- **`scraped_at`** (`auto_now=True`) — updates *every time the row is
  saved*, including a routine re-scrape of a posting we already had.
  This answers "when did we last confirm this posting still exists,"
  not "when was it posted."
- **`first_seen_at`** (`auto_now_add=True`) — set once, the first
  time this `job_link` is ever saved, and never touched again.

Every "how old is this job" decision in the app — trending's recency
score, and the 24h/week/month filters — is based on **`first_seen_at`**,
never `scraped_at`, and never the free-text `posted` field the
scrapers also save (its format isn't consistent enough to parse
reliably: `"3 days ago"` from one source, `"02 July 2026"` from
another).

## 3. The trending formula

Code: `jobs/recommender/trending.py`, function `compute_trending_jobs()`.

We don't have page-view or click analytics, so "trending" is built
from the three signals that actually exist in the database:

1. **Recency** — how long ago `first_seen_at` was.
2. **Demand** — how many *other* currently-open postings (within the
   last 30 days) share the same normalized job title. Ten companies
   all posting "Backend Developer" this month is a real market
   signal, independent of any one posting.
3. **Engagement** — how many users have saved that specific job
   (`SavedJob`). This is genuine user behavior, not a proxy, so it's
   weighted the highest of the three.

These combine into a single score per job:

```
score = (1 + 5·ln(1 + saves) + 2·ln(1 + similar_postings)) / (age_hours + 2)^1.5
```

This is the **Hacker News / Reddit "hot" ranking formula**
(`score / (age + 2)^gravity`), adapted for a job board:

- HN's raw upvote count is replaced with the weighted blend of saves
  and similar-posting count described above.
- Both signal counts are passed through `log1p` (`ln(1+x)`) before
  being weighted, so one outlier — a job saved 200 times, or a
  generic title like "Software Engineer" that naturally clusters with
  many others — can't single-handedly dominate the ranking. Going
  from 1 save to 2 matters a lot more than going from 50 to 51.
- The `+ 1` in the numerator means a brand-new posting with zero
  saves and no duplicates yet still gets a real score, purely from
  recency — so the trending list isn't empty just because engagement
  hasn't accumulated yet.
- **Gravity = 1.5** (HN itself uses 1.8). Job postings stay live for
  weeks, not hours, so decay is gentler than a news feed's — a HN-speed
  decay would empty the trending list every few hours.

Why this formula and not something simpler (e.g. "just sort by
newest")? Pure recency ignores real demand signals entirely — a job
nobody's interested in would rank identically to one ten people just
saved. Pure popularity (sort by saves) would let old, stale postings
that accumulated saves months ago permanently bury today's openings.
The HN formula is a well-known, battle-tested answer to exactly this
tension, which is why it was chosen over inventing something bespoke.

The top 5 jobs by this score get the animated **"#N trending"** badge
on their card, on both the Trending Jobs page and the dashboard's
trending section.

`compute_trending_jobs()` is the single source of truth — it's used
by both the standalone Trending Jobs page (`views.trending_jobs`) and
the trending section of the logged-in user dashboard
(`views.user_dashboard`), so the two never disagree with each other.

## 4. Categories

Code: `jobs/recommender/categorize.py`.

Every job gets a `category` (Technology, Marketing, Sales, HR,
Customer Service, Finance & Accounting, Design, Education,
Healthcare, Logistics, or Other) assigned automatically at scrape
time, by keyword-matching its title against `CATEGORY_KEYWORDS` (falls
back to matching against `skills` if the title itself doesn't match
anything). There's no per-source category field to trust - each of
the four scraper sites structures its own listings differently - so
title keyword matching is the one signal that's reliably present and
consistent no matter which scraper produced the job.

To recompute every job's category after editing the keyword list (or
for jobs that existed before this field was added), run:

```bash
python manage.py backfill_categories
```

`compute_trending_jobs()` and `top_job_per_category()` (used by the
homepage's "Trending by category" section) both key off this field,
and `available_categories()` powers the category filter dropdown on
Trending Jobs / Search Jobs, showing only categories that currently
have at least one job.

Worth knowing: as of writing, `scrape_python` (python.org) only ever
produces Technology jobs - that's genuinely all that source lists.
Category diversity in the database depends on running the other
scrapers against sources that list general jobs. `scrape_indeed`
verified this works well (one live run pulled admin, customer
service and healthcare listings alongside tech ones); `scrape_mustakbil`
returned zero results on the same test run, which most likely means
Mustakbil changed their page structure since that scraper was written
and its CSS selectors need updating - not something to assume is
still broken without checking again.

## 5. Recommended for you

Code: `jobs/recommender/recommend.py`, function `get_recommended_jobs()`.
Shown on the dashboard's "Recommended Jobs" tab and as a sidebar card
on every job detail page.

Trending is deliberately *not* personalized - Recommended is. It's
built from a **personalization score** (four optional signals) plus
a **trending tiebreaker** - and those two are combined differently
than they might look at first:

1. **CV / profile skill match** (40%) - `skill_match_score()` against
   the union of `Profile.skills` and `CVData.skills`.
2. **Explicit preferences** (15%) - title/location/job-type match
   against `Profile.job_title` / `.location` / `.job_type` (a list -
   a user can prefer more than one job type), whichever of those the
   user has actually set.
3. **CV field match** (20%) - `infer_user_category()` (the same
   function that defaults Trending's category filter - see §6) looks
   at the user's preferred title, most recent CV experience title,
   skills, then education degree, and scores 100 if a job's category
   matches whatever field that implies. This is what lets a "BS
   Computer Science" education entry or a past job title pull
   relevant jobs up even before the user has explicitly listed
   skills or browsed anything.
4. **Behavioral category affinity** (25%) - which job *categories*
   the user has actually viewed or searched most, recency-weighted
   with a 14-day half-life over a 60-day window (`UserActivity`,
   logged from `job_detail` on every view and from `search_jobs` /
   the dashboard's search on every query). A view counts double a
   search, since actually opening a job is a stronger signal than a
   query that may not have returned what they wanted.
5. **Trending score** - normalized against the site-wide max, used
   purely as a **tiebreaker**, not summed in as a fourth weighted
   term. The sort key is `(personalization_score, trending_norm)`:
   any job with real personalization signal outranks every job with
   none, full stop, and trending only decides ordering *within* a tie
   on personalization. This was a deliberate fix, not the original
   design - with a modest-sized dataset, many jobs get scraped in the
   same batch and end up with near-identical trending scores; treating
   trending as a same-scale additive term let a handful of completely
   unrelated fresh postings (an office admin role, say) creep up
   almost as high as a genuine skill match for a Python developer,
   which read as "recommendations don't reflect my CV" even though
   the matched jobs were still nominally ranked first. Making
   trending a strict tiebreaker instead of a peer signal fixed that.

Each of the four personalization signals is 0 when its underlying
data doesn't exist yet (no CV, no preferences set, no browsing
history), so a brand-new user isn't stuck with an empty list - with
personalization at 0 for every job, the tiebreaker alone decides,
which is exactly `compute_trending_jobs()`'s own order. As they
browse, save, and fill in preferences, the personalization score
takes over and the list becomes genuinely theirs. This directly
answers "by default recommendations follow preferences, and improve
further as preferences/activity build up" - there's no separate
"default mode"; it's one scoring path that naturally has more to work
with over time.

Duplicate postings (see §1 - the same real listing can exist as more
than one `Job` row when a source's link changes between scrapes) are
collapsed by `(title, company)` before display, and a job's own
near-duplicates are excluded from its own "Recommended for you" card
so a posting never recommends itself.

**On the job detail page**, "Recommended for you" and "More in
[category]" are mutually exclusive by design: a signed-in user sees
personalized recommendations; a logged-out visitor (who has no
profile to personalize against) sees same-category listings instead.
The `similar_jobs` query in `views.py::job_detail` doesn't even run
for a signed-in user, since its result would never be shown.

**A note on data size**: the tiebreaker fix stops irrelevant jobs
from crowding in *ahead of* genuine matches, but it can't invent
matches that don't exist. If the database only has three
Python-developer-titled postings, "Recommended for you" will still
fill its remaining slots with the next-best (or, failing that,
zero-signal fallback) jobs available - that's a dataset size
question, not a ranking bug. Running the working scrapers again (see
`SCRAPING.md`) is what actually grows the pool of genuine matches.

## 6. Filters

**Time window** (Trending Jobs, and its embedded copy on the
dashboard) — `?window=` / `?trend_window=` with `24h`, `7d`, or `30d`,
filtering on `first_seen_at`. **Defaults to `24h` on a fresh page
load** - distinguished from an explicit "Any time" click (which also
submits the param, just as `""`) by checking whether the key is
present in the querystring at all, not just its value. Search Jobs
carries the same options under `?posted=` but defaults to "Any time"
- it's a deliberate search, not a "what's fresh" feed. Implemented in
`jobs/recommender/filters.py::apply_time_window()`.

**Category** (Trending Jobs, Search Jobs, and the dashboard's
embedded search) — `?category=` against `Job.category`, see §4 above.
On Trending (both the standalone page and the dashboard's embedded
copy), a **signed-in user's category also defaults**, same "key
present vs. not" logic as the time window:
`jobs/recommender/categorize.py::infer_user_category()` looks at
their preferred job title, most recent CV experience title, skills,
then CV education degree (in that priority order — an explicit stated
preference outranks an inference from a degree), and pre-selects
whichever category that implies. A CS graduate with no other data set
opens Trending and sees Technology already selected, not an
undifferentiated mix of everything. Explicitly choosing "All
categories" is still respected as exactly that.

**Search Jobs defaults its category too, but only once the user has
engaged with search some other way** (typed a title/location, picked
a job type, or clicked a time-window pill) — never on a genuinely
fresh, untouched visit, which still shows the "Search for your next
opportunity" prompt rather than a wall of results. The distinction
matters: without it, clicking just a time-window pill with no title
typed would still run `rank_jobs()` across *every* category (it still
scores skill/location/salary match even with an empty search query),
which read as "search turned into an undifferentiated trending-style
feed" rather than a scoped search result. Once engaged, an unset
category defaults to `infer_user_category()` the same way Trending's
does, and an explicit "All categories" choice is still honored as
exactly that — this isn't search "depending on preferences" in a
restrictive sense, it's the same sensible-default-that-can-be-
overridden pattern used everywhere else in this document.

This same `infer_user_category()` is also one of the four signals in
"Recommended for you" (§5) - see **CV field match** there for why a
degree or past job title should pull relevant jobs up even before any
skills are explicitly set.

**Preferred job title is required** when saving preferences (both
`preferences.html`'s onboarding form and the dashboard's own "Job
preferences" form) — it's the strongest input to both
`infer_user_category()` and the recommendation formula's preference
score, so a blank one would leave both with much less to work with.
Location stays optional. Job type is a multi-select (checkboxes) and
an empty selection means no restriction at all — every job type still
shows in Recommended/Trending, `job_type_match_score()` just
contributes 0 rather than excluding anything.

**Location** and **job type** (Search Jobs) — plain `icontains`
filters against `Job.location` / `Job.job_type`.

**Title relevance** (Search Jobs) — when a search query is entered:

- **Logged in**: results are ranked by `recommender/ranking.py`'s
  full personalized score — a blend of skill match (40%), title
  match (30%), location match (15%), job type match (10%) and salary
  match (5%) against the user's profile/CV.
- **Not logged in**: there's no profile to personalize against, so
  results are ranked by title relevance alone
  (`recommender/matcher.py::title_match_score`) — closest to an exact
  title match first, the same "best match first" behavior LinkedIn
  and Indeed show to a visitor who isn't signed in.
