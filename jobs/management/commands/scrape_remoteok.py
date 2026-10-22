"""Import Remote OK public API listings into WorkVista's Job model."""

import logging
import re
from html import unescape
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

API_URL = "https://remoteok.com/api"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; WorkVista job aggregator; "
        "+https://remoteok.com)"
    )
}
REQUEST_TIMEOUT = 30
SOURCE = "remoteok"
ALLOWED_JOB_HOSTS = {"remoteok.com", "www.remoteok.com"}


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _salary_text(item):
    minimum = item.get("salary_min")
    maximum = item.get("salary_max")
    try:
        minimum = int(minimum) if minimum not in (None, "") else None
        maximum = int(maximum) if maximum not in (None, "") else None
    except (TypeError, ValueError):
        return ""

    minimum = minimum if minimum and minimum > 0 else None
    maximum = maximum if maximum and maximum > 0 else None
    amounts = [amount for amount in (minimum, maximum) if amount is not None]
    if not amounts:
        return ""
    if minimum is None:
        minimum = maximum
    if maximum is None:
        maximum = minimum
    if minimum == maximum:
        return f"USD {minimum:,}"
    return f"USD {minimum:,} - {maximum:,}"


def _description(value):
    return _clean(BeautifulSoup(unescape(str(value or "")), "html.parser").get_text(" "))


def _job_type(tags):
    normalized = {str(tag).strip().lower().replace("-", " ") for tag in tags}
    if "part time" in normalized:
        return "Part-time"
    if "contract" in normalized or "contractor" in normalized:
        return "Contract"
    if "full time" in normalized:
        return "Full-time"
    return "Remote"


def parse_jobs(payload):
    """Extract listing fields; ignore the API's leading legal metadata object."""
    if not isinstance(payload, list):
        raise ValueError("Remote OK API response must be a JSON list")

    rows = []
    for item in payload:
        if not isinstance(item, dict) or not item.get("position"):
            continue
        rows.append({
            "title": _clean(item.get("position")),
            "company": _clean(item.get("company")),
            "location": _clean(item.get("location")),
            "salary": _salary_text(item),
            "experience": "",
            "job_type": _job_type(item.get("tags") or []),
            "education": "",
            "skills": [
                _clean(tag) for tag in (item.get("tags") or [])
                if _clean(tag)
            ],
            "posted": _clean(item.get("date")),
            "job_link": _clean(item.get("url")),
            "description": _description(item.get("description")),
        })
    return rows


def fetch_jobs():
    response = requests.get(API_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as error:
        raise ValueError("Remote OK returned invalid JSON") from error
    return parse_jobs(payload)


def _validate_row(row):
    values = {
        key: _clean(row.get(key, ""))
        for key in (
            "title", "company", "location", "salary", "experience",
            "job_type", "education", "posted", "job_link", "description",
        )
    }
    values["skills"] = row.get("skills") or []

    if not values["title"]:
        raise ValueError("job has no title")
    if len(values["title"]) > Job._meta.get_field("title").max_length:
        raise ValueError("job title exceeds the supported length")
    if not isinstance(values["skills"], list):
        raise ValueError("job tags must be a list")

    link = urlsplit(values["job_link"])
    if (
        link.scheme != "https"
        or (link.hostname or "").lower() not in ALLOWED_JOB_HOSTS
    ):
        raise ValueError("job link is not a valid Remote OK listing URL")
    if len(values["job_link"]) > Job._meta.get_field("job_link").max_length:
        raise ValueError("job link exceeds the supported length")

    for field_name in (
        "company", "location", "salary", "experience", "job_type", "posted",
    ):
        maximum = Job._meta.get_field(field_name).max_length
        if maximum and len(values[field_name]) > maximum:
            raise ValueError(f"{field_name} exceeds {maximum} characters")
    return values


def save_jobs(rows):
    """Upsert Remote OK listings by their canonical job URL."""
    result = {"found": len(rows), "new": 0, "updated": 0, "failed": 0}
    for row in rows:
        try:
            values = _validate_row(row)
            with transaction.atomic():
                _, created = Job.objects.update_or_create(
                    job_link=values["job_link"],
                    defaults={
                        **values,
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
                "Remote OK job failed validation: link=%r title=%r: %s",
                row.get("job_link", ""),
                row.get("title", ""),
                error,
            )
        except Exception:
            result["failed"] += 1
            logger.exception(
                "Remote OK job could not be saved: link=%r title=%r",
                row.get("job_link", ""),
                row.get("title", ""),
            )
    return result


class Command(BaseCommand):
    help = "Import jobs from Remote OK's public jobs API."

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

        self.stdout.write("Starting Remote OK scraper...")
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
            self.stdout.write(self.style.SUCCESS("Remote OK scraping complete."))
