from pathlib import Path
from datetime import date, timedelta
import re
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.template.loader import render_to_string
from django.utils import timezone

from . import refresh
from .management.commands.scrape_brightspyre import (
    fetch_jobs as fetch_brightspyre_jobs,
    next_page_number as brightspyre_next_page_number,
    parse_listing_page as parse_brightspyre_listing_page,
    save_jobs as save_brightspyre_jobs,
)
from .management.commands.scrape_ppsc import (
    parse_ppsc_table,
    save_jobs as save_ppsc_jobs,
)
from .management.commands.scrape_remoteok import (
    parse_jobs as parse_remoteok_jobs,
    save_jobs as save_remoteok_jobs,
)
from .models import Job, ScrapeRun, ScraperSchedule
from .views import run_scraper


def ppsc_fixture():
    return (Path(__file__).parent / "tests_data" / "ppsc_jobs.html").read_text(
        encoding="utf-8"
    )


BRIGHTSPYRE_PAGE_ONE = """
<div class="col-md-10 col-xs-10 padding-top-ten">
  <a class="title-job" href="/jobs/active-job">Current Python Developer</a>
  <span type="PropertyValue">Example Health</span>
  <span property="validThrough">2026-10-25</span>
  <span property="datePosted">2026-10-14</span>
  <span property="employmentType">Full Time</span>
  <span property="description">Job Title: Developer
Location: Lahore, Pakistan
Build Python APIs....</span>
  <span property="addressLocality">-</span>
  <span property="addressRegion">-</span>
  <span property="addressCountry">-</span>
  <li class="tags-default"><a href="/jobs?query=python">#Python</a></li>
</div>
<div class="col-md-10 col-xs-10 padding-top-ten">
  <a class="title-job" href="/jobs/expired-job">Expired Developer</a>
  <span type="PropertyValue">Example Health</span>
  <span property="validThrough">2026-10-15</span>
</div>
<div class="col-md-10 col-xs-10 padding-top-ten">
  <a class="title-job" href="/jobs/no-deadline">Unknown deadline role</a>
  <span type="PropertyValue">Example Health</span>
</div>
<a href="/jobs?page=2">Next&nbsp;›</a>
"""

BRIGHTSPYRE_PAGE_TWO = """
<div class="col-md-10 col-xs-10 padding-top-ten">
  <a class="title-job" href="/jobs/second-job">Current Nurse</a>
  <span type="PropertyValue">Example Clinic</span>
  <span property="validThrough">2026-10-16</span>
  <span property="datePosted">2026-10-16</span>
  <span property="employmentType">Contractual</span>
  <span property="description">Location: Karachi, Pakistan.</span>
</div>
"""


class BrightSpyreParsingTests(TestCase):

    def test_only_jobs_with_nonexpired_deadlines_are_parsed(self):
        rows = parse_brightspyre_listing_page(
            BRIGHTSPYRE_PAGE_ONE,
            today=date(2026, 10, 16),
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Current Python Developer")
        self.assertEqual(rows[0]["company"], "Example Health")
        self.assertEqual(rows[0]["location"], "Lahore, Pakistan")
        self.assertEqual(rows[0]["job_type"], "Full-time")
        self.assertEqual(rows[0]["posted"], "2026-10-14")
        self.assertEqual(rows[0]["valid_through"], "2026-10-25")
        self.assertEqual(rows[0]["skills"], ["Python"])
        self.assertEqual(rows[0]["job_link"], "https://resume.brightspyre.com/jobs/active-job")

    def test_deadline_today_is_still_active(self):
        rows = parse_brightspyre_listing_page(
            BRIGHTSPYRE_PAGE_TWO,
            today=date(2026, 10, 16),
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Current Nurse")
        self.assertEqual(rows[0]["job_type"], "Contract")

    def test_next_results_page_is_followed(self):
        self.assertEqual(brightspyre_next_page_number(BRIGHTSPYRE_PAGE_ONE), 2)
        self.assertIsNone(brightspyre_next_page_number(BRIGHTSPYRE_PAGE_TWO))

    def test_fetch_jobs_collects_all_pages(self):
        responses = [
            mock.Mock(text=BRIGHTSPYRE_PAGE_ONE),
            mock.Mock(text=BRIGHTSPYRE_PAGE_TWO),
        ]
        for response in responses:
            response.raise_for_status.return_value = None

        with (
            mock.patch(
                "jobs.management.commands.scrape_brightspyre.requests.get",
                side_effect=responses,
            ) as get,
            mock.patch("jobs.management.commands.scrape_brightspyre.time.sleep"),
        ):
            rows = fetch_brightspyre_jobs(today=date(2026, 10, 16))

        self.assertEqual(
            [row["title"] for row in rows],
            ["Current Python Developer", "Current Nurse"],
        )
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[1].kwargs["params"], {"page": 2})

    def test_source_is_registered_for_search_dashboard_and_refresh(self):
        self.assertIn("brightspyre", dict(Job.SOURCE_CHOICES))
        self.assertEqual(
            refresh.SCRAPER_COMMANDS["brightspyre"],
            "scrape_brightspyre",
        )
        self.assertIn("brightspyre", refresh.AUTO_SOURCES)


class BrightSpyreSavingTests(TestCase):

    def setUp(self):
        self.row = parse_brightspyre_listing_page(
            BRIGHTSPYRE_PAGE_ONE,
            today=date(2026, 10, 16),
        )[0]

    def test_active_jobs_are_saved_with_brightspyre_source(self):
        result = save_brightspyre_jobs([self.row], today=date(2026, 10, 16))

        job = Job.objects.get()
        self.assertEqual(result, {
            "found": 1, "new": 1, "updated": 0, "failed": 0,
        })
        self.assertEqual(job.source, "brightspyre")
        self.assertEqual(job.title, "Current Python Developer")
        self.assertEqual(job.category, "technology")

    def test_expired_or_missing_deadline_jobs_are_not_saved(self):
        expired = dict(self.row, valid_through="2026-10-15")
        missing = dict(self.row, job_link="https://resume.brightspyre.com/jobs/missing")
        missing.pop("valid_through")

        result = save_brightspyre_jobs(
            [expired, missing],
            today=date(2026, 10, 16),
        )

        self.assertEqual(result["failed"], 2)
        self.assertFalse(Job.objects.exists())

    def test_repeated_listings_update_instead_of_duplicating(self):
        first = save_brightspyre_jobs([self.row], today=date(2026, 10, 16))
        second = save_brightspyre_jobs([self.row], today=date(2026, 10, 16))

        self.assertEqual(first["new"], 1)
        self.assertEqual(second["updated"], 1)
        self.assertEqual(Job.objects.count(), 1)


class RemoteOkParsingTests(TestCase):

    def setUp(self):
        self.rows = parse_remoteok_jobs([
            {"legal": "API metadata is not a job"},
            {
                "id": "123",
                "position": "Senior Python Developer",
                "company": "Example Co",
                "location": "Worldwide",
                "salary_min": 90000,
                "salary_max": 120000,
                "date": "2026-10-15T08:00:17+00:00",
                "tags": ["python", "full-time"],
                "url": "https://remoteok.com/remote-jobs/123-example",
                "description": "<p>Build <strong>Python</strong> services.</p>",
            },
        ])

    def test_metadata_is_skipped_and_existing_job_fields_are_extracted(self):
        self.assertEqual(len(self.rows), 1)
        self.assertEqual(self.rows[0]["title"], "Senior Python Developer")
        self.assertEqual(self.rows[0]["company"], "Example Co")
        self.assertEqual(self.rows[0]["location"], "Worldwide")
        self.assertEqual(self.rows[0]["salary"], "USD 90,000 - 120,000")
        self.assertEqual(self.rows[0]["job_type"], "Full-time")
        self.assertEqual(self.rows[0]["skills"], ["python", "full-time"])
        self.assertEqual(self.rows[0]["description"], "Build Python services.")
        self.assertEqual(self.rows[0]["experience"], "")
        self.assertEqual(self.rows[0]["education"], "")

    def test_zero_salary_is_not_reported_as_a_salary(self):
        rows = parse_remoteok_jobs([
            {
                "position": "Developer",
                "salary_min": 0,
                "salary_max": 0,
                "url": "https://remoteok.com/remote-jobs/123-example",
            },
        ])

        self.assertEqual(rows[0]["salary"], "")

    def test_non_list_api_response_fails_explicitly(self):
        with self.assertRaises(ValueError):
            parse_remoteok_jobs({"error": "not a jobs list"})


class RemoteOkSavingTests(TestCase):

    def setUp(self):
        self.row = parse_remoteok_jobs([
            {
                "position": "Senior Python Developer",
                "company": "Example Co",
                "location": "Worldwide",
                "salary_min": 90000,
                "salary_max": 120000,
                "date": "2026-10-15",
                "tags": ["python", "full-time"],
                "url": "https://remoteok.com/remote-jobs/123-example",
                "description": "<p>Build Python services.</p>",
            },
        ])[0]

    def test_jobs_are_saved_with_remoteok_source_and_existing_fields(self):
        result = save_remoteok_jobs([self.row])

        job = Job.objects.get()
        self.assertEqual(result, {
            "found": 1, "new": 1, "updated": 0, "failed": 0,
        })
        self.assertEqual(job.source, "remoteok")
        self.assertEqual(job.title, "Senior Python Developer")
        self.assertEqual(job.salary_min, None)
        self.assertEqual(job.skills, ["python", "full-time"])

    def test_scraping_the_same_listing_updates_instead_of_duplicating(self):
        first = save_remoteok_jobs([self.row])
        second = save_remoteok_jobs([self.row])

        self.assertEqual(first["new"], 1)
        self.assertEqual(second["updated"], 1)
        self.assertEqual(Job.objects.count(), 1)

    def test_invalid_remote_url_does_not_save_a_job(self):
        row = dict(self.row, job_link="https://example.com/job")

        result = save_remoteok_jobs([row])

        self.assertEqual(result["failed"], 1)
        self.assertFalse(Job.objects.exists())

    def test_remoteok_is_registered_for_dashboard_search_and_auto_refresh(self):
        from . import refresh

        self.assertIn("remoteok", dict(Job.SOURCE_CHOICES))
        self.assertEqual(refresh.SCRAPER_COMMANDS["remoteok"], "scrape_remoteok")
        self.assertIn("remoteok", refresh.AUTO_SOURCES)


class PpscSavingTests(TestCase):

    def setUp(self):
        self.rows = parse_ppsc_table(ppsc_fixture())

    def test_title_longer_than_old_field_capacity_is_saved_without_truncation(self):
        long_title = "PUBLIC HEALTH SPECIALIST " * 12
        self.rows[0]["title"] = long_title

        result = save_ppsc_jobs([self.rows[0]])

        self.assertEqual(result, {
            "found": 1, "new": 1, "updated": 0, "failed": 0,
        })
        self.assertEqual(Job.objects.get().title, long_title.strip())

    def test_invalid_advertisements_do_not_discard_valid_rows(self):
        invalid_title = dict(self.rows[1], title="x" * 501)
        invalid_link = dict(self.rows[2], job_link="")

        result = save_ppsc_jobs([self.rows[0], invalid_title, invalid_link])

        self.assertEqual(result, {
            "found": 3, "new": 1, "updated": 0, "failed": 2,
        })
        self.assertEqual(Job.objects.count(), 1)

    def test_repeated_advertisements_update_the_existing_job(self):
        first = save_ppsc_jobs([self.rows[0]])
        second = save_ppsc_jobs([self.rows[0]])

        self.assertEqual(first["new"], 1)
        self.assertEqual(second["new"], 0)
        self.assertEqual(second["updated"], 1)
        self.assertEqual(Job.objects.count(), 1)

    def test_malformed_advertisement_is_counted_and_logged(self):
        malformed = dict(self.rows[0], title="")

        with self.assertLogs("jobs.management.commands.scrape_ppsc", level="WARNING"):
            result = save_ppsc_jobs([malformed])

        self.assertEqual(result["failed"], 1)
        self.assertEqual(Job.objects.count(), 0)

    def test_table_fields_are_mapped_without_misusing_title_or_salary(self):
        row = self.rows[0]

        self.assertEqual(row["title"], "ASSISTANT DIRECTOR (ENVIRONMENTAL LEGISLATION) (CLIMATE POLICY AND TECHNOLOGY CENTER)")
        self.assertTrue(row["company"].startswith("PUNJAB ENVIRONMENT"))
        self.assertEqual(row["posted"], "06-09-2026")
        self.assertEqual(row["salary"], "")
        self.assertIn("Application fee: Rs. 600", row["description"])
        self.assertIn("Closing date: 21-09-2026", row["description"])

    def test_command_records_discovered_saved_and_failed_counts(self):
        with mock.patch(
            "jobs.management.commands.scrape_ppsc.fetch",
            return_value=ppsc_fixture(),
        ):
            call_command("scrape_ppsc", verbosity=0)

        run = ScrapeRun.objects.get(source="ppsc")
        self.assertEqual(run.status, "success")
        self.assertEqual(run.jobs_found, 3)
        self.assertEqual(run.jobs_saved, 3)
        self.assertEqual(run.jobs_updated, 0)
        self.assertEqual(run.jobs_failed, 0)
        self.assertIsNotNone(run.finished_at)


    def test_ppsc_dashboard_displays_latest_run_time_status_and_counts(self):
        run = ScrapeRun.objects.create(
            source="ppsc",
            status="success",
            jobs_found=8,
            jobs_saved=3,
            jobs_updated=5,
        )
        ScrapeRun.objects.filter(pk=run.pk).update(
            started_at=timezone.now() - timedelta(hours=2, minutes=19)
        )

        html = render_to_string(
            "dashboard/admin_dashboard.html",
            {
                "scraper_runs": refresh.last_run_by_source(),
                "active_section": "scraper",
            },
        )
        ppsc_card = html.split("<h3>PPSC</h3>", 1)[1].split("</div>", 1)[0]

        self.assertRegex(
            ppsc_card,
            re.compile(
                r"Last run\s+2\s+hours,\s*19\s+minutes ago\s*&middot;\s*"
                r"succeeded,\s*3 new"
            ),
        )
        self.assertNotIn("8 found", ppsc_card)
        self.assertNotIn("Oct ", ppsc_card)

    def test_manual_run_of_another_scraper_records_its_latest_status(self):
        request = RequestFactory().post("/dashboard/admin/run-scraper/mustakbil/")
        request.user = SimpleNamespace(is_authenticated=True)
        request._messages = mock.Mock()

        def save_test_job(command):
            self.assertEqual(command, "scrape_mustakbil")
            Job.objects.create(
                title="New test listing",
                source="mustakbil",
                job_link="https://example.com/jobs/new-test-listing",
            )

        with (
            mock.patch("jobs.views.Profile.objects.get", return_value=SimpleNamespace(role="admin")),
            mock.patch.object(refresh, "_default_runner", side_effect=save_test_job),
        ):
            response = run_scraper(request, "mustakbil")

        self.assertEqual(response.status_code, 302)
        run = ScrapeRun.objects.get(source="mustakbil")
        self.assertEqual(run.status, "success")
        self.assertEqual(run.jobs_saved, 1)
        self.assertIsNotNone(run.finished_at)
        self.assertNotIn("mustakbil", refresh.sources_due(["mustakbil"]))
        self.assertFalse(ScraperSchedule.objects.exists())
