# WorkVista — database dumps

Import one of these instead of building the schema by hand. **You do
not need to run `manage.py migrate`** — `01_schema.sql` carries the
migration history with it.

Full explanation: [`guidebook/03-database-and-mysql.md`](../guidebook/03-database-and-mysql.md).

## Files

| File | Size | Contains |
|------|------|----------|
| `01_schema.sql` | 24 KB | All 21 tables + Django's migration history. No user or job data. |
| `02_seed_jobs.sql` | 500 KB | 235 real jobs from all 6 sources. No accounts. Import *after* `01`. |
| `03_full_backup.sql` | 559 KB | Everything, including user accounts, parsed CVs and activity. |

## Quick start

```bash
mysql -u root -p -e "CREATE DATABASE workvista_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -u root -p workvista_db < mysql/01_schema.sql
mysql -u root -p workvista_db < mysql/02_seed_jobs.sql
```

Then check:

```bash
python manage.py migrate --check      # should report nothing to do
mysql -u root -p workvista_db -e "SELECT source, COUNT(*) FROM jobs_job GROUP BY source;"
```

Expected:

```
njp         78
mustakbil   57
indeed      45
python_org  30
ppsc        23
workvista    2
```

## Which file do I want?

- **Starting fresh, want something to look at** → `01` then `02`
- **Starting fresh, want it empty** → `01` only
- **Restoring this exact instance** → `03` only (it includes everything)

`jobs_notification` holds the job-match alerts behind the dashboard bell
and the digest email; `unique_together (user, job, kind)` is what stops
anyone being told about the same job twice. See
[`guidebook/13-job-alerts.md`](../guidebook/13-job-alerts.md).

Two other tables hold employer accounts: `jobs_company` (one row
per employer, holding the company name, head office, website, founding
year and description) and `jobs_companybranch` (extra offices, optional).
`jobs_job.branch_id` points at whichever office a posting is for, and is
null for head office and for every scraped job.

`utf8mb4` is required — job descriptions contain emoji and non-Latin
characters, and the older `utf8` alias cannot store them.

## A note on `03_full_backup.sql`

It contains real user rows: email addresses and hashed passwords from
`auth_user`, plus parsed CV contents in `jobs_cvdata`. Fine as a local
backup — **do not push it to a public repository.** `01` and `02` carry
no personal data and are safe to share.

## Re-exporting

The exact commands used to produce these files are in
[`guidebook/03-database-and-mysql.md`](../guidebook/03-database-and-mysql.md#re-exporting-after-you-change-things).
