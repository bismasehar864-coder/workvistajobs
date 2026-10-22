"""Mustakbil (mustakbil.com) scraper.

Rewritten to need no browser. The previous version drove Selenium
through a grid of cities x keywords and read job cards by CSS class;
Mustakbil then renamed those classes (`.job-title__link` ->
`.jc-title__link`, `.job-company` -> `.jc-byline__company`, and the
`.job-time` / `.job-location` / `.job-badge--*` elements went away
entirely). Every card lookup threw, `extract_job_card()` swallowed the
exception and returned None, and the scraper cheerfully reported 0
results for every single query without ever failing. It stayed that way
until somebody checked.

Two things make this version far harder to break that quietly:

1.  Job URLs come from the sitemap Mustakbil publishes in its own
    robots.txt (sitemaps.mustakbil.com), which carries a <lastmod> per
    posting - so "newest first" is the site's own answer, not ours.

2.  Each posting is read from its schema.org JobPosting JSON-LD rather
    than from CSS classes. That block is what Mustakbil feeds Google
    for search results, so it is both stable and structured - it even
    carries a numeric salary range, which the old card scraping could
    only get as free text.

robots.txt is `Allow: /` for everything we touch here. We still
identify ourselves in the User-Agent and pause between requests.

parse_sitemap() and parse_job_posting() are pure functions tested
against saved copies of the real feed and a real posting - see
jobs/tests.py::MustakbilSitemapTests and MustakbilJobPostingTests.
"""

import json
import re
import time
from html import unescape

import requests
from bs4 import BeautifulSoup

from django.core.management.base import BaseCommand

from jobs.models import Job
from jobs.recommender.categorize import categorize_job


# ============================================================
# CONFIGURATION
# ============================================================

SITEMAP_URL = "https://sitemaps.mustakbil.com/sitemaps/jobs/1"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; WorkVista job aggregator; "
        "+https://www.mustakbil.com/jobs)"
    )
}

REQUEST_TIMEOUT = 30

REQUEST_DELAY = 1.0

SOURCE = "mustakbil"

# schema.org spells employment types in SCREAMING_SNAKE; the rest of
# WorkVista uses Job.JOB_TYPE_CHOICES. Anything unmapped is left blank
# rather than invented.
EMPLOYMENT_TYPES = {
    "FULL_TIME": "Full-time",
    "PART_TIME": "Part-time",
    "CONTRACTOR": "Contract",
    "TEMPORARY": "Contract",
    "INTERN": "Part-time",
}


# ============================================================
# PARSING
# ============================================================

def _clean(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def parse_sitemap(xml):
    """[{"url", "lastmod"}] from a sitemap, newest posting first.

    Sorting here is what makes --limit mean "the N most recently
    updated postings" rather than "whatever the file happens to list
    first" - Mustakbil's sitemap is not in date order.
    """

    entries = []

    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):

        loc = re.search(r"<loc>(.*?)</loc>", block, re.S)

        if not loc:
            continue

        lastmod = re.search(r"<lastmod>(.*?)</lastmod>", block, re.S)

        entries.append({
            "url": _clean(loc.group(1)),
            "lastmod": _clean(lastmod.group(1)) if lastmod else "",
        })

    # ISO-8601 timestamps sort correctly as plain strings.
    entries.sort(key=lambda entry: entry["lastmod"], reverse=True)

    return entries


def _job_posting_data(html):
    """The JobPosting JSON-LD block on a posting page, or None."""

    soup = BeautifulSoup(html, "html.parser")

    for script in soup.find_all("script", {"type": "application/ld+json"}):

        try:
            data = json.loads(script.string or "")

        except (ValueError, TypeError):
            continue

        # A page may carry several blocks (breadcrumbs, organisation);
        # occasionally they arrive as a list.
        for candidate in (data if isinstance(data, list) else [data]):

            if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
                return candidate

    return None


def _location(posting):
    place = posting.get("jobLocation") or {}

    if isinstance(place, list):
        place = place[0] if place else {}

    address = place.get("address") or {}

    parts = [
        address.get("addressLocality"),
        address.get("addressCountry"),
    ]

    return ", ".join(part for part in parts if part)


def _salary(posting):
    """(text, minimum, maximum) from a MonetaryAmount, or ("", None, None)."""

    base = posting.get("baseSalary") or {}
    value = base.get("value") or {}

    minimum = value.get("minValue")
    maximum = value.get("maxValue")

    if minimum is None and maximum is None:
        return "", None, None

    if minimum is None:
        minimum = maximum

    if maximum is None:
        maximum = minimum

    currency = base.get("currency") or ""

    # unitText is HOUR / DAY / WEEK / MONTH / YEAR.
    unit = (value.get("unitText") or "").lower()

    text = f"{currency} {int(minimum):,} - {int(maximum):,}".strip()

    if unit:
        text = f"{text} /{unit}"

    return text, int(minimum), int(maximum)


def _description(posting):
    """The description as plain text.

    JobPosting descriptions are HTML, and are sometimes double-escaped.
    """

    raw = posting.get("description") or ""

    return _clean(BeautifulSoup(unescape(raw), "html.parser").get_text(" "))


def parse_job_posting(html):
    """A row of job data from one posting page, or None if it has none."""

    posting = _job_posting_data(html)

    if not posting:
        return None

    organisation = posting.get("hiringOrganization") or {}

    employment_type = posting.get("employmentType") or ""

    if isinstance(employment_type, list):
        employment_type = employment_type[0] if employment_type else ""

    salary_text, salary_min, salary_max = _salary(posting)

    return {
        "title": _clean(posting.get("title")),

        "company": _clean(organisation.get("name") if isinstance(organisation, dict) else ""),

        "location": _location(posting),

        "job_type": EMPLOYMENT_TYPES.get(str(employment_type).upper(), ""),

        "salary": salary_text,

        "salary_min": salary_min,

        "salary_max": salary_max,

        "description": _description(posting),

        # Free text on every source. Job.first_seen_at is what time
        # filtering actually uses - see TRENDING.md.
        "posted": _clean(posting.get("datePosted"))[:10],

        "job_link": _clean(posting.get("url")),
    }


# ============================================================
# FETCHING
# ============================================================

def fetch(url):
    """GET a page, returning its text or "" if the request failed."""

    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

    except requests.RequestException as error:
        print(f"  ! request failed for {url}: {error}")
        return ""

    return response.text


def collect_jobs(limit):
    """Parse the `limit` most recently updated postings in the sitemap."""

    entries = parse_sitemap(fetch(SITEMAP_URL))

    print(f"  sitemap lists {len(entries)} postings")

    rows = []

    for index, entry in enumerate(entries[:limit], start=1):

        print(f"  {index}/{min(limit, len(entries))}: {entry['url']}")

        row = parse_job_posting(fetch(entry["url"]))

        if not row:
            print("    ! no JobPosting data on this page - skipped")
            time.sleep(REQUEST_DELAY)
            continue

        # The sitemap URL is the canonical one; the JSON-LD's own `url`
        # is occasionally absent.
        row["job_link"] = row.get("job_link") or entry["url"]

        rows.append(row)

        time.sleep(REQUEST_DELAY)

    return rows


# ============================================================
# SAVING
# ============================================================

def save_jobs(rows):
    """Upsert rows into Job, keyed on job_link. Returns how many."""

    saved = 0

    for row in rows:

        job_link = (row.get("job_link") or "").strip()

        if not job_link:
            continue

        title = row.get("title", "")

        Job.objects.update_or_create(

            job_link=job_link,

            defaults={

                "title": title,

                "company": row.get("company", ""),

                "location": row.get("location", ""),

                "salary": row.get("salary", ""),

                "salary_min": row.get("salary_min"),

                "salary_max": row.get("salary_max"),

                "experience": "",

                "job_type": row.get("job_type", ""),

                "education": "",

                "skills": [],

                "posted": row.get("posted", ""),

                "source": SOURCE,

                "description": row.get("description", ""),

                "category": categorize_job(title),
            }
        )

        saved += 1

    return saved


# ============================================================
# DJANGO MANAGEMENT COMMAND
# ============================================================

class Command(BaseCommand):

    help = "Scrape jobs from Mustakbil via its sitemap and JobPosting data."

    def add_arguments(self, parser):

        parser.add_argument(
            "--limit",
            type=int,
            default=60,
            help=(
                "How many of the most recently updated postings to fetch "
                "(default: 60). One request each, so keep it sane."
            ),
        )

    def handle(self, *args, **options):

        self.stdout.write(self.style.SUCCESS("Starting Mustakbil scraper..."))

        rows = collect_jobs(options["limit"])

        self.stdout.write(f"Parsed {len(rows)} postings.")

        saved = save_jobs(rows)

        self.stdout.write(
            self.style.SUCCESS(f"Mustakbil scraping complete - {saved} jobs saved.")
        )
