"""The Settings and Notifications sections of the job-seeker dashboard.

Job preferences used to live on My Profile, mixed in with the CV and
the account email. Preferences are not identity - they are how the site
behaves for you - so they moved to Settings, next to the job alerts
switch that acts on them.

Notifications used to be a dropdown off a bell in the top bar. A
dropdown cannot show a job properly, so they moved to a section of
their own, and the sidebar entry carries the unread count.
"""

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from unittest.mock import patch
import tempfile

from bs4 import BeautifulSoup

from .models import Company, Job, Notification


def make_seeker(username="ayesha", email="ayesha@example.com"):
    user = User.objects.create_user(
        username=username, email=email, password="Secret!1"
    )
    user.first_name = "Ayesha Khan"
    user.save()

    profile = user.profile
    profile.job_title = "Django Developer"
    profile.location = "Lahore"
    profile.save()

    return user, profile


def make_job(title="Senior Django Developer", **kwargs):
    defaults = {
        "company": "Galixo",
        "location": "Lahore",
        "source": "workvista",
        "skills": [],
    }
    defaults.update(kwargs)
    return Job.objects.create(title=title, **defaults)


def sidebar_entries(response):
    """Every sidebar link, as (id, visible text)."""

    soup = BeautifulSoup(response.content.decode(), "html.parser")

    return [
        (a.get("id"), " ".join(a.get_text().split()))
        for a in soup.select(".sidebar ul li a")
    ]


# =========================================================
# THE SIDEBAR
# =========================================================

class SidebarTests(TestCase):

    def setUp(self):
        self.user, self.profile = make_seeker()
        self.client.force_login(self.user)

    def test_it_offers_notifications_and_settings(self):
        entries = dict(sidebar_entries(self.client.get(reverse("dashboard_profile"))))

        self.assertIn("nav-notifications", entries)
        self.assertIn("nav-settings", entries)

    def test_the_badge_counts_unread_matches(self):
        for n in range(3):
            Notification.objects.create(
                user=self.user, job=make_job(title=f"Role {n}"), title=f"Role {n}"
            )

        response = self.client.get(reverse("dashboard_profile"))

        self.assertContains(response, 'class="nav-badge"')
        self.assertContains(response, ">3<")

    def test_no_badge_when_nothing_is_unread(self):
        response = self.client.get(reverse("dashboard_profile"))

        self.assertNotContains(response, 'class="nav-badge"')

    def test_the_old_top_bar_bell_is_gone(self):
        response = self.client.get(reverse("dashboard_profile"))

        self.assertNotContains(response, "notification-bell")
        self.assertNotContains(response, "bell-panel")

    def test_an_employer_sees_notifications_but_not_job_seeker_settings(self):
        employer = User.objects.create_user(
            username="hirer", email="hirer@example.com", password="Secret!1"
        )
        p = employer.profile
        p.role = "employer"
        p.save()
        Company.objects.create(owner=employer, name="Galixo", location="Lahore")

        self.client.force_login(employer)

        entries = dict(sidebar_entries(self.client.get(reverse("employer_company"))))

        self.assertIn("nav-notifications", entries)
        self.assertNotIn("nav-settings", entries)


# =========================================================
# THE NOTIFICATIONS SECTION
# =========================================================

class NotificationsPageTests(TestCase):

    def setUp(self):
        self.user, self.profile = make_seeker()
        self.client.force_login(self.user)
        self.job = make_job(salary="$70,000 - $110,000")
        self.note = Notification.objects.create(
            user=self.user, job=self.job, title=self.job.title,
            body="Galixo · Lahore · Matched: Skills", score=92,
        )

    def test_it_shows_the_match_with_its_detail(self):
        response = self.client.get(reverse("dashboard_notifications"))

        self.assertContains(response, "Senior Django Developer")
        self.assertContains(response, "Galixo")
        self.assertContains(response, "$70,000 - $110,000")
        self.assertContains(response, "Matched")
        self.assertNotContains(response, "Matched: Skills")
        self.assertNotContains(response, "Skills")
        self.note.refresh_from_db()
        self.assertEqual(self.note.score, 92)

    def test_every_job_match_shows_matched_even_when_body_is_empty(self):
        self.note.body = ""
        self.note.save(update_fields=["body"])

        response = self.client.get(reverse("dashboard_notifications"))

        soup = BeautifulSoup(response.content.decode(), "html.parser")
        meta = " ".join(soup.select_one(".notification-meta").get_text().split())
        self.assertEqual(meta, "Galixo · Lahore · Matched")

    def test_it_links_through_to_the_job(self):
        response = self.client.get(reverse("dashboard_notifications"))

        self.assertContains(response, reverse("job_detail", args=[self.job.id]))

    def test_visiting_clears_the_badge(self):
        self.client.get(reverse("dashboard_notifications"))

        self.note.refresh_from_db()

        self.assertIsNotNone(self.note.read_at)

        later = self.client.get(reverse("dashboard_profile"))

        self.assertNotContains(later, 'class="nav-badge"')

    def test_what_was_unread_is_still_marked_on_the_visit_that_clears_it(self):
        """Otherwise opening the page erases the very thing you came to see."""

        response = self.client.get(reverse("dashboard_notifications"))

        self.assertContains(response, "notification-card--new")

    def test_a_second_visit_marks_nothing_as_new(self):
        self.client.get(reverse("dashboard_notifications"))

        response = self.client.get(reverse("dashboard_notifications"))

        self.assertNotContains(response, "notification-card--new")

    def test_it_shows_only_your_own_matches(self):
        rival, _ = make_seeker(username="rival", email="rival@example.com")
        Notification.objects.create(
            user=rival, job=make_job(title="Theirs"), title="Theirs"
        )

        response = self.client.get(reverse("dashboard_notifications"))

        self.assertNotContains(response, "Theirs")

    def test_it_marks_its_own_sidebar_entry(self):
        response = self.client.get(reverse("dashboard_notifications"))
        soup = BeautifulSoup(response.content.decode(), "html.parser")

        active = [
            a.get("id") for a in soup.select(".sidebar ul li a")
            if "active" in (a.get("class") or [])
        ]

        self.assertEqual(active, ["nav-notifications"])

    def test_the_best_match_in_a_batch_comes_first(self):
        """One scrape's worth of matches all share a timestamp, so the
        list must rank them by strength - not by which row the database
        happened to insert last."""

        from jobs.alerts.notifications import generate_notifications

        Notification.objects.all().delete()
        self.profile.skills = ["python", "django"]
        self.profile.alerts_checked_at = None
        self.profile.save()

        make_job(title="Python Backend Engineer", company="Vyro", location="Remote")
        make_job(title="Django Developer", company="Systems", location="Karachi")

        generate_notifications()

        response = self.client.get(reverse("dashboard_notifications"))
        scores = [n.score for n in response.context["notifications"]]

        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_newer_notifications_come_before_older_higher_scoring_ones(self):
        from datetime import timedelta
        from django.utils import timezone

        older = self.note
        older.created_at = timezone.now() - timedelta(days=1)
        older.save(update_fields=["created_at"])
        newer_job = make_job(title="New Python Engineer")
        newer = Notification.objects.create(
            user=self.user,
            job=newer_job,
            title=newer_job.title,
            score=10,
            created_at=timezone.now(),
        )

        response = self.client.get(reverse("dashboard_notifications"))
        notifications = response.context["notifications"]

        self.assertEqual([note.pk for note in notifications[:2]], [newer.pk, older.pk])

    def test_an_empty_page_points_at_settings(self):
        Notification.objects.all().delete()

        response = self.client.get(reverse("dashboard_notifications"))

        self.assertContains(response, "No matches yet")
        self.assertContains(response, reverse("dashboard_settings"))

    def test_it_is_private(self):
        self.client.logout()

        response = self.client.get(reverse("dashboard_notifications"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("signin"), response["Location"])


# =========================================================
# THE SETTINGS SECTION
# =========================================================

class SettingsPageTests(TestCase):

    def setUp(self):
        self.user, self.profile = make_seeker()
        self.client.force_login(self.user)

    def test_it_shows_the_current_preferences(self):
        response = self.client.get(reverse("dashboard_settings"))

        self.assertContains(response, 'value="Django Developer"')
        self.assertContains(response, 'value="Lahore"')

    def test_it_offers_the_alerts_switch(self):
        response = self.client.get(reverse("dashboard_settings"))

        self.assertContains(response, 'name="email_job_alerts"')
        self.assertContains(response, "switch")

    def test_saving_preferences_stores_them_and_returns_here(self):
        response = self.client.post(
            reverse("dashboard_settings"),
            {
                "update_preferences": "1",
                "job_title": "Backend Engineer",
                "location": "Karachi",
                "job_type": ["Remote", "Full-time"],
            },
        )

        self.profile.refresh_from_db()

        self.assertEqual(self.profile.job_title, "Backend Engineer")
        self.assertEqual(self.profile.location, "Karachi")
        self.assertEqual(sorted(self.profile.job_type), ["Full-time", "Remote"])
        self.assertRedirects(response, reverse("dashboard_settings"))

    def test_job_title_accepts_commas_slashes_and_hyphens(self):
        title = "Senior Engineer, Data/AI - Remote"
        response = self.client.post(
            reverse("dashboard_settings"),
            {"update_preferences": "1", "job_title": title},
        )

        self.profile.refresh_from_db()

        self.assertEqual(self.profile.job_title, title)
        self.assertRedirects(response, reverse("dashboard_settings"))

    def test_location_accepts_commas_and_spaces(self):
        response = self.client.post(
            reverse("dashboard_settings"),
            {
                "update_preferences": "1",
                "job_title": "Backend Engineer",
                "location": "Lahore, Karachi",
            },
        )

        self.profile.refresh_from_db()

        self.assertEqual(self.profile.location, "Lahore, Karachi")
        self.assertRedirects(response, reverse("dashboard_settings"))

    def test_a_blank_job_title_is_refused(self):
        response = self.client.post(
            reverse("dashboard_settings"),
            {"update_preferences": "1", "job_title": "  ", "location": "Karachi"},
        )

        self.profile.refresh_from_db()

        self.assertEqual(self.profile.job_title, "Django Developer")
        self.assertRedirects(response, reverse("dashboard_settings"))

    def test_invalid_preference_text_is_rejected_without_saving(self):
        for key, value, expected_error in (
            ("job_title", "Developer 2", "Only alphabets, commas, / and - are allowed."),
            ("location", "Lahore!", "Only alphabets and commas are allowed."),
            ("job_title", "Backend Engineer\n", "Only alphabets, commas, / and - are allowed."),
            ("job_title", "Backend Engineer & Data", "Only alphabets, commas, / and - are allowed."),
        ):
            with self.subTest(field=key):
                response = self.client.post(
                    reverse("dashboard_settings"),
                    {
                        "update_preferences": "1",
                        "job_title": "Backend Engineer",
                        "location": "Karachi",
                        key: value,
                    },
                    follow=True,
                )

                self.profile.refresh_from_db()
                self.assertContains(response, expected_error)
                self.assertEqual(self.profile.job_title, "Django Developer")
                self.assertEqual(self.profile.location, "Lahore")

    def test_optional_preference_location_can_be_empty_and_values_are_trimmed(self):
        response = self.client.post(
            reverse("dashboard_settings"),
            {
                "update_preferences": "1",
                "job_title": "  Backend Engineer  ",
                "location": "   ",
            },
        )

        self.profile.refresh_from_db()

        self.assertRedirects(response, reverse("dashboard_settings"))
        self.assertEqual(self.profile.job_title, "Backend Engineer")
        self.assertEqual(self.profile.location, "")

    def test_saving_preferences_does_not_touch_the_alerts_switch(self):
        """The switch is its own form. Saving preferences must not
        silently unsubscribe someone because a checkbox wasn't posted."""

        self.assertTrue(self.profile.email_job_alerts)

        self.client.post(
            reverse("dashboard_settings"),
            {"update_preferences": "1", "job_title": "Django Developer"},
        )

        self.profile.refresh_from_db()

        self.assertTrue(self.profile.email_job_alerts)

    def test_flipping_the_switch_off_saves(self):
        response = self.client.post(
            reverse("dashboard_settings"), {"update_alerts": "1"}
        )

        self.profile.refresh_from_db()

        self.assertFalse(self.profile.email_job_alerts)
        self.assertRedirects(response, reverse("dashboard_settings"))

    def test_flipping_the_switch_on_saves(self):
        self.profile.email_job_alerts = False
        self.profile.save()

        self.client.post(
            reverse("dashboard_settings"),
            {"update_alerts": "1", "email_job_alerts": "1"},
        )

        self.profile.refresh_from_db()

        self.assertTrue(self.profile.email_job_alerts)

    def test_the_switch_never_touches_notifications(self):
        job = make_job()
        Notification.objects.create(user=self.user, job=job, title=job.title)

        self.client.post(reverse("dashboard_settings"), {"update_alerts": "1"})

        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)

    def test_an_unrecognised_post_changes_nothing(self):
        self.client.post(reverse("dashboard_settings"), {"something": "else"})

        self.profile.refresh_from_db()

        self.assertEqual(self.profile.job_title, "Django Developer")
        self.assertTrue(self.profile.email_job_alerts)

    def test_it_marks_its_own_sidebar_entry(self):
        response = self.client.get(reverse("dashboard_settings"))
        soup = BeautifulSoup(response.content.decode(), "html.parser")

        active = [
            a.get("id") for a in soup.select(".sidebar ul li a")
            if "active" in (a.get("class") or [])
        ]

        self.assertEqual(active, ["nav-settings"])

    def test_it_is_private(self):
        self.client.logout()

        response = self.client.get(reverse("dashboard_settings"))

        self.assertEqual(response.status_code, 302)


class ProfileNoLongerHoldsPreferencesTests(TestCase):

    def setUp(self):
        self.user, self.profile = make_seeker()
        self.client.force_login(self.user)

    def test_the_profile_no_longer_shows_the_preferences_form(self):
        response = self.client.get(reverse("dashboard_profile"))

        self.assertNotContains(response, 'name="update_preferences"')

    def test_the_profile_points_at_settings_instead(self):
        response = self.client.get(reverse("dashboard_profile"))

        self.assertContains(response, reverse("dashboard_settings"))

    def test_the_profile_still_shows_the_cv_and_account(self):
        response = self.client.get(reverse("dashboard_profile"))

        self.assertContains(response, 'name="update_cv"')
        self.assertContains(response, 'name="update_email"')


class EditProfilePageTests(TestCase):

    def setUp(self):
        self.user, self.profile = make_seeker()
        self.client.force_login(self.user)

    def edit_data(self, **overrides):
        data = {
            "full_name": "Ayesha New Name",
            "email": "ayesha@example.com",
            "job_title": "Backend Engineer",
            "location": "Karachi",
            "salary": "95000",
            "salary_currency": "USD",
            "skills": "Python, Django, SQL",
            "job_type": ["Remote", "Full-time"],
        }
        data.update(overrides)
        return data

    def test_get_prefills_values_and_marks_edit_profile_active(self):
        response = self.client.get(reverse("edit_profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="Ayesha Khan"')
        self.assertContains(response, 'value="ayesha@example.com"')
        self.assertContains(response, 'id="nav-edit-profile"')
        self.assertContains(response, 'enctype="multipart/form-data"')
        self.assertContains(response, 'name="new_password"')
        self.assertContains(response, 'name="confirm_password"')
        self.assertContains(response, 'class="toggle-password"')
    def test_saving_updates_user_and_profile_then_returns_to_profile(self):
        response = self.client.post(reverse("edit_profile"), self.edit_data())

        self.user.refresh_from_db()
        self.profile.refresh_from_db()

        self.assertEqual(self.user.first_name, "Ayesha New Name")
        self.assertEqual(self.user.email, "ayesha@example.com")
        self.assertEqual(self.user.username, "ayesha")
        self.assertEqual(self.profile.job_title, "Backend Engineer")
        self.assertEqual(self.profile.location, "Karachi")
        self.assertEqual(self.profile.salary, 95000)
        self.assertEqual(self.profile.salary_currency, "USD")
        self.assertEqual(self.profile.skills, ["Python", "Django", "SQL"])
        self.assertEqual(sorted(self.profile.job_type), ["Full-time", "Remote"])
        self.assertRedirects(response, reverse("dashboard_profile"))

    def test_password_can_be_changed_without_logging_out(self):
        response = self.client.post(
            reverse("edit_profile"),
            self.edit_data(
                new_password="N3w-unique-Password!42",
                confirm_password="N3w-unique-Password!42",
            ),
            follow=True,
        )

        self.user.refresh_from_db()

        self.assertTrue(self.user.check_password("N3w-unique-Password!42"))
        self.assertTrue(response.wsgi_request.user.is_authenticated)
        self.assertRedirects(response, reverse("dashboard_profile"))

    def test_blank_password_fields_do_not_change_the_password(self):
        original_hash = self.user.password

        response = self.client.post(reverse("edit_profile"), self.edit_data())

        self.user.refresh_from_db()

        self.assertEqual(self.user.password, original_hash)
        self.assertRedirects(response, reverse("dashboard_profile"))

    def test_mismatched_passwords_are_rejected(self):
        response = self.client.post(
            reverse("edit_profile"),
            self.edit_data(
                new_password="N3w-unique-Password!42",
                confirm_password="Different-Password!43",
            ),
        )

        self.user.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The passwords do not match.")
        self.assertFalse(self.user.check_password("N3w-unique-Password!42"))

    def test_invalid_scoped_profile_text_is_rejected(self):
        cases = (
            ("full_name", "Ayesha 2", "Only alphabets are allowed"),
            ("job_title", "Backend Engineer!", "Only alphabets are allowed"),
            ("location", "Karachi 2", "Only alphabets and commas are allowed."),
        )
        for field, value, error_message in cases:
            with self.subTest(field=field):
                response = self.client.post(
                    reverse("edit_profile"),
                    self.edit_data(**{field: value}),
                )

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, error_message)
                self.user.refresh_from_db()
                self.profile.refresh_from_db()
                self.assertEqual(self.user.first_name, "Ayesha Khan")
                self.assertEqual(self.profile.job_title, "Django Developer")

    def test_profile_location_accepts_alphabets_spaces_and_commas(self):
        response = self.client.post(
            reverse("edit_profile"),
            self.edit_data(location="Lahore, Karachi"),
        )

        self.profile.refresh_from_db()

        self.assertRedirects(response, reverse("dashboard_profile"))
        self.assertEqual(self.profile.location, "Lahore, Karachi")

    def test_skills_accept_digits_and_special_characters(self):
        response = self.client.post(
            reverse("edit_profile"),
            self.edit_data(skills="C++, C#; Node.js 2.0"),
        )

        self.profile.refresh_from_db()

        self.assertRedirects(response, reverse("dashboard_profile"))
        self.assertEqual(self.profile.skills, ["C++", "C#; Node.js 2.0"])

    def test_optional_profile_text_fields_can_be_empty(self):
        response = self.client.post(
            reverse("edit_profile"),
            self.edit_data(job_title="  ", location=" ", skills=" "),
        )

        self.profile.refresh_from_db()

        self.assertRedirects(response, reverse("dashboard_profile"))
        self.assertIsNone(self.profile.job_title)
        self.assertIsNone(self.profile.location)
        self.assertEqual(self.profile.skills, [])

    def test_empty_file_submission_preserves_existing_cv(self):
        self.profile.cv = "cvs/current-resume.pdf"
        self.profile.save(update_fields=["cv"])

        self.client.post(reverse("edit_profile"), self.edit_data())

        self.profile.refresh_from_db()

        self.assertEqual(self.profile.cv.name, "cvs/current-resume.pdf")

    def test_duplicate_email_is_rejected_without_saving_other_changes(self):
        make_seeker(username="another", email="taken@example.com")

        response = self.client.post(
            reverse("edit_profile"),
            self.edit_data(email="taken@example.com"),
        )

        self.user.refresh_from_db()
        self.profile.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "An account with this email already exists.")
        self.assertEqual(self.user.email, "ayesha@example.com")
        self.assertEqual(self.profile.job_title, "Django Developer")

    def test_post_cannot_edit_another_users_profile(self):
        other_user, other_profile = make_seeker(
            username="another", email="another@example.com"
        )

        self.client.post(
            reverse("edit_profile"),
            self.edit_data(user_id=other_user.pk),
        )

        other_user.refresh_from_db()
        other_profile.refresh_from_db()

        self.assertEqual(other_user.first_name, "Ayesha Khan")
        self.assertEqual(other_profile.job_title, "Django Developer")

    def test_login_is_required(self):
        self.client.logout()

        response = self.client.get(reverse("edit_profile"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("signin"), response["Location"])

    def test_replacing_cv_runs_existing_resume_parser(self):
        temporary_media = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_media.cleanup)
        media_settings = override_settings(MEDIA_ROOT=temporary_media.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)

        with (
            patch("jobs.views_settings.extract_cv_text", return_value="resume text"),
            patch("jobs.views_settings.is_valid_cv", return_value=True),
            patch("jobs.views_settings.parse_resume", return_value={"skills": ["Python"]}),
        ):
            data = self.edit_data()
            data["cv"] = SimpleUploadedFile("resume.pdf", b"pdf content")
            response = self.client.post(
                reverse("edit_profile"),
                data,
            )

        self.profile.refresh_from_db()

        self.assertRedirects(response, reverse("dashboard_profile"))
        self.assertTrue(self.profile.cv.name.startswith("cvs/resume"))
