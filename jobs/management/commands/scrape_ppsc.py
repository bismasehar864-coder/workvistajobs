"""Scrape PPSC's public advertisements table into the common Job model."""

import logging
import re
import unicodedata
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from jobs.models import Job, ScrapeRun
from jobs.recommender.categorize import categorize_job
from jobs.refresh import acquire_lock, get_active_scrape_run, release_lock


logger = logging.getLogger(__name__)

BASE_URL = "https://www.ppsc.gop.pk"
JOBS_URL = f"{BASE_URL}/Jobs.aspx"
TABLE_ID = "ctl00_ContentPlaceHolder1_tbl_Jobs"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; WorkVista job aggregator; "
        "+https://www.ppsc.gop.pk/Jobs.aspx)"
    )
}
REQUEST_TIMEOUT = 30
DEFAULT_LOCATION = "Punjab, Pakistan"
SOURCE = "ppsc"

COL_AD_NO = 1
COL_CASE_NO = 2
COL_TITLE = 3
COL_FEE = 4
COL_DEPARTMENT = 5
COL_AD_DATE = 6
COL_CLOSING_DATE = 7
MIN_COLUMNS = 8


def _clean(text):
    text = unicodedata.normalize("NFC", str(text or ""))
    return " ".join(text.split()).strip()


def parse_ppsc_table(html):
    """Return advertisement rows; malformed entries remain countable for logging."""

    soup = BeautifulSoup(html or "", "html.parser")
    table = soup.find("table", id=TABLE_ID)
    if table is None:
        return []

    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < MIN_COLUMNS:
            continue

        values = [_clean(cell.get_text(" ")) for cell in cells]
        case_no = values[COL_CASE_NO]
        valid_case_no = re.fullmatch(r"[A-Za-z0-9/-]+", case_no or "")
        rows.append({
            "title": values[COL_TITLE],
            "company": values[COL_DEPARTMENT],
            "location": DEFAULT_LOCATION,
            "salary": "",
            "experience": "",
            "education": "",
            "skills": [],
            "posted": values[COL_AD_DATE],
            "job_link": (
                f"{JOBS_URL}#{case_no}" if valid_case_no else ""
            ),
            "description": "; ".join(
                part for part in (
                    f"Advertisement {values[COL_AD_NO]}" if values[COL_AD_NO] else "",
                    f"Application fee: Rs. {values[COL_FEE]}" if values[COL_FEE] else "",
                    (
                        f"Closing date: {values[COL_CLOSING_DATE]}"
                        if values[COL_CLOSING_DATE] else ""
                    ),
                ) if part
            ),
        })
    return rows


def fetch(url=JOBS_URL):
    """Fetch the publicly accessible table or raise a visible request error."""

    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


def _validate_row(row):
    """Reject malformed or overlong data instead of truncating valid content."""

    normalized = {
        key: _clean(row.get(key, ""))
        for key in ("title", "company", "location", "salary", "experience",
                    "education", "posted", "description", "job_link")
    }
    normalized["skills"] = row.get("skills") or []

    if not normalized["title"]:
        raise ValueError("advertisement has no post title")
    if len(normalized["title"]) > Job._meta.get_field("title").max_length:
        raise ValueError(
            f"post title exceeds {Job._meta.get_field('title').max_length} characters"
        )
    if not normalized["job_link"]:
        raise ValueError("advertisement has no valid case number/job link")

    parsed_link = urlsplit(normalized["job_link"])
    if parsed_link.scheme != "https" or parsed_link.netloc.lower() != "www.ppsc.gop.pk":
        raise ValueError("advertisement job link is malformed")

    for field_name in ("company", "location", "salary", "experience", "posted"):
        maximum = Job._meta.get_field(field_name).max_length
        if maximum and len(normalized[field_name]) > maximum:
            raise ValueError(f"{field_name} exceeds {maximum} characters")

    if len(normalized["job_link"]) > Job._meta.get_field("job_link").max_length:
        raise ValueError("advertisement job link exceeds the supported length")
    if not isinstance(normalized["skills"], list):
        raise ValueError("skills must be a list")
    return normalized


def save_jobs(rows):
    """Upsert each valid advertisement independently and return outcome counts."""

    result = {"found": len(rows), "new": 0, "updated": 0, "failed": 0}

    for row in rows:
        try:
            values = _validate_row(row)
            title = values["title"]
            with transaction.atomic():
                _, created = Job.objects.update_or_create(
                    job_link=values["job_link"],
                    defaults={
                        **values,
                        "job_type": "",
                        "salary_min": None,
                        "salary_max": None,
                        "source": SOURCE,
                        "category": categorize_job(title, values["skills"]),
                    },
                )
            result["new" if created else "updated"] += 1
        except ValueError as error:
            result["failed"] += 1
            logger.warning(
                "PPSC advertisement failed validation: case/link=%r title=%r: %s",
                row.get("job_link", ""),
                row.get("title", ""),
                error,
            )
        except Exception:
            result["failed"] += 1
            logger.exception(
                "PPSC advertisement could not be saved: case/link=%r title=%r",
                row.get("job_link", ""),
                row.get("title", ""),
            )
    return result


class Command(BaseCommand):
    help = "Scrape live advertisements from the Punjab Public Service Commission."

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

        self.stdout.write("Starting PPSC scraper...")
        try:
            html = fetch()
            if BeautifulSoup(html, "html.parser").find("table", id=TABLE_ID) is None:
                raise RuntimeError("PPSC advertisements table was not present in the response")

            rows = parse_ppsc_table(html)
            result = save_jobs(rows)
            run.jobs_found = result["found"]
            run.jobs_saved = result["new"]
            run.jobs_updated = result["updated"]
            run.jobs_failed = result["failed"]
            run.status = "failed" if result["failed"] else "success"
            run.message = (
                f"{result['failed']} advertisement(s) failed validation or saving."
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
            self.stdout.write(self.style.SUCCESS("PPSC scraping complete."))
