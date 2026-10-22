# WorkVista

A job board that goes and finds the jobs. Five sites are scraped on a
schedule into one searchable pool; members get a personalised feed, a
CV parsed into structured data, and an email when something new
actually fits them. Companies sign up separately and post their own
openings.

Django 5.2 · MySQL 8 · Python 3.11 · no JavaScript framework

---

## Contents

1. [What it does](#1-what-it-does)
2. [Getting it running](#2-getting-it-running)
3. [The database](#3-the-database)
4. [Accounts: job seekers and employers](#4-accounts-job-seekers-and-employers)
5. [The scrapers](#5-the-scrapers)
6. [Matching: recommended, trending, alerts](#6-matching-recommended-trending-alerts)
7. [Notifications and email](#7-notifications-and-email)
8. [Email setup (SMTP)](#8-email-setup-smtp)
9. [Scheduling](#9-scheduling)
10. [Testing](#10-testing)
11. [Project layout](#11-project-layout)
12. [Troubleshooting](#12-troubleshooting)

The `guidebook/` folder goes deeper on every one of these; this file is
the map.

---

## 1. What it does

**For someone looking for work.** Sign up, upload a CV, and it is parsed
into skills, education, experience, certifications and languages. Say
what job title, location, salary and job types you want. You then get:

- **Recommended** — a ranked feed blending your CV skills, your stated
  preferences, what your CV implies your field is, and what you have
  actually been clicking on
- **Trending** — what is moving right now, not personalised
- **Search** — across every source, filterable by category, type,
  source and recency
- **Saved jobs** — bookmarks
- **Notifications** — new jobs that match you, with an unread count in
  the sidebar
- **Settings** — your preferences, and a switch for alert emails

**For a company.** Sign up as an employer, add your company profile and
any branch offices, and post jobs. Your postings join the same pool as
the scraped ones and show up in everyone's search and recommendations.
Employers do not see the job-seeking side at all.

**Running underneath.** Five scrapers refresh the pool, matching runs
after each scrape, and a daily digest emails people their new matches.

---

## 2. Getting it running

### Prerequisites

- Python 3.11
- MySQL 8 running locally

### Setup

```bash
git clone <your-repo> workvista
cd workvista

python3.11 -m venv venv311
source venv311/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then fill it in, see below
```

### Fill in `.env`

Nothing secret lives in `config/settings.py` — it all comes from `.env`,
which is gitignored and must never be committed.

```bash
# generate a secret key
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

| Variable | Required | Notes |
|---|---|---|
| `WORKVISTA_SECRET_KEY` | **yes** | Generate with the command above |
| `WORKVISTA_DB_PASSWORD` | **yes** | Your MySQL password |
| `WORKVISTA_DEBUG` | no | `True` locally, `False` in production |
| `WORKVISTA_ALLOWED_HOSTS` | no | Comma-separated; only enforced when `DEBUG=False` |
| `WORKVISTA_DB_NAME` / `_USER` / `_HOST` / `_PORT` | no | Default to `workvista_db` / `root` / `localhost` / `3306` |
| `WORKVISTA_EMAIL_USER` / `_PASSWORD` | no | Blank keeps digests printing to the terminal — see §8 |
| `WORKVISTA_SITE_URL` | no | Where links in alert emails point |

The two required ones have no fallback on purpose. A default secret key
is a published key every copy shares, and a missing database password
otherwise surfaces much later as an access-denied error that says
nothing about which knob to turn. Missing either raises
`ImproperlyConfigured` at startup, naming the variable.

### Create the database

```bash
mysql -u root -p -e "CREATE DATABASE workvista_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -u root -p workvista_db < mysql/01_schema.sql
mysql -u root -p workvista_db < mysql/02_seed_jobs.sql    # optional: real jobs to look at
```

`utf8mb4` is not optional — job descriptions contain emoji and
non-Latin characters that the older `utf8` alias cannot store.

### Run it

```bash
python manage.py migrate --check     # should report nothing pending
python manage.py runserver
```

Then <http://127.0.0.1:8000>.

> **Do not put this project in `~/Desktop`, `~/Documents` or
> `~/Downloads` on macOS.** Those folders are TCC-protected: any
> scheduled background job against them fails with `Operation not
> permitted` and no useful error. `~/workvista` is fine.

---

## 3. The database

MySQL, 21 tables — 10 are Django's own, 11 are ours.

| Table | Holds |
|---|---|
| `jobs_job` | Every listing, scraped or posted. The centre of everything. |
| `jobs_profile` | One per user: role, CV file, skills, preferences, alert settings |
| `jobs_cvdata` | Structured data parsed out of the uploaded CV |
| `jobs_company` | An employer's company — name, head office, website, founded, description |
| `jobs_companybranch` | Extra offices. Optional. |
| `jobs_notification` | Job matches, for the bell and the digest |
| `jobs_savedjob` | Bookmarks |
| `jobs_useractivity` | Views and searches — the behavioural signal for Recommended |
| `jobs_scraperun` | One row per scrape attempt: status, timings, errors |
| `jobs_scrapelock` | A single row used as a mutex around a refresh |
| `jobs_scraperwebsite` | Legacy, unused |

### Why job.company and job.location are plain text

They are `CharField`s, not foreign keys, and that is deliberate. Most
jobs are scraped and have no `Company` row behind them at all, while job
cards, search filters and the recommender all read those two fields.
Making them relations would mean teaching every one of those about a
company that, for a scraped job, does not exist. When an employer posts,
the two are *stamped* from their company and chosen branch, and
`jobs_job.branch_id` is the live link.

### Dumps

| File | Contains |
|---|---|
| `mysql/01_schema.sql` | All 21 tables + Django's migration history. No data. |
| `mysql/02_seed_jobs.sql` | Real scraped jobs. No accounts. Import after `01`. |
| `mysql/03_full_backup.sql` | Everything, **including real emails and password hashes** — gitignored |

Re-export after a schema change: see
[`guidebook/03-database-and-mysql.md`](guidebook/03-database-and-mysql.md#re-exporting-after-you-change-things).

---

## 4. Accounts: job seekers and employers

Which kind you are is chosen once, at signup, and stored on
`Profile.role`. Signing in reads it back off the account, so nobody is
ever asked twice.

```
/signup/  →  role chooser (creates nothing)
              ├─ /signup/employee/  →  CV upload  →  preferences  →  dashboard
              └─ /signup/employer/  →  company + branches  →  employer dashboard
```

| | Job seeker (`user`) | Employer (`employer`) |
|---|---|---|
| Dashboard | `/dashboard/user/` | `/dashboard/employer/` |
| Can post jobs | no | yes |
| Sees search / recommended / trending / saved | yes | no |
| Has a company and branches | no | yes |
| Uploads a CV | yes | no |
| Gets job alerts | yes | no |

The two dashboards are **separate templates**, not one with things
hidden. The sections an employer must not see are not in their template
at all, so there is nothing to hide conditionally and no way for one to
leak in.

Employer signup creates the user, profile, company and branches in a
single transaction — a `User` with no `Company` would be an account that
cannot post and cannot be repaired from the UI.

There are also `admin` and `superadmin` roles with their own dashboards
for managing users and triggering scrapers.

Full detail: [`guidebook/05-features.md`](guidebook/05-features.md) and
[`guidebook/08-post-a-job-logic.md`](guidebook/08-post-a-job-logic.md).

---

## 5. The scrapers

Six sources, each a management command that writes into `jobs_job`.

| Source | Command | How it runs |
|---|---|---|
| National Job Portal | `scrape_njp` | automatic |
| Mustakbil | `scrape_mustakbil` | automatic |
| PPSC | `scrape_ppsc` | automatic |
| Python.org | `scrape_python` | automatic |
| Remote OK | `scrape_remoteok` | automatic |
| BrightSpyre | `scrape_brightspyre` | automatic; skips expired/undated listings |

### Running one by hand

```bash
python manage.py scrape_njp
python manage.py scrape_mustakbil
python manage.py scrape_ppsc
python manage.py scrape_python
python manage.py scrape_remoteok
python manage.py scrape_brightspyre
```

### Refreshing whatever is stale

```bash
python manage.py refresh_jobs                      # all six sources
python manage.py refresh_jobs --force              # ignore the freshness check
```

`refresh_jobs` is the real entry point. It takes a database lock and
runs all sources together after the shared `JOB_REFRESH_INTERVAL_HOURS`
cooldown (default 24), recording every attempt in `jobs_scraperun`.
Configure the system scheduler to check every minute. Manual admin runs
can still be started at any time without changing the automatic batch
schedule.

### How refreshing happens on its own

There is no worker process or task queue. Instead `JobRefreshMiddleware`
hangs off ordinary web traffic: a page view checks "is anything due?" at
most once every five minutes per process, and if so starts a background
thread. The visitor's response is never held up.

For a real deployment, drive it from cron instead and set
`JOB_REFRESH_ENABLED = False`.

### Adding another source

Write a command that parses the site and calls `update_or_create` keyed
on `job_link`, then register it in `SCRAPER_COMMANDS` in
`jobs/refresh.py`. [`guidebook/09-scrapers.md`](guidebook/09-scrapers.md)
walks through one end to end.

---

## 6. Matching: recommended, trending, alerts

Three different questions, three different scorers. They share the
primitives in `jobs/recommender/matcher.py` but combine them
differently, on purpose.

**Recommended** (`jobs/recommender/recommend.py`) ranks a list. Four
optional signals, so a brand-new user still gets something:

| Signal | Weight |
|---|---|
| CV / profile skill match | 40% |
| Stated preferences (title, location, type) | 15% |
| CV field match — what your CV implies your field is | 20% |
| Behavioural affinity — what you actually view and search | 25% |

Trending score is a *tiebreaker*, not a fifth term: a job with any real
personalisation signal always outranks one with none, however fresh.

**Trending** (`jobs/recommender/trending.py`) is not personalised —
recency plus engagement.

**Alerts** (`jobs/alerts/matching.py`) answer a yes/no question about
one job, using only what you explicitly told us:

```
score = 0.5·skill + 0.3·title + 0.2·location
        renormalised over the signals you actually set
alert when score >= 40
```

Two guard rules matter more than the weights:

1. **Location alone never triggers.** If skill and title both score 0,
   the total is 0 whatever the location. Otherwise someone who set only
   "Lahore" hears about every Lahore job forever.
2. **No signals, no alerts.** Nothing to match on means nothing is sent.

And one the other way: **a job located "Remote" scores full marks on
location for everyone**, because plain string matching would give a
Lahore-based user 0 against it, and remote roles are the ones people
most want to hear about.

### The finding behind the skill matching

`Job.skills` is populated on only 27 of 216 scraped rows, and those hold
broad labels — "Back end", "Cloud" — not technologies. Measured
directly, it matches **zero** jobs for "python", "django", "react",
"excel" or "marketing", while title + description matches 22, 1, 3, 8
and 17. So alert skill matching searches
`job.skills ∪ job.title ∪ job.description`, word-boundary matched, and
scores *what fraction of your skills the job mentions* — because "this
job wants 3 of the 5 things I can do" is the question you are actually
asking.

Detail: [`guidebook/06-recommended-logic.md`](guidebook/06-recommended-logic.md),
[`guidebook/07-trending-logic.md`](guidebook/07-trending-logic.md),
[`guidebook/13-job-alerts.md`](guidebook/13-job-alerts.md).

---

## 7. Notifications and email

Two channels off one matching pass.

```
scrapers land new jobs
  └─ generate_notifications()     database only, milliseconds
       └─ rows in jobs_notification   →  sidebar badge updates immediately

manage.py send_job_alerts          SMTP, slow, separate pass
       └─ one digest email per person
```

They are deliberately separate. The badge must never wait on a mail
server, and a mail server being down must never fail a scrape. That is
what `Notification.emailed_at` is for: phase one creates rows, phase two
stamps the ones it managed to send.

**In the app.** A **Notifications** entry in the sidebar carries an
unread count. Opening the page marks everything read — that is what the
count means — while the items that were unread on arrival stay marked
for that one render, so opening the page does not erase what you came to
see. Each match shows the job, company, location, salary, a match
strength meter, and a link through.

**By email.** One digest a day listing everything new, in both plain
text and HTML. Only to job seekers who have `email_job_alerts` on and an
address on file.

**Turning email off.** A switch in **Settings**, or a one-click signed
link in every digest footer that needs no login and never expires. The
in-app notifications are unaffected by either — they cost nothing and
are only visible when you are already on the site.

**Never told twice.** `unique_together (user, job, kind)` on
`jobs_notification` — a database constraint, not a check in code, so two
refreshes racing each other cannot slip a duplicate through.

**Nothing is lost.** Each profile carries `alerts_checked_at`, a
watermark. A job is new *to you* if it first appeared after that. If
alerts do not run for three days, the next run catches everything since,
rather than silently dropping it.

---

## 8. Email setup (SMTP)

Out of the box **nothing is sent**. With `WORKVISTA_EMAIL_USER` and
`WORKVISTA_EMAIL_PASSWORD` blank, Django uses the console backend and
every digest prints to the terminal — enough to develop and test
against.

Fill both in and it switches to Gmail SMTP with no code change.
Job-alert emails use the sender `WorkVista <work4vista@gmail.com>`, so
set `WORKVISTA_EMAIL_USER=work4vista@gmail.com` and use an App Password
for that same account. If Gmail still displays a personal name, update
the Google account's sender/display name to **WorkVista**.

### Gmail needs an App Password

Not your account password. Google withdrew password SMTP for
third-party apps in May 2022, so the account password will simply fail
to authenticate.

1. Turn on 2-Step Verification on the Google account
2. Generate an App Password at <https://myaccount.google.com/apppasswords>
3. Put it in `.env` as `WORKVISTA_EMAIL_PASSWORD`

Google shows it as four groups of four (`abcd efgh ijkl mnop`); SMTP
wants the sixteen characters with no spaces. `settings.py` strips them,
so either form works.

An App Password is a credential in its own right — keep it in `.env`,
never in `settings.py`, and revoke it from that page if it leaks. It can
be revoked on its own without touching the account password.

### Checking it works

```bash
python manage.py send_job_alerts --dry-run       # reports, sends nothing
python manage.py send_job_alerts                 # actually sends
```

The test suite can never send real mail — Django's test runner swaps in
an in-memory backend whatever `.env` says.

Another provider works the same way: set `WORKVISTA_EMAIL_HOST` and
`WORKVISTA_EMAIL_PORT` alongside the user and password.

---

## 9. Scheduling

```bash
python manage.py send_job_alerts     # match, then email everyone their digest
```

Flags: `--dry-run` reports without sending or writing;
`--skip-matching` sends only what is already waiting.

### macOS — launchd

`bin/send_job_alerts.sh` wraps the command with a timestamp and appends
to `logs/job_alerts.log`. A launchd agent at
`~/Library/LaunchAgents/com.workvista.jobalerts.plist` runs it daily at
09:00.

```bash
launchctl list | grep workvista                              # registered?
launchctl kickstart -p gui/$(id -u)/com.workvista.jobalerts   # run it now
tail -20 logs/job_alerts.log                                  # what it did
launchctl bootout gui/$(id -u)/com.workvista.jobalerts        # stop it
```

**Not cron.** On macOS, `/usr/sbin/cron` cannot read `/usr/lib/cron/tabs`
without Full Disk Access, so a crontab entry never fires and nothing is
logged anywhere — it just silently does not run.

### Linux — cron

Neither restriction exists, so a plain crontab line is fine:

```
0 9 * * *  cd /path/to/workvista && venv311/bin/python manage.py send_job_alerts
* * * * * cd /path/to/workvista && venv311/bin/python manage.py refresh_jobs
```

### Without any scheduler

`JobRefreshMiddleware` sends the digest on the first page view after 24
hours without one. That is a fallback, not the mechanism — it depends on
somebody visiting. A week with no visitors is a week with no digests.

---

## 10. Testing

```bash
python manage.py test                 # everything
python manage.py test jobs.tests_alerts               # one module
python manage.py test jobs.tests.CategorizeJobTests   # one class
```

340 tests, about 20 seconds, touching no external website.

| Module | Tests | Covers |
|---|---|---|
| `jobs/tests.py` | 88 | Posting, categories, search, three scrapers |
| `jobs/tests_employer.py` | 63 | Employer signup, company, branches, the posting gate |
| `jobs/tests_alerts.py` | 65 | The alert score, notifications, the digest, unsubscribe |
| `jobs/tests_navigation.py` | 42 | Section URLs, where forms return you, sidebar state |
| `jobs/tests_refresh.py` | 40 | Freshness, locking, the traffic trigger |
| `jobs/tests_settings.py` | 29 | The Notifications and Settings sections, the badge |
| `jobs/tests_config.py` | 13 | That settings come from `.env` and no credential is in `settings.py` |

Two things the suite deliberately cannot do, both switched off by
`"test" in sys.argv`: start a real scraper (`JOB_REFRESH_ENABLED`) or
send a real email (`JOB_ALERTS_ENABLED`).

---

## 11. Project layout

```
config/          Django settings (credentials from .env), root URLs
jobs/
  models.py            11 models
  views.py             public pages, job-seeker dashboard, admin shells
  views_employer.py    employer dashboard, branches, posting
  views_settings.py    the Settings section
  views_alerts.py      notifications, unsubscribe
  forms.py             signup, company, branch, post-a-job
  roles.py             employer_required
  refresh.py           scheduling, locking, the traffic trigger
  recommender/         matcher, recommend, trending, categorize
  alerts/              matching, notifications, digest
  management/commands/ five scrapers + refresh_jobs + send_job_alerts
templates/       base, auth, dashboards, email
static/css/      the "Vista" design system
bin/             send_job_alerts.sh
mysql/           schema and seed dumps
guidebook/       13 chapters, one per subsystem
docs/superpowers/ design specs and implementation plans
```

---

## 12. Troubleshooting

**`ImproperlyConfigured: WORKVISTA_SECRET_KEY is not set`**
No `.env`, or it is missing a required variable. `cp .env.example .env`
and fill it in.

**MySQL access denied**
`WORKVISTA_DB_PASSWORD` in `.env` does not match your MySQL root
password.

**Emails are not arriving**
Run `python manage.py send_job_alerts --dry-run`. If it says it would
email someone but nothing arrives, check §8 — the most common cause is
using the account password instead of an App Password.

**The scheduled job never runs (macOS)**
See §9. Almost always either a crontab (which macOS silently ignores) or
a project sitting in `~/Desktop`.

**Nobody is getting alerts**
They need a preferred job title or skills set — location alone never
triggers, by design. Check Settings.

More: [`guidebook/12-troubleshooting.md`](guidebook/12-troubleshooting.md).
