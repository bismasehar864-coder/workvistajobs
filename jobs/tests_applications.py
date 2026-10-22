from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Application, Job


class ApplicationTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="applicant",
            email="applicant@example.com",
            password="Secret!1",
        )
        self.other_user = User.objects.create_user(
            username="another",
            email="another@example.com",
            password="Secret!1",
        )
        self.job = Job.objects.create(
            title="Django Developer",
            company="WorkVista",
            location="Lahore",
            source="workvista",
            job_link="https://example.com/apply",
        )
        self.client.force_login(self.user)

    def test_application_is_created_and_confirmation_stays_on_workvista(self):
        response = self.client.post(
            reverse("apply_job", args=[self.job.id]),
            {"next": reverse("job_detail", args=[self.job.id])},
            follow=True,
        )

        self.assertEqual(Application.objects.count(), 1)
        application = Application.objects.get()
        self.assertEqual(application.user, self.user)
        self.assertEqual(application.job, self.job)
        self.assertIsNotNone(application.applied_at)
        self.assertContains(response, "You have successfully applied for this job.")
        self.assertContains(response, "Already Applied")
        self.assertContains(
            response,
            f'href="{self.job.job_link}" target="_blank"',
        )

    def test_duplicate_application_shows_message_without_creating_another_row(self):
        Application.objects.create(user=self.user, job=self.job)

        response = self.client.post(
            reverse("apply_job", args=[self.job.id]),
            {"next": reverse("job_detail", args=[self.job.id])},
            follow=True,
        )

        self.assertEqual(Application.objects.count(), 1)
        self.assertContains(response, "You have already applied for this job.")
        self.assertContains(response, "Already Applied")

    def test_apply_endpoint_rejects_get(self):
        response = self.client.get(reverse("apply_job", args=[self.job.id]))

        self.assertEqual(response.status_code, 405)
        self.assertFalse(Application.objects.exists())

    def test_applied_jobs_are_private_to_the_current_user(self):
        Application.objects.create(user=self.user, job=self.job)
        other_job = Job.objects.create(
            title="Private to another user",
            source="mustakbil",
        )
        Application.objects.create(user=self.other_user, job=other_job)

        response = self.client.get(reverse("applied_jobs"))

        self.assertContains(response, "Django Developer")
        self.assertNotContains(response, "Private to another user")
        self.assertEqual(
            list(response.context["applications"].values_list("user_id", flat=True)),
            [self.user.id],
        )

    def test_applied_jobs_page_requires_login(self):
        self.client.logout()

        response = self.client.get(reverse("applied_jobs"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("signin"), response["Location"])

    def test_sidebar_links_to_applied_jobs(self):
        response = self.client.get(reverse("dashboard_profile"))

        self.assertContains(response, f'href="{reverse("applied_jobs")}"')