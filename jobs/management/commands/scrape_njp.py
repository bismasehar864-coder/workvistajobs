"""National Job Portal (njp.gov.pk) scraper.

NJP needs no browser: it serves its listings as plain server-rendered HTML with
stable class names and ?page=N pagination, so `requests` + BeautifulSoup
is enough. That makes it fast, headless, and cheap to run on a schedule.

njp.gov.pk/robots.txt is "User-agent: * / Disallow:" - crawling is
explicitly permitted - but we still identify ourselves honestly in the
User-Agent and pause between requests rather than hammering a
government service.

The parsing functions below are deliberately pure (HTML string in,
plain dicts out) so they can be tested against saved copies of real
pages. See jobs/tests.py::NjpParsingTests - that is what stops this
scraper from silently rotting into returning 0 results the way
scrape_mustakbil did when its selectors went stale.
"""

import re
import time

import requests
from bs4 import BeautifulSoup

from django.core.management.base import BaseCommand

from jobs.models import Job
from jobs.recommender.categorize import categorize_job


# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = "https://www.njp.gov.pk"

LISTING_URL = f"{BASE_URL}/jobs/live"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; WorkVista job aggregator; "
        "+https://www.njp.gov.pk/jobs/live)"
    )
}

REQUEST_TIMEOUT = 30

# Seconds to wait between requests. NJP is a government service and we
# are a guest on it; this keeps the crawl to a trickle.
REQUEST_DELAY = 1.5

# NJP publishes no location field - it is a single national portal.
# Leaving location blank would render as "Remote" on a job card, which
# a federal government post is not.
DEFAULT_LOCATION = "Pakistan"

SOURCE = "njp"


# ============================================================
# PARSING
# ============================================================

def _clean(text):
    """Collapse the whitespace NJP's templates leave inside badges."""

    return re.sub(r"\s+", " ", (text or "")).strip()


def _strip_label(text, label):
    """Drop a leading "Experience:"-style label from a badge."""

    cleaned = _clean(text)

    if cleaned.lower().startswith(label.lower()):
        cleaned = cleaned[len(label):]

    return cleaned.strip(" :")


def parse_listing_page(html):
    """Rows of job data from one /jobs/live page.

    Returns [] for a page with no cards, which is how crawl_listings()
    below knows it has run past the last page.
    """

    soup = BeautifulSoup(html, "html.parser")

    rows = []

    for card in soup.select("div.job-card"):

        heading = card.select_one("h2 a")

        if not heading:
            continue

        badges = card.select("div.job-badges-container > span")

        experience_badge = card.select_one("span.job-badge-exp")
        deadline_badge = card.select_one("span.job-badge-deadline")

        # The hiring body sits in the card's first paragraph, written
        # as "by <ministry>" next to a pin icon.
        company = ""

        body = card.select_one("div.job-card-main > p")

        if body:
            company = _strip_label(body.get_text(" ", strip=True), "by")

        rows.append({
            "title": _clean(heading.get_text()),

            "job_link": heading.get("href", "").strip(),

            "company": company,

            # The first badge is the engagement type (Contract,
            # Regular, ...). The ones after it are pay scale and
            # vacancy count, which we don't model.
            "job_type": _clean(badges[0].get_text()) if badges else "",

            "experience": (
                _strip_label(experience_badge.get_text(), "Experience")
                if experience_badge else ""
            ),

            # NJP shows an application deadline rather than a posting
            # date. It goes in `posted`, which is free text on every
            # source anyway - Job.first_seen_at is what time filtering
            # actually uses. See TRENDING.md.
            "posted": _clean(deadline_badge.get_text()) if deadline_badge else "",
        })

    return rows


def parse_detail_page(html):
    """The job description text from a single /jobs/<id> page."""

    soup = BeautifulSoup(html, "html.parser")

    block = soup.select_one("div.w-full.space-y-4")

    if not block:
        return ""

    return _strip_label(block.get_text(" ", strip=True), "Job Description")


# ============================================================
# FETCHING
# ============================================================

def fetch(url):
    """GET a page, returning its HTML or "" if the request failed.

    A single unreachable page must not abandon the whole crawl - the
    remaining pages are still worth having.
    """

    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

    except requests.RequestException as error:
        print(f"  ! request failed for {url}: {error}")
        return ""

    return response.text


def crawl_listings(max_pages):
    """Walk /jobs/live page by page until one comes back empty."""

    rows = []
    seen_links = set()

    for page in range(1, max_pages + 1):

        url = LISTING_URL if page == 1 else f"{LISTING_URL}?page={page}"

        print(f"  page {page}: {url}")

        page_rows = parse_listing_page(fetch(url))

        if not page_rows:
            print("  no cards on this page - stopping")
            break

        # NJP's paginator clamps an out-of-range ?page= back to the
        # last real page, so without this the crawl would loop over
        # the final page until max_pages ran out.
        fresh = [r for r in page_rows if r["job_link"] not in seen_links]

        if not fresh:
            print("  page repeats the previous one - stopping")
            break

        for row in fresh:
            seen_links.add(row["job_link"])

        rows.extend(fresh)

        time.sleep(REQUEST_DELAY)

    return rows


def add_descriptions(rows):
    """Fill in each row's description from its detail page."""

    for index, row in enumerate(rows, start=1):

        if not row.get("job_link"):
            continue

        print(f"  detail {index}/{len(rows)}: {row['job_link']}")

        row["description"] = parse_detail_page(fetch(row["job_link"]))

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

        # job_link is the identity of a posting across re-scrapes; a
        # row without one would create a duplicate every single run.
        if not row.get("job_link"):
            continue

        title = row.get("title", "")

        Job.objects.update_or_create(

            job_link=job_link,

            defaults={

                "title": title,

                "company": row.get("company", ""),

                "location": DEFAULT_LOCATION,

                "salary": "",

                "experience": row.get("experience", ""),

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

    help = "Scrape live jobs from the National Job Portal (njp.gov.pk)."

    def add_arguments(self, parser):

        parser.add_argument(
            "--max-pages",
            type=int,
            default=10,
            help="Stop after this many listing pages (default: 10).",
        )

        parser.add_argument(
            "--skip-details",
            action="store_true",
            help=(
                "Don't open each job's detail page. Much faster and far "
                "fewer requests, but the jobs are saved without their "
                "description."
            ),
        )

    def handle(self, *args, **options):

        self.stdout.write(self.style.SUCCESS("Starting NJP scraper..."))

        self.stdout.write("Collecting listings:")

        rows = crawl_listings(options["max_pages"])

        self.stdout.write(f"Found {len(rows)} listings.")

        if rows and not options["skip_details"]:
            self.stdout.write("Fetching descriptions:")
            add_descriptions(rows)

        saved = save_jobs(rows)

        self.stdout.write(
            self.style.SUCCESS(f"NJP scraping complete - {saved} jobs saved.")
        )
