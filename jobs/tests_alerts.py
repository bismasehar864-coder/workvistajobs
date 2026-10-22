"""Job alerts: spotting a new job that suits someone, and telling them.

A job seeker sets their skills, title and location, sees nothing today,
and tomorrow the scrapers bring in exactly the right job - which nobody
mentions. These tests cover the part that notices, and the two ways it
says so: the bell in the dashboard, and a daily digest email.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import CVData, Job, Notification
from .alerts.matching import (
    alert_score,
    job_match_details,
    location_score,
    normalize_skill,
    skill_score,
)


def make_seeker(
    username="ayesha",
    email="ayesha@example.com",
    skills=("python", "django"),
    job_title="Django Developer",
    location="Lahore",
):
    """A job seeker with preferences set - the only kind who gets alerts."""

    user = User.objects.create_user(
        username=username, email=email, password="Secret!1"
    )
    user.first_name = "Ayesha Khan"
    user.save()

    # Through the cached instance the post_save signal attached, not a
    # queryset update, so profile reads afterwards aren't stale.
    profile = user.profile
    profile.skills = list(skills)
    profile.job_title = job_title
    profile.location = location
    profile.save()

    return user, profile


def make_job(title="Django Developer", **kwargs):
    defaults = {
        "company": "Galixo",
        "location": "Lahore",
        "description": "",
        "source": "workvista",
        "skills": [],
    }
    defaults.update(kwargs)

    return Job.objects.create(title=title, **defaults)


class SkillScoreTests(TestCase):

    def test_a_skill_named_in_the_description_counts(self):
        job = make_job(title="Backend Engineer", description="We use Python daily.")

        self.assertEqual(skill_score({"python"}, job), 100)

    def test_a_skill_named_in_the_title_counts(self):
        job = make_job(title="Senior Django Developer")

        self.assertEqual(skill_score({"django"}, job), 100)

    def test_a_skill_in_the_jobs_own_skills_list_counts(self):
        job = make_job(title="Engineer", skills=["Machine Learning"])

        self.assertEqual(skill_score({"machine learning"}, job), 100)

    def test_it_scores_the_fraction_of_the_users_skills_the_job_mentions(self):
        job = make_job(title="Django Developer", description="Django and Postgres.")

        # python is not mentioned; django is. One of two.
        self.assertEqual(skill_score({"python", "django"}, job), 50)

    def test_a_long_job_description_is_not_penalised(self):
        """The job listing twenty things it wants doesn't dilute the fact
        that it wants the two this user has."""

        job = make_job(
            title="Engineer",
            description="python django " + " ".join(f"thing{n}" for n in range(20)),
        )

        self.assertEqual(skill_score({"python", "django"}, job), 100)

    def test_a_partial_word_is_not_a_match(self):
        job = make_job(title="Engineer", description="We use Javascript.")

        self.assertEqual(skill_score({"java"}, job), 0)

    def test_a_one_letter_skill_is_ignored(self):
        """"R" or "C" matches a word boundary in nearly every description."""

        job = make_job(title="Engineer", description="Grade C candidates welcome.")

        self.assertEqual(skill_score({"c"}, job), 0)

    def test_common_skill_aliases_match_and_normalize(self):
        job = make_job(title="Frontend Engineer", description="We use React.")

        self.assertEqual(normalize_skill(" ReactJS "), "react")
        self.assertEqual(skill_score({"ReactJS"}, job), 100)

    def test_no_user_skills_scores_zero(self):
        self.assertEqual(skill_score(set(), make_job()), 0)


class LocationScoreTests(TestCase):

    def test_the_same_city_scores_full(self):
        self.assertEqual(location_score("Lahore", "Lahore, Pakistan"), 100)

    def test_a_different_city_scores_nothing(self):
        self.assertEqual(location_score("Lahore", "Karachi"), 0)

    def test_a_remote_job_suits_everyone(self):
        self.assertEqual(location_score("Lahore", "Remote"), 100)
        self.assertEqual(location_score("Karachi", "Remote/Worldwide"), 100)
        self.assertEqual(location_score("Lahore", "Work from home"), 100)

    def test_no_stated_location_scores_nothing(self):
        self.assertEqual(location_score("", "Lahore"), 0)


class AlertScoreTests(TestCase):
    """The worked table from the design, asserted row by row."""

    def setUp(self):
        _, self.profile = make_seeker()
        self.skills = {"python", "django"}

    def score(self, **job_kwargs):
        return alert_score(self.skills, self.profile, make_job(**job_kwargs))

    def test_a_direct_hit(self):
        self.assertEqual(
            self.score(title="Senior Django Developer", location="Lahore"), 135
        )

    def test_a_remote_job_on_skills_alone(self):
        self.assertEqual(
            self.score(title="Python Engineer", location="Remote"), 110
        )

    def test_the_right_role_in_the_wrong_city(self):
        self.assertEqual(
            self.score(title="Django Developer", location="Karachi"), 125
        )

    def test_location_alone_never_triggers(self):
        """Otherwise someone who set only "Lahore" hears about every
        Lahore job there will ever be."""

        self.assertEqual(
            self.score(title="Graphic Designer", location="Lahore"), 0
        )

    def test_a_remote_job_in_the_wrong_field_never_triggers(self):
        self.assertEqual(
            self.score(title="Senior Accountant", location="Remote"), 0
        )

class AlertScoreWithPartialPreferencesTests(TestCase):

    def test_a_user_with_only_a_title_cannot_match(self):
        """A title by itself must never make a notification eligible."""

        _, profile = make_seeker(skills=(), location="")

        score = alert_score(set(), profile, make_job(title="Django Developer"))

        self.assertEqual(score, 0)

    def test_a_user_with_only_skills_is_scored_out_of_a_hundred(self):
        _, profile = make_seeker(job_title="", location="")

        score = alert_score(
            {"python", "django"}, profile, make_job(title="Django Developer")
        )

        self.assertEqual(score, 100)

    def test_a_user_with_no_preferences_at_all_scores_zero(self):
        _, profile = make_seeker(skills=(), job_title="", location="")

        self.assertEqual(alert_score(set(), profile, make_job()), 0)


# =========================================================
# THE NOTIFICATION RECORD
# =========================================================

class NotificationModelTests(TestCase):

    def setUp(self):
        self.user, self.profile = make_seeker()
        self.job = make_job()

    def test_a_user_reaches_their_notifications(self):
        note = Notification.objects.create(
            user=self.user, job=self.job, title="New match"
        )

        self.assertEqual(list(self.user.notifications.all()), [note])

    def test_the_same_job_cannot_be_notified_twice(self):
        from django.db.utils import IntegrityError

        Notification.objects.create(user=self.user, job=self.job, title="New match")

        with self.assertRaises(IntegrityError):
            Notification.objects.create(
                user=self.user, job=self.job, title="New match again"
            )

    def test_deleting_the_job_removes_the_notification(self):
        Notification.objects.create(user=self.user, job=self.job, title="New match")

        self.job.delete()

        self.assertEqual(Notification.objects.count(), 0)

    def test_a_new_notification_is_unread_and_unemailed(self):
        note = Notification.objects.create(
            user=self.user, job=self.job, title="New match"
        )

        self.assertIsNone(note.read_at)
        self.assertIsNone(note.emailed_at)

    def test_the_newest_comes_first(self):
        older = make_job(title="Older")
        newer = make_job(title="Newer")

        Notification.objects.create(user=self.user, job=older, title="Older")
        Notification.objects.create(user=self.user, job=newer, title="Newer")

        self.assertEqual(
            [n.title for n in Notification.objects.all()], ["Newer", "Older"]
        )


class ProfileAlertFieldTests(TestCase):

    def test_email_alerts_are_on_by_default(self):
        _, profile = make_seeker()

        self.assertTrue(profile.email_job_alerts)

    def test_a_new_profile_has_never_been_checked(self):
        _, profile = make_seeker()

        self.assertIsNone(profile.alerts_checked_at)


# =========================================================
# SPOTTING THE MATCHES
# =========================================================

from .alerts.notifications import generate_notifications, notify_job_matches


class GenerateNotificationTests(TestCase):

    def setUp(self):
        self.user, self.profile = make_seeker()
        self.now = timezone.now()

        # Already checked an hour ago, so only jobs newer than that are
        # new to this user.
        self.profile.alerts_checked_at = self.now - timedelta(hours=1)
        self.profile.save()

    def age(self, job, **delta):
        """first_seen_at is auto_now_add, so it can only be moved with
        an update() that bypasses the field's auto behaviour."""

        Job.objects.filter(id=job.id).update(
            first_seen_at=self.now - timedelta(**delta)
        )

        job.refresh_from_db()
        return job

    def test_a_matching_new_job_creates_one_notification(self):
        make_job(title="Senior Django Developer", location="Lahore")

        created = generate_notifications(now=self.now)

        self.assertEqual(created, 1)
        note = Notification.objects.get()
        self.assertEqual(note.user, self.user)
        self.assertEqual(note.title, "Senior Django Developer")
        self.assertEqual(note.score, 135)

    def test_a_job_that_does_not_match_creates_nothing(self):
        make_job(title="Graphic Designer", location="Lahore")

        self.assertEqual(generate_notifications(now=self.now), 0)

    def test_running_twice_does_not_notify_twice(self):
        make_job(title="Senior Django Developer", location="Lahore")

        generate_notifications(now=self.now)
        second = generate_notifications(now=self.now + timedelta(minutes=1))

        self.assertEqual(second, 0)
        self.assertEqual(Notification.objects.count(), 1)

    def test_a_job_older_than_the_watermark_is_ignored(self):
        job = make_job(title="Senior Django Developer", location="Lahore")
        self.age(job, hours=5)

        self.assertEqual(generate_notifications(now=self.now), 0)

    def test_the_watermark_advances_even_when_nothing_matched(self):
        """Otherwise an unlucky user rescans the same empty window forever."""

        generate_notifications(now=self.now)

        self.profile.refresh_from_db()

        self.assertEqual(self.profile.alerts_checked_at, self.now)

    def test_a_missed_run_is_caught_up_by_the_next_one(self):
        self.profile.alerts_checked_at = self.now - timedelta(days=3)
        self.profile.save()

        job = make_job(title="Senior Django Developer", location="Lahore")
        self.age(job, days=2)

        self.assertEqual(generate_notifications(now=self.now), 1)

    def test_a_user_never_checked_looks_back_one_day_not_forever(self):
        self.profile.alerts_checked_at = None
        self.profile.save()

        recent = make_job(title="Senior Django Developer", location="Lahore")
        self.age(recent, hours=3)

        ancient = make_job(title="Django Developer", location="Lahore")
        self.age(ancient, days=40)

        generate_notifications(now=self.now)

        self.assertEqual(
            [n.title for n in Notification.objects.all()],
            ["Senior Django Developer"],
        )

    def test_an_employer_is_never_scanned(self):
        from .models import Company

        employer = User.objects.create_user(
            username="hirer", email="hirer@example.com", password="Secret!1"
        )
        profile = employer.profile
        profile.role = "employer"
        profile.job_title = "Django Developer"
        profile.location = "Lahore"
        profile.save()
        Company.objects.create(owner=employer, name="Galixo", location="Lahore")

        make_job(title="Senior Django Developer", location="Lahore")

        generate_notifications(now=self.now)

        self.assertFalse(Notification.objects.filter(user=employer).exists())

    def test_a_user_with_no_skills_or_title_is_never_scanned(self):
        _, bare = make_seeker(
            username="bare", email="bare@example.com",
            skills=(), job_title="", location="Lahore",
        )

        make_job(title="Senior Django Developer", location="Lahore")

        generate_notifications(now=self.now)

        self.assertFalse(Notification.objects.filter(user=bare.user).exists())

    def test_cv_skills_count_as_well_as_profile_skills(self):
        _, profile = make_seeker(
            username="cvonly", email="cvonly@example.com",
            skills=(), job_title="", location="Lahore",
        )
        CVData.objects.create(user=profile.user, skills=["python"])

        make_job(title="Python Engineer", location="Lahore")

        generate_notifications(now=self.now)

        self.assertTrue(Notification.objects.filter(user=profile.user).exists())

    def test_the_notification_says_where_the_job_is(self):
        make_job(
            title="Senior Django Developer", company="Galixo", location="Lahore"
        )

        generate_notifications(now=self.now)

        self.assertEqual(
            Notification.objects.get().body,
            "Galixo · Lahore · Matched",
        )

    def test_a_skill_match_alone_is_enough_to_notify(self):
        self.profile.job_title = ""
        self.profile.location = ""
        self.profile.save()
        make_job(title="Python Engineer")

        self.assertEqual(generate_notifications(now=self.now), 1)
        self.assertEqual(Notification.objects.get().body, "Galixo · Lahore · Matched")

    def test_bulk_generation_queues_email_only_after_commit(self):
        from unittest.mock import patch
        from django.test import override_settings

        make_job(title="Senior Django Developer", location="Lahore")

        with override_settings(JOB_ALERTS_ENABLED=True):
            with patch("jobs.alerts.digest.spawn_notification_emails") as spawn:
                with self.captureOnCommitCallbacks(execute=True):
                    self.assertEqual(generate_notifications(now=self.now), 1)

        note = Notification.objects.get(user=self.user)
        spawn.assert_called_once_with((note.pk,))
        self.assertIsNone(note.emailed_at)

    def test_a_title_match_without_a_skill_match_does_not_notify(self):
        self.profile.skills = ["python"]
        self.profile.save()
        make_job(
            title="Django Developer",
            description="",
            skills=[],
        )

        self.assertEqual(generate_notifications(now=self.now), 0)
        self.assertFalse(Notification.objects.exists())

    def test_job_type_and_salary_are_reported_as_other_matches(self):
        self.profile.job_type = ["Full-time"]
        self.profile.salary = 90000
        self.profile.save()
        job = make_job(
            title="Python Engineer",
            job_type="Full-time",
            salary="PKR 90000 /month",
        )

        score, fields = job_match_details({"python"}, self.profile, job)

        self.assertEqual(score, 120)
        self.assertEqual(fields, ("Skills", "Location", "Job type", "Salary"))

    def test_more_skill_matches_outrank_optional_preference_matches(self):
        self.profile.skills = ["python", "django"]
        self.profile.job_title = "Product Manager"
        self.profile.job_type = ["Full-time"]
        self.profile.salary = 90000
        self.profile.save()

        broad_skill_match = make_job(
            title="Engineer",
            description="Python and Django",
            location="Karachi",
        )
        single_skill_match = make_job(
            title="Product Manager",
            description="Python",
            location="Lahore",
            job_type="Full-time",
            salary="PKR 90000 /month",
        )

        broad_score, _ = job_match_details(
            {"python", "django"}, self.profile, broad_skill_match
        )
        single_score, _ = job_match_details(
            {"python", "django"}, self.profile, single_skill_match
        )

        self.assertGreater(broad_score, single_score)

    def test_missing_optional_fields_do_not_prevent_a_skill_match(self):
        self.profile.job_title = None
        self.profile.location = None
        self.profile.salary = None
        self.profile.job_type = []
        self.profile.save()
        job = make_job(title="Python Engineer")

        score, fields = job_match_details({"python"}, self.profile, job)

        self.assertEqual(score, 100)
        self.assertEqual(fields, ("Skills",))


class PublishedJobNotificationTests(TestCase):

    def setUp(self):
        self.user, self.profile = make_seeker()
        self.job = make_job(
            title="Senior Django Developer",
            description="Python and Django",
            is_approved=True,
        )

    def test_a_newly_published_match_queues_email_without_sending_inline(self):
        from django.core import mail
        from unittest.mock import patch
        from django.test import override_settings

        with override_settings(JOB_ALERTS_ENABLED=True):
            with patch("jobs.alerts.digest.spawn_notification_emails") as spawn:
                with self.captureOnCommitCallbacks(execute=True):
                    self.assertEqual(notify_job_matches(self.job), 1)

        notification = Notification.objects.get(user=self.user, job=self.job)
        self.assertEqual(notification.body, "Galixo · Lahore · Matched")
        self.assertIsNone(notification.emailed_at)
        spawn.assert_called_once_with((notification.pk,))
        self.assertEqual(len(mail.outbox), 0)

        from .alerts.digest import send_one_notification

        self.assertTrue(send_one_notification(notification))
        notification.refresh_from_db()
        self.assertIsNotNone(notification.emailed_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ayesha@example.com"])
        self.assertIn(self.job.title, mail.outbox[0].body)
        self.assertIn("Matched", mail.outbox[0].body)
        self.assertIn(f"/jobs/{self.job.id}/", mail.outbox[0].body)
        self.assertIn("/dashboard/", mail.outbox[0].body)

    def test_duplicate_publish_does_not_create_or_email_twice(self):
        from django.core import mail
        from unittest.mock import patch
        from django.test import override_settings

        with override_settings(JOB_ALERTS_ENABLED=True):
            with patch("jobs.alerts.digest.spawn_notification_emails") as spawn:
                with self.captureOnCommitCallbacks(execute=True):
                    notify_job_matches(self.job)
                spawn.reset_mock()
                with self.captureOnCommitCallbacks(execute=True):
                    self.assertEqual(notify_job_matches(self.job), 0)

        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)
        spawn.assert_not_called()
        self.assertEqual(len(mail.outbox), 0)

    def test_email_opt_out_keeps_dashboard_notification(self):
        from django.core import mail

        self.profile.email_job_alerts = False
        self.profile.save(update_fields=["email_job_alerts"])

        self.assertEqual(notify_job_matches(self.job), 1)

        notification = Notification.objects.get(user=self.user, job=self.job)
        self.assertIsNone(notification.emailed_at)
        self.assertEqual(len(mail.outbox), 0)

    def test_email_failure_does_not_interrupt_dashboard_notification(self):
        from unittest.mock import patch
        from .alerts.digest import send_one_notification

        self.assertEqual(notify_job_matches(self.job), 1)

        notification = Notification.objects.get(user=self.user, job=self.job)
        self.assertIsNone(notification.emailed_at)
        with patch(
            "django.core.mail.EmailMultiAlternatives.send",
            side_effect=OSError("smtp failed"),
        ):
            with self.assertRaises(OSError):
                send_one_notification(notification)

        notification.refresh_from_db()
        self.assertIsNone(notification.emailed_at)


# =========================================================
# THE DIGEST EMAIL
# =========================================================

from django.core import mail

from .alerts.digest import (
    send_pending_digests,
    unsubscribe_token,
    user_from_token,
)


class DigestTests(TestCase):

    def setUp(self):
        self.user, self.profile = make_seeker()
        self.job = make_job(
            title="Senior Django Developer", company="Galixo", location="Lahore"
        )
        Notification.objects.create(
            user=self.user, job=self.job, title=self.job.title,
            body="Galixo · Lahore", score=75,
        )

    def test_a_user_with_new_matches_gets_one_email(self):
        sent = send_pending_digests()

        self.assertEqual(sent, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ayesha@example.com"])
        self.assertEqual(mail.outbox[0].from_email, "WorkVista <work4vista@gmail.com>")

    def test_the_subject_counts_the_matches(self):
        send_pending_digests()

        self.assertEqual(mail.outbox[0].subject, "1 new job matches your profile")

    def test_the_subject_pluralises(self):
        second = make_job(title="Django Developer", location="Lahore")
        Notification.objects.create(
            user=self.user, job=second, title=second.title, score=55
        )

        send_pending_digests()

        self.assertEqual(mail.outbox[0].subject, "2 new jobs match your profile")

    def test_the_email_names_the_job_and_links_to_it(self):
        send_pending_digests()

        body = mail.outbox[0].body

        self.assertIn("Senior Django Developer", body)
        self.assertIn("Galixo", body)
        self.assertIn(f"/jobs/{self.job.id}/", body)
        self.assertIn("http", body)

    def test_notifications_without_a_job_still_link_to_the_dashboard(self):
        note = Notification.objects.create(
            user=self.user,
            kind="employer_job_denied",
            title="Your job was not approved",
            body="The posting was removed.",
        )

        from .alerts.digest import send_one_notification

        self.assertTrue(send_one_notification(note))
        body = mail.outbox[0].body
        self.assertIn("Your job was not approved", body)
        self.assertIn("/dashboard/", body)
        self.assertNotIn("/jobs/None/", body)

    def test_it_sends_both_a_text_and_an_html_part(self):
        send_pending_digests()

        alternatives = mail.outbox[0].alternatives

        self.assertEqual(len(alternatives), 1)
        self.assertEqual(alternatives[0][1], "text/html")
        self.assertIn("Senior Django Developer", alternatives[0][0])

    def test_everything_sent_is_stamped(self):
        send_pending_digests()

        self.assertIsNotNone(Notification.objects.get().emailed_at)

    def test_nothing_is_sent_twice(self):
        send_pending_digests()
        mail.outbox.clear()

        self.assertEqual(send_pending_digests(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_user_who_turned_email_off_gets_nothing(self):
        self.profile.email_job_alerts = False
        self.profile.save()

        self.assertEqual(send_pending_digests(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_user_with_no_address_gets_nothing(self):
        self.user.email = ""
        self.user.save()

        self.assertEqual(send_pending_digests(), 0)

    def test_a_user_with_no_new_matches_gets_nothing(self):
        Notification.objects.update(emailed_at=timezone.now())

        self.assertEqual(send_pending_digests(), 0)

    def test_read_notifications_are_still_emailed(self):
        """Reading it in the bell is not a reason to drop it from the
        digest - the two channels are independent."""

        Notification.objects.update(read_at=timezone.now())

        self.assertEqual(send_pending_digests(), 1)

    def test_the_footer_carries_a_working_unsubscribe_link(self):
        send_pending_digests()

        self.assertIn(
            f"/alerts/unsubscribe/{unsubscribe_token(self.user)}/",
            mail.outbox[0].body,
        )


class DigestFailureTests(TestCase):

    def test_one_bad_recipient_does_not_stop_the_others(self):
        from unittest.mock import patch

        first, _ = make_seeker(username="a", email="a@example.com")
        second, _ = make_seeker(username="b", email="b@example.com")

        for user in (first, second):
            job = make_job(title=f"Django Developer for {user.username}")
            Notification.objects.create(user=user, job=job, title=job.title)

        real_send = mail.EmailMultiAlternatives.send

        def explode_for_a(self, *args, **kwargs):
            if self.to == ["a@example.com"]:
                raise OSError("smtp exploded")
            return real_send(self, *args, **kwargs)

        with patch.object(mail.EmailMultiAlternatives, "send", explode_for_a):
            sent = send_pending_digests()

        self.assertEqual(sent, 1)
        self.assertIsNone(Notification.objects.get(user=first).emailed_at)
        self.assertIsNotNone(Notification.objects.get(user=second).emailed_at)


class UnsubscribeTokenTests(TestCase):

    def test_a_token_round_trips_to_its_user(self):
        user, _ = make_seeker()

        self.assertEqual(user_from_token(unsubscribe_token(user)), user)

    def test_a_tampered_token_resolves_to_nobody(self):
        user, _ = make_seeker()

        token = unsubscribe_token(user)

        self.assertIsNone(user_from_token(token[:-4] + "xxxx"))
        self.assertIsNone(user_from_token("not-a-token"))

    def test_a_token_for_a_deleted_user_resolves_to_nobody(self):
        user, _ = make_seeker()
        token = unsubscribe_token(user)

        user.delete()

        self.assertIsNone(user_from_token(token))


# =========================================================
# TURNING EMAIL OFF
# =========================================================

from django.urls import reverse


class UnsubscribeViewTests(TestCase):

    def setUp(self):
        self.user, self.profile = make_seeker()

    def url_for(self, token):
        return reverse("alerts_unsubscribe", args=[token])

    def test_a_valid_link_turns_email_alerts_off_without_a_login(self):
        response = self.client.get(self.url_for(unsubscribe_token(self.user)))

        self.profile.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.profile.email_job_alerts)

    def test_it_says_so(self):
        response = self.client.get(self.url_for(unsubscribe_token(self.user)))

        self.assertContains(response, "won't email you")

    def test_a_tampered_link_changes_nothing_and_does_not_blow_up(self):
        response = self.client.get(self.url_for("clearly-not-a-real-token"))

        self.profile.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.profile.email_job_alerts)
        self.assertContains(response, "isn't valid")

    def test_unsubscribing_twice_is_harmless(self):
        token = unsubscribe_token(self.user)

        self.client.get(self.url_for(token))
        response = self.client.get(self.url_for(token))

        self.profile.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.profile.email_job_alerts)

    def test_it_leaves_the_bell_alone(self):
        """Turning off email is not turning off notifications."""

        job = make_job(title="Senior Django Developer")
        Notification.objects.create(user=self.user, job=job, title=job.title)

        self.client.get(self.url_for(unsubscribe_token(self.user)))

        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)


# The bell and its dropdown were replaced by a Notifications section
# with the count on the sidebar entry - a dropdown had no room to show
# a job properly. Those tests live in jobs/tests_settings.py now.


# =========================================================
# RUNNING IT
# =========================================================

from io import StringIO

from django.core.management import call_command
from django.test import override_settings


class SendJobAlertsCommandTests(TestCase):

    def setUp(self):
        self.user, self.profile = make_seeker()
        self.profile.alerts_checked_at = timezone.now() - timedelta(hours=1)
        self.profile.save()

        make_job(title="Senior Django Developer", location="Lahore")

    def test_it_matches_and_sends_in_one_go(self):
        out = StringIO()

        call_command("send_job_alerts", stdout=out)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("1 notification", out.getvalue())
        self.assertIn("1 email", out.getvalue())

    def test_dry_run_sends_nothing_and_stamps_nothing(self):
        out = StringIO()

        call_command("send_job_alerts", "--dry-run", stdout=out)

        self.assertEqual(len(mail.outbox), 0)
        self.assertIn("would email", out.getvalue())
        self.assertFalse(
            Notification.objects.filter(emailed_at__isnull=False).exists()
        )

    def test_skip_matching_only_sends_what_is_already_there(self):
        job = make_job(title="Django Developer", location="Karachi")
        Notification.objects.create(user=self.user, job=job, title=job.title)

        call_command("send_job_alerts", "--skip-matching")

        # The one pre-existing notification, and nothing newly matched.
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)


class DigestTrafficFallbackTests(TestCase):

    def setUp(self):
        from jobs import refresh

        refresh.reset_digest_throttle()

    def test_it_is_off_while_alerts_are_disabled(self):
        from jobs import refresh

        with override_settings(JOB_ALERTS_ENABLED=False):
            self.assertFalse(refresh.maybe_send_digests())

    @override_settings(JOB_ALERTS_ENABLED=True)
    def test_it_fires_once_and_then_holds_off(self):
        from unittest.mock import patch
        from jobs import refresh

        with patch.object(refresh, "spawn_digest") as spawn:
            first = refresh.maybe_send_digests()
            second = refresh.maybe_send_digests()

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(spawn.call_count, 1)
