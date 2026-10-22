"""Tests for the scheduled job refresh.

The refresh has to hold three properties, and each is easy to get wrong
in a way that only shows up in production:

1.  It must not run two scrapes at once. Two web workers handling
    requests at the same moment would otherwise both decide a refresh
    is due and both start one.
2.  A crashed run must not wedge it forever. The lock expires.
3.  It must never break a page. It is triggered from a middleware on
    ordinary requests, so any failure in it has to stay invisible to
    the visitor.
"""

import logging
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from django.contrib.auth.models import User

from .models import Job, Profile, ScrapeRun, ScrapeLock
from .models import ScraperSchedule
from . import refresh


class SourcesDueTests(TestCase):

    def test_default_scraper_interval_is_24_hours(self):
        self.assertEqual(refresh.DEFAULT_INTERVAL, timedelta(hours=24))

    def test_a_source_that_has_never_run_is_due(self):
        self.assertIn("njp", refresh.sources_due(["njp"]))

    def test_a_source_scraped_just_now_is_not_due(self):
        ScrapeRun.objects.create(
            source="njp", status="success", finished_at=timezone.now()
        )

        self.assertEqual(refresh.sources_due(["njp"]), [])

    def test_a_source_is_not_due_until_the_full_interval_has_elapsed(self):
        now = timezone.now().replace(microsecond=0)
        run = ScrapeRun.objects.create(
            source="njp", status="success", finished_at=now
        )

        ScrapeRun.objects.filter(pk=run.pk).update(
            finished_at=now - timedelta(hours=24) + timedelta(seconds=1)
        )

        self.assertEqual(
            refresh.sources_due(
                ["njp"], interval=timedelta(hours=24), now=now
            ),
            [],
        )

        ScrapeRun.objects.filter(pk=run.pk).update(
            finished_at=now - timedelta(hours=24)
        )
        self.assertEqual(
            refresh.sources_due(
                ["njp"], interval=timedelta(hours=24), now=now
            ),
            ["njp"],
        )

    def test_a_failed_run_starts_the_automatic_cooldown(self):
        now = timezone.now()
        ScrapeRun.objects.create(
            source="njp", status="failed", finished_at=now
        )

        self.assertEqual(
            refresh.sources_due(
                ["njp"], interval=timedelta(hours=24), now=now
            ),
            [],
        )

    def test_sources_are_considered_independently(self):
        ScrapeRun.objects.create(
            source="njp", status="success", finished_at=timezone.now()
        )

        self.assertEqual(refresh.sources_due(["njp", "ppsc"]), ["ppsc"])

    def test_every_registered_scraper_runs_automatically(self):
        self.assertEqual(set(refresh.AUTO_SOURCES), set(refresh.SCRAPER_COMMANDS))

    def test_every_automatic_source_has_a_command(self):
        for source in refresh.AUTO_SOURCES:
            self.assertIn(source, refresh.SCRAPER_COMMANDS)


class AutomaticBatchScheduleTests(TestCase):

    def test_the_whole_batch_is_due_before_its_first_run(self):
        self.assertTrue(refresh.automatic_batch_due())

    def test_the_whole_batch_is_not_due_until_24_hours_after_completion(self):
        now = timezone.now().replace(microsecond=0)
        ScraperSchedule.objects.create(
            last_completed_at=now - timedelta(hours=24) + timedelta(seconds=1)
        )

        self.assertFalse(refresh.automatic_batch_due(now=now))
        self.assertTrue(
            refresh.automatic_batch_due(
                now=now + timedelta(seconds=1)
            )
        )

    def test_a_due_batch_runs_all_sources_and_records_one_shared_timestamp(self):
        ScrapeRun.objects.create(
            source="njp", status="success", finished_at=timezone.now()
        )
        called = []

        def record_command(command):
            schedule = ScraperSchedule.objects.get(key="automatic")
            self.assertGreater(schedule.next_allowed_at, timezone.now())
            called.append(command)

        summary = refresh.run_refresh(
            automatic_batch=True,
            runner=record_command,
        )

        self.assertTrue(summary["started"])
        self.assertEqual(
            called,
            [refresh.SCRAPER_COMMANDS[source] for source in refresh.AUTO_SOURCES],
        )
        self.assertIsNotNone(
            ScraperSchedule.objects.get(key="automatic").last_completed_at
        )
        self.assertGreater(
            ScraperSchedule.objects.get(key="automatic").next_allowed_at,
            timezone.now(),
        )

    def test_batch_does_not_start_before_its_shared_cooldown(self):
        ScraperSchedule.objects.create(last_completed_at=timezone.now())
        called = []

        summary = refresh.run_refresh(
            automatic_batch=True,
            runner=called.append,
        )

        self.assertFalse(summary["started"])
        self.assertIn("cooldown", summary["reason"])
        self.assertEqual(called, [])


class LockTests(TestCase):

    def test_the_lock_can_be_taken_when_free(self):
        self.assertTrue(refresh.acquire_lock())

    def test_a_second_attempt_is_refused_while_it_is_held(self):
        refresh.acquire_lock()

        self.assertFalse(refresh.acquire_lock())

    def test_releasing_it_lets_the_next_caller_take_it(self):
        refresh.acquire_lock()
        refresh.release_lock()

        self.assertTrue(refresh.acquire_lock())

    def test_an_expired_lock_is_taken_over(self):
        # A run whose process was killed leaves the lock held. It has to
        # time out, or the refresh never happens again.
        refresh.acquire_lock(ttl=timedelta(seconds=-1))

        self.assertTrue(refresh.acquire_lock())

    def test_the_lock_is_a_single_row(self):
        refresh.acquire_lock()
        refresh.release_lock()
        refresh.acquire_lock()

        self.assertEqual(ScrapeLock.objects.count(), 1)


class RunRefreshTests(TestCase):

    def setUp(self):
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_each_source_gets_a_recorded_run(self):
        refresh.run_refresh(["njp", "ppsc"], runner=lambda command: None)

        self.assertEqual(
            sorted(ScrapeRun.objects.values_list("source", flat=True)),
            ["njp", "ppsc"],
        )

    def test_a_successful_run_is_recorded_as_such(self):
        refresh.run_refresh(["njp"], runner=lambda command: None)

        run = ScrapeRun.objects.get()

        self.assertEqual(run.status, "success")
        self.assertIsNotNone(run.finished_at)

    def test_the_command_for_each_source_is_the_one_that_runs(self):
        called = []

        refresh.run_refresh(["njp", "ppsc"], runner=called.append)

        self.assertEqual(called, ["scrape_njp", "scrape_ppsc"])

    def test_the_number_of_new_jobs_is_recorded(self):
        def runner(command):
            Job.objects.create(title="Fresh", source="njp", job_link="x")

        refresh.run_refresh(["njp"], runner=runner)

        self.assertEqual(ScrapeRun.objects.get().jobs_saved, 1)

    def test_a_failing_scraper_is_recorded_as_failed_with_its_error(self):
        def runner(command):
            raise RuntimeError("site unreachable")

        refresh.run_refresh(["njp"], runner=runner)

        run = ScrapeRun.objects.get()

        self.assertEqual(run.status, "failed")
        self.assertIn("site unreachable", run.message)

    def test_one_failing_scraper_does_not_stop_the_others(self):
        def runner(command):
            if command == "scrape_njp":
                raise RuntimeError("nope")

        refresh.run_refresh(["njp", "ppsc"], runner=runner)

        self.assertEqual(
            ScrapeRun.objects.get(source="ppsc").status, "success"
        )

    def test_a_source_that_is_not_due_is_skipped(self):
        ScrapeRun.objects.create(
            source="njp", status="success", finished_at=timezone.now()
        )

        called = []
        refresh.run_refresh(["njp"], runner=called.append)

        self.assertEqual(called, [])

    def test_force_runs_a_source_that_is_not_due(self):
        ScrapeRun.objects.create(
            source="njp", status="success", finished_at=timezone.now()
        )

        called = []
        refresh.run_refresh(["njp"], runner=called.append, force=True)

        self.assertEqual(called, ["scrape_njp"])

    def test_a_refresh_will_not_start_while_another_holds_the_lock(self):
        refresh.acquire_lock()

        called = []
        refresh.run_refresh(["njp"], runner=called.append)

        self.assertEqual(called, [])

    def test_the_lock_is_released_even_when_a_scraper_explodes(self):
        def runner(command):
            raise RuntimeError("boom")

        refresh.run_refresh(["njp"], runner=runner)

        self.assertTrue(refresh.acquire_lock())

    def test_an_unknown_source_is_ignored_rather_than_crashing(self):
        called = []
        refresh.run_refresh(["not_a_source"], runner=called.append)

        self.assertEqual(called, [])


# =========================================================
# THE TRAFFIC TRIGGER
# =========================================================

@override_settings(JOB_REFRESH_ENABLED=True)
class RefreshMiddlewareTests(TestCase):

    def setUp(self):
        refresh.reset_trigger_throttle()
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_a_page_view_starts_a_refresh_when_one_is_due(self):
        with mock.patch.object(refresh, "spawn_refresh") as spawn:
            self.client.get(reverse("home"))

        spawn.assert_called_once()

    def test_no_refresh_is_started_when_nothing_is_due(self):
        ScraperSchedule.objects.create(last_completed_at=timezone.now())

        with mock.patch.object(refresh, "spawn_refresh") as spawn:
            self.client.get(reverse("home"))

        spawn.assert_not_called()

    def test_the_database_is_not_consulted_on_every_single_request(self):
        # Without the throttle this would ask "is anything due?" on every
        # asset and page view; the answer cannot change that fast.
        with mock.patch.object(refresh, "spawn_refresh"):
            with mock.patch.object(
                refresh, "automatic_batch_due", return_value=False
            ) as due:
                self.client.get(reverse("home"))
                self.client.get(reverse("home"))
                self.client.get(reverse("home"))

        self.assertEqual(due.call_count, 1)

    @override_settings(JOB_REFRESH_ENABLED=False)
    def test_the_trigger_can_be_switched_off(self):
        with mock.patch.object(refresh, "spawn_refresh") as spawn:
            self.client.get(reverse("home"))

        spawn.assert_not_called()

    def test_a_broken_refresh_never_breaks_the_page(self):
        with mock.patch.object(
            refresh, "maybe_start_refresh", side_effect=RuntimeError("kaboom")
        ):
            response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)


class LastRunReportTests(TestCase):

    def test_it_reports_the_most_recent_run_per_source(self):
        old = ScrapeRun.objects.create(
            source="njp", status="success", finished_at=timezone.now(), jobs_saved=1
        )
        ScrapeRun.objects.filter(pk=old.pk).update(
            started_at=timezone.now() - timedelta(days=2)
        )

        ScrapeRun.objects.create(
            source="njp", status="success", finished_at=timezone.now(), jobs_saved=9
        )

        report = refresh.last_run_by_source()

        self.assertEqual(report["njp"].jobs_saved, 9)

    def test_a_source_never_run_is_absent_from_the_report(self):
        self.assertNotIn("ppsc", refresh.last_run_by_source())


# =========================================================
# THE MANAGEMENT COMMAND
# =========================================================
#
# Same entry point as the traffic trigger, so a cron line and a page
# view produce identical behaviour.

class RefreshJobsCommandTests(TestCase):

    def call(self, *args, **options):
        out = StringIO()
        call_command("refresh_jobs", *args, stdout=out, stderr=out, **options)
        return out.getvalue()

    def test_it_refreshes_all_sources_by_default(self):
        with mock.patch.object(refresh, "run_refresh") as run:
            run.return_value = {"started": True, "reason": "", "results": {}}
            self.call()

        self.assertEqual(run.call_args.kwargs["sources"], list(refresh.AUTO_SOURCES))
        self.assertIs(run.call_args.kwargs["automatic_batch"], True)

    def test_named_sources_override_the_default_set(self):
        with mock.patch.object(refresh, "run_refresh") as run:
            run.return_value = {"started": True, "reason": "", "results": {}}
            self.call("--sources", "njp,ppsc")

        self.assertEqual(run.call_args.kwargs["sources"], ["njp", "ppsc"])

    def test_force_is_passed_through(self):
        with mock.patch.object(refresh, "run_refresh") as run:
            run.return_value = {"started": True, "reason": "", "results": {}}
            self.call("--force")

        self.assertIs(run.call_args.kwargs["force"], True)

    def test_it_says_so_when_nothing_needed_doing(self):
        ScraperSchedule.objects.create(last_completed_at=timezone.now())

        self.assertIn("nothing due", self.call().lower())

    def test_it_reports_what_each_source_did(self):
        with mock.patch.object(refresh, "_default_runner"):
            output = self.call("--sources", "njp", "--force")

        self.assertIn("njp", output)
        self.assertIn("success", output.lower())


class AdminScraperPanelTests(TestCase):
    """Every scraper must stay listed on the admin panel.

    A regex used to remove the Glassdoor card once took the Mustakbil
    card with it, and nothing noticed, because no test knew what was
    supposed to be there.
    """

    def setUp(self):
        self.admin = User.objects.create_user(
            username="boss", email="boss@example.com", password="Secret!1"
        )
        Profile.objects.filter(user=self.admin).update(role="admin")
        self.client.force_login(self.admin)

    def test_every_scraper_has_a_run_button(self):
        response = self.client.get(reverse("admin_dashboard"))

        for source in refresh.SCRAPER_COMMANDS:
            self.assertContains(
                response,
                reverse("run_scraper", args=[source]),
                msg_prefix=f"missing Run button for {source}",
            )

    def test_indeed_scraper_is_not_registered_or_shown(self):
        response = self.client.get(reverse("admin_dashboard"))

        self.assertNotIn("indeed", refresh.SCRAPER_COMMANDS)
        self.assertNotIn("indeed", dict(Job.SOURCE_CHOICES))
        self.assertNotContains(response, "Indeed")
        with self.assertRaises(CommandError):
            call_command("scrape_indeed")

    def test_remoteok_has_a_visible_scraper_card(self):
        response = self.client.get(reverse("admin_dashboard"))

        self.assertContains(response, "<h3>Remote OK</h3>", html=True)
        self.assertContains(
            response,
            reverse("run_scraper", args=["remoteok"]),
        )

    def test_remoteok_is_listed_in_the_superadmin_panel_too(self):
        Profile.objects.filter(user=self.admin).update(role="superadmin")
        response = self.client.get(reverse("superadmin_dashboard"))

        self.assertContains(response, "<h3>Remote OK</h3>", html=True)
        self.assertContains(
            response,
            reverse("run_scraper", args=["remoteok"]),
        )

    def test_brightspyre_has_a_run_button_and_is_listed_in_the_superadmin_panel(self):
        response = self.client.get(reverse("admin_dashboard"))
        self.assertContains(response, "<h3>BrightSpyre</h3>", html=True)
        self.assertContains(
            response,
            reverse("run_scraper", args=["brightspyre"]),
        )

        Profile.objects.filter(user=self.admin).update(role="superadmin")
        response = self.client.get(reverse("superadmin_dashboard"))
        self.assertContains(response, "<h3>BrightSpyre</h3>", html=True)
        self.assertContains(
            response,
            reverse("run_scraper", args=["brightspyre"]),
        )

    def test_a_source_never_run_says_so(self):
        response = self.client.get(reverse("admin_dashboard"))

        self.assertContains(response, "Never run")

    def test_the_last_run_is_shown_once_a_source_has_run(self):
        ScrapeRun.objects.create(
            source="njp", status="success",
            finished_at=timezone.now(), jobs_saved=7,
        )

        response = self.client.get(reverse("admin_dashboard"))

        self.assertContains(response, "7 new")
        self.assertContains(response, "scraper-status__dot--success")

    def test_a_failed_run_is_visible_rather_than_silent(self):
        ScrapeRun.objects.create(
            source="njp", status="failed",
            finished_at=timezone.now(), message="boom",
        )

        response = self.client.get(reverse("admin_dashboard"))

        self.assertContains(response, "scraper-status__dot--failed")
