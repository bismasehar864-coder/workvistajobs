"""Import current job listings from BrightSpyre's public jobs pages."""

import logging
import re
import time
from datetime import date
from urllib.parse import parse_qs, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from jobs.models import Job, ScrapeRun
from jobs.refresh import acquire_lock, get_active_scrape_run, release_lock
from jobs.recommender.categorize import categorize_job


logger = logging.getLogger(__name__)

BASE_URL = "https://resume.brightspyre.com"
JOBS_URL = f"{BASE_URL}/jobs"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; WorkVista job aggregator; "
        "+https://resume.brightspyre.com/jobs)"
    )
}
REQUEST_TIMEOUT = 30
REQUEST_DELAY = 1.0
SOURCE = "brightspyre"
ALLOWED_JOB_HOSTS = {"resume.brightspyre.com"}

JOB_TYPE_MAP = {
    "contract": "Contract",
    "contractual": "Contract",
    "full time": "Full-time",
    "full-time": "Full-time",
    "part time": "Part-time",
    "part-time": "Part-time",
    "remote": "Remote",
}


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _parse_date(value):
    value = _clean(value)
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _property_text(element, name):
    node = element.select_one(f'[property="{name}"]')
    return _clean(node.get_text(" ", strip=True)) if node else ""


def _job_type(value):
    return JOB_TYPE_MAP.get(_clean(value).lower(), "")


def parse_listing_page(html, today=None):
    """Extract current jobs from one BrightSpyre results page.

    Listings without a usable application deadline are omitted as well:
    there is no reliable way to establish that they have not expired.
    """

    today = today or timezone.localdate()
    soup = BeautifulSoup(html, "html.parser")
    rows = []

    for title_link in soup.select("a.title-job[href]"):
        card = title_link.find_parent("div", class_="col-md-10")
        if card is None:
            continue

        deadline = _parse_date(_property_text(card, "validThrough"))
        if deadline is None or deadline < today:
            continue

        job_link = urljoin(BASE_URL, title_link["href"])
        company_node = card.select_one('[type="PropertyValue"]')
        company = _clean(company_node.get_text(" ", strip=True)) if company_node else ""
        description_node = card.select_one('[property="description"]')
        description_raw = (
            description_node.get_text("\n", strip=True)
            if description_node else ""
        )
        description = _clean(description_raw)
        description = re.sub(r"\s*\.{3,}\s*$", "", description)

        location_parts = [
            _property_text(card, "addressLocality"),
            _property_text(card, "addressRegion"),
            _property_text(card, "addressCountry"),
        ]
        location_parts = [
            part for part in location_parts
            if part and part not in {"-", "N/A"}
        ]
        location = ", ".join(dict.fromkeys(location_parts))
        if not location:
            match = re.search(
                r"(?:^|\n)\s*Location:\s*([^\r\n]+)",
                description_raw,
                flags=re.IGNORECASE,
            )
            location = _clean(match.group(1)) if match else "Pakistan"

        tags = [
            _clean(tag.get_text(" ", strip=True)).lstrip("#")
            for tag in card.select(".tags-default a")
        ]
        tags = [tag for tag in tags if tag]

        rows.append({
            "title": _clean(title_link.get_text(" ", strip=True)),
            "company": company,
            "location": location,
            "salary": "",
            "experience": "",
            "job_type": _job_type(_property_text(card, "employmentType")),
            "education": "",
            "skills": tags,
            "posted": _property_text(card, "datePosted"),
            "valid_through": deadline.isoformat(),
            "job_link": job_link,
            "description": description,
        })

    return rows


def next_page_number(html):
    """Return the next results page number, or None on the final page."""

    soup = BeautifulSoup(html, "html.parser")
    for link in soup.select('a[href*="page="]'):
        if not re.search(r"\bnext\b", link.get_text(" ", strip=True), re.I):
            continue
        query = parse_qs(urlsplit(link["href"]).query)
        try:
            return int(query["page"][0])
        except (KeyError, IndexError, ValueError):
            return None
    return None


def fetch_jobs(today=None):
    """Fetch every results page and retain only listings with an active deadline."""

    today = today or timezone.localdate()
    rows = []
    seen_pages = set()
    page = 1

    while page not in seen_pages:
        seen_pages.add(page)
        params = {"page": page} if page > 1 else None
        response = requests.get(
            JOBS_URL,
            params=params,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        if not soup.select("a.title-job[href]"):
            raise ValueError(
                f"BrightSpyre page {page} contained no job listing cards"
            )

        rows.extend(parse_listing_page(response.text, today=today))
        next_page = next_page_number(response.text)
        if next_page is None:
            break
        if next_page in seen_pages:
            raise ValueError("BrightSpyre pagination repeated a results page")

        page = next_page
        time.sleep(REQUEST_DELAY)

    return rows


def _validate_row(row, today=None):
    values = {
        key: _clean(row.get(key, ""))
        for key in (
            "title", "company", "location", "salary", "experience",
            "job_type", "education", "posted", "valid_through",
            "job_link", "description",
        )
    }
    values["skills"] = row.get("skills") or []

    if not values["title"]:
        raise ValueError("job has no title")
    if len(values["title"]) > Job._meta.get_field("title").max_length:
        raise ValueError("job title exceeds the supported length")
    if not isinstance(values["skills"], list):
        raise ValueError("job tags must be a list")

    deadline = _parse_date(values["valid_through"])
    if deadline is None:
        raise ValueError("job has no valid application deadline")
    if deadline < (today or timezone.localdate()):
        raise ValueError("job application deadline has passed")

    link = urlsplit(values["job_link"])
    if (
        link.scheme != "https"
        or (link.hostname or "").lower() not in ALLOWED_JOB_HOSTS
        or not re.fullmatch(r"/jobs/[A-Za-z0-9_-]+", link.path)
    ):
        raise ValueError("job link is not a valid BrightSpyre listing URL")
    if len(values["job_link"]) > Job._meta.get_field("job_link").max_length:
        raise ValueError("job link exceeds the supported length")

    for field_name in (
        "company", "location", "salary", "experience", "job_type", "posted",
    ):
        maximum = Job._meta.get_field(field_name).max_length
        if maximum and len(values[field_name]) > maximum:
            raise ValueError(f"{field_name} exceeds {maximum} characters")

    return values


def save_jobs(rows, today=None):
    """Upsert active BrightSpyre listings by their canonical job URL."""

    result = {"found": len(rows), "new": 0, "updated": 0, "failed": 0}
    for row in rows:
        try:
            values = _validate_row(row, today=today)
            with transaction.atomic():
                _, created = Job.objects.update_or_create(
                    job_link=values["job_link"],
                    defaults={
                        **{
                            key: value
                            for key, value in values.items()
                            if key != "valid_through"
                        },
                        "salary_min": None,
                        "salary_max": None,
                        "source": SOURCE,
                        "category": categorize_job(
                            values["title"], values["skills"]
                        ),
                    },
                )
            result["new" if created else "updated"] += 1
        except ValueError as error:
            result["failed"] += 1
            logger.warning(
                "BrightSpyre job failed validation: link=%r title=%r: %s",
                row.get("job_link", ""),
                row.get("title", ""),
                error,
            )
        except Exception:
            result["failed"] += 1
            logger.exception(
                "BrightSpyre job could not be saved: link=%r title=%r",
                row.get("job_link", ""),
                row.get("title", ""),
            )
    return result


class Command(BaseCommand):
    help = "Import active job listings from BrightSpyre."

    def handle(self, *args, **options):
        run = get_active_scrape_run(SOURCE)
        owns_lock = run is None
        if owns_lock:
            run = ScrapeRun.objects.create(source=SOURCE, status="running")
            try:
                lock_acquired = acquire_lock()
            except Exception as error:
                run.status = "failed"
                run.message = f"{type(error).__name__}: {error}"[:2000]
                run.finished_at = timezone.now()
                run.save(update_fields=["status", "message", "finished_at"])
                raise
            if not lock_acquired:
                run.status = "failed"
                run.message = "Another scraper run is already active."
                run.finished_at = timezone.now()
                run.save(update_fields=["status", "message", "finished_at"])
                raise RuntimeError(run.message)

        self.stdout.write("Starting BrightSpyre scraper...")
        try:
            rows = fetch_jobs()
            result = save_jobs(rows)
            run.jobs_found = result["found"]
            run.jobs_saved = result["new"]
            run.jobs_updated = result["updated"]
            run.jobs_failed = result["failed"]
            run.status = "failed" if result["failed"] else "success"
            run.message = (
                f"{result['failed']} job(s) failed validation or saving."
                if result["failed"] else ""
            )
            run.finished_at = timezone.now()
            run.save(update_fields=[
                "jobs_found", "jobs_saved", "jobs_updated", "jobs_failed",
                "status", "message", "finished_at",
            ])
        except Exception as error:
            run.status = "failed"
            run.message = f"{type(error).__name__}: {error}"[:2000]
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "message", "finished_at"])
            raise
        finally:
            if owns_lock:
                release_lock()

        self.stdout.write(
            f"Discovered {result['found']}; new {result['new']}; "
            f"updated {result['updated']}; failed {result['failed']}."
        )
        if result["failed"]:
            self.stderr.write(self.style.WARNING(run.message))
        else:
            self.stdout.write(self.style.SUCCESS("BrightSpyre scraping complete."))
