"""The employer account type: signing up, the company profile, and posting.

WorkVista used to have one kind of member, and anyone at all could post
a job. Posting belongs to companies, so members now choose at signup
whether they are looking for work or hiring, and only the second kind
can post. The role is stored on the account, which is why signing in
never asks again.
"""

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from .models import (
    Application,
    Company,
    CompanyBranch,
    Job,
    Notification,
    Profile,
    SavedJob,
    UserActivity,
)


def make_employer(
    username="hirer",
    email="hirer@example.com",
    fullname="Sana Iqbal",
    company_name="Galixo",
    company_location="Lahore",
):
    """An employer account with its company, the way signup builds one."""

    user = User.objects.create_user(
        username=username, email=email, password="Secret!1"
    )
    user.first_name = fullname
    user.save()

    # Set through the instance the post_save signal already attached to
    # `user`, not with a queryset update - that would leave the cached
    # user.profile stale and every is_employer check reading "user".
    profile = user.profile
    profile.role = "employer"
    profile.save()

    company = Company.objects.create(
        owner=user,
        name=company_name,
        location=company_location,
    )

    return user, company


class CompanyModelTests(TestCase):

    def test_an_employer_reaches_their_company_as_user_company(self):
        user, company = make_employer()

        self.assertEqual(user.company, company)

    def test_a_company_reaches_its_branches(self):
        _, company = make_employer()

        branch = CompanyBranch.objects.create(
            company=company, name="Karachi office", location="Karachi"
        )

        self.assertEqual(list(company.branches.all()), [branch])

    def test_deleting_a_branch_keeps_the_jobs_posted_from_it(self):
        user, company = make_employer()

        branch = CompanyBranch.objects.create(
            company=company, name="Karachi office", location="Karachi"
        )

        job = Job.objects.create(
            title="Django Developer",
            source="workvista",
            posted_by=user,
            branch=branch,
        )

        branch.delete()
        job.refresh_from_db()

        self.assertIsNone(job.branch)
        self.assertTrue(Job.objects.filter(id=job.id).exists())

    def test_two_branches_of_one_company_cannot_share_a_name(self):
        from django.db.utils import IntegrityError

        _, company = make_employer()

        CompanyBranch.objects.create(
            company=company, name="Karachi office", location="Karachi"
        )

        with self.assertRaises(IntegrityError):
            CompanyBranch.objects.create(
                company=company, name="Karachi office", location="Korangi"
            )


class RoleHelperTests(TestCase):

    def test_an_employer_profile_knows_it_is_an_employer(self):
        user, _ = make_employer()

        self.assertTrue(user.profile.is_employer)
        self.assertFalse(user.profile.is_job_seeker)

    def test_a_new_account_is_a_job_seeker(self):
        user = User.objects.create_user(
            username="seeker", email="seeker@example.com", password="Secret!1"
        )

        self.assertTrue(user.profile.is_job_seeker)
        self.assertFalse(user.profile.is_employer)

    def test_employer_is_one_of_the_offered_roles(self):
        self.assertIn(("employer", "Employer"), Profile.ROLE_CHOICES)


# =========================================================
# THE EMPLOYER GATE
# =========================================================

from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory

from .roles import employer_required


@employer_required
def _sample_view(request):
    return HttpResponse("posted")


class EmployerRequiredTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()

    def test_an_anonymous_visitor_is_sent_to_sign_in_carrying_where_they_were(self):
        request = self.factory.get("/dashboard/employer/post-job/")
        request.user = AnonymousUser()

        response = _sample_view(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            f"{reverse('signin')}?next=/dashboard/employer/post-job/",
        )

    def test_an_employee_is_told_why_rather_than_bounced(self):
        user = User.objects.create_user(
            username="seeker", email="seeker@example.com", password="Secret!1"
        )

        request = self.factory.get("/dashboard/employer/post-job/")
        request.user = user

        response = _sample_view(request)

        self.assertEqual(response.status_code, 403)
        self.assertIn("employer", response.content.decode().lower())

    def test_an_employer_is_let_through(self):
        user, _ = make_employer()

        request = self.factory.get("/dashboard/employer/post-job/")
        request.user = user

        response = _sample_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"posted")


# =========================================================
# SIGNING UP
# =========================================================

class SignupChooserTests(TestCase):

    def test_the_chooser_offers_both_paths(self):
        response = self.client.get(reverse("signup"))

        self.assertContains(response, reverse("signup_employee"))
        self.assertContains(response, reverse("signup_employer"))

    def test_the_chooser_creates_nothing(self):
        self.client.get(reverse("signup"))

        self.assertEqual(User.objects.count(), 0)

    def test_employee_signup_still_makes_a_job_seeker(self):
        response = self.client.post(
            reverse("signup_employee"),
            {
                "fullname": "Ayesha Khan",
                "email": "ayesha@example.com",
                "password": "Secret!1",
            },
        )

        user = User.objects.get(email="ayesha@example.com")

        self.assertTrue(user.profile.is_job_seeker)
        self.assertRedirects(response, reverse("cv_upload"))


def employer_signup_data(**overrides):
    """A complete employer signup POST, branch formset included."""

    data = {
        "fullname": "Sana Iqbal",
        "email": "sana@example.com",
        "password": "Secret!1",
        "company_name": "Galixo",
        "company_location": "Lahore",
        "website": "https://galixo.ai",
        "founded_year": 2019,
        "description": "We build AI products.",
        "branches-TOTAL_FORMS": "1",
        "branches-INITIAL_FORMS": "0",
        "branches-MIN_NUM_FORMS": "0",
        "branches-MAX_NUM_FORMS": "1000",
        "branches-0-name": "",
        "branches-0-location": "",
    }

    data.update(overrides)

    return data


class EmployerSignupTests(TestCase):

    def test_it_creates_an_employer_with_a_company(self):
        response = self.client.post(
            reverse("signup_employer"), employer_signup_data()
        )

        user = User.objects.get(email="sana@example.com")

        self.assertTrue(user.profile.is_employer)
        self.assertEqual(user.company.name, "Galixo")
        self.assertEqual(user.company.location, "Lahore")
        self.assertEqual(user.company.website, "https://galixo.ai")
        self.assertEqual(user.company.founded_year, 2019)
        self.assertRedirects(response, reverse("employer_company"))

    def test_it_signs_the_new_employer_in(self):
        self.client.post(reverse("signup_employer"), employer_signup_data())

        self.assertIn("_auth_user_id", self.client.session)

    def test_branch_rows_filled_in_become_branches(self):
        self.client.post(
            reverse("signup_employer"),
            employer_signup_data(**{
                "branches-TOTAL_FORMS": "2",
                "branches-0-name": "Karachi office",
                "branches-0-location": "Karachi",
                "branches-1-name": "Islamabad office",
                "branches-1-location": "Islamabad",
            }),
        )

        company = User.objects.get(email="sana@example.com").company

        self.assertEqual(
            sorted(company.branches.values_list("name", flat=True)),
            ["Islamabad office", "Karachi office"],
        )

    def test_a_blank_branch_row_is_skipped(self):
        self.client.post(reverse("signup_employer"), employer_signup_data())

        company = User.objects.get(email="sana@example.com").company

        self.assertEqual(company.branches.count(), 0)

    def test_a_half_filled_branch_row_is_rejected(self):
        response = self.client.post(
            reverse("signup_employer"),
            employer_signup_data(**{"branches-0-name": "Karachi office"}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="sana@example.com").exists())
        self.assertContains(response, "location")

    def test_a_rejected_signup_creates_no_user_at_all(self):
        response = self.client.post(
            reverse("signup_employer"),
            employer_signup_data(company_name=""),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Company.objects.count(), 0)

    def test_a_founding_year_in_the_future_is_rejected(self):
        response = self.client.post(
            reverse("signup_employer"),
            employer_signup_data(founded_year=2500),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), 0)

    def test_employers_are_not_sent_to_cv_upload(self):
        response = self.client.post(
            reverse("signup_employer"), employer_signup_data()
        )

        self.assertNotEqual(response.url, reverse("cv_upload"))


# =========================================================
# ROLE-BASED ROUTING
# =========================================================

from bs4 import BeautifulSoup


def active_sidebar_ids(response):
    """Which sidebar entries the server marked as the open one."""

    soup = BeautifulSoup(response.content.decode(), "html.parser")

    return [
        link.get("id")
        for link in soup.select(".sidebar ul li a")
        if "active" in (link.get("class") or [])
    ]


class RoleRoutingTests(TestCase):

    def test_signing_in_as_an_employer_opens_the_employer_dashboard(self):
        make_employer()

        response = self.client.post(
            reverse("signin"),
            {"email": "hirer@example.com", "password": "Secret!1"},
        )

        self.assertRedirects(
            response, reverse("employer_dashboard"), target_status_code=302
        )

    def test_signing_in_as_an_employee_still_opens_the_user_dashboard(self):
        user = User.objects.create_user(
            username="seeker", email="seeker@example.com", password="Secret!1"
        )
        user.save()

        response = self.client.post(
            reverse("signin"),
            {"email": "seeker@example.com", "password": "Secret!1"},
        )

        self.assertRedirects(
            response, reverse("user_dashboard"), fetch_redirect_response=False
        )

    def test_the_bare_dashboard_routes_an_employer_to_theirs(self):
        user, _ = make_employer()
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(
            response, reverse("employer_dashboard"), target_status_code=302
        )

    def test_an_employer_visiting_the_job_seeker_dashboard_is_sent_to_theirs(self):
        user, _ = make_employer()
        self.client.force_login(user)

        response = self.client.get(reverse("user_dashboard"))

        self.assertRedirects(
            response, reverse("employer_dashboard"), target_status_code=302
        )

    def test_an_employee_visiting_the_employer_dashboard_is_refused(self):
        user = User.objects.create_user(
            username="seeker", email="seeker@example.com", password="Secret!1"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("employer_company"))

        self.assertEqual(response.status_code, 403)

    def test_the_bare_employer_dashboard_opens_the_company_profile(self):
        user, _ = make_employer()
        self.client.force_login(user)

        response = self.client.get(reverse("employer_dashboard"))

        self.assertRedirects(response, reverse("employer_company"))


class EmployerCompanySectionTests(TestCase):

    def setUp(self):
        self.user, self.company = make_employer()
        self.client.force_login(self.user)

    def test_it_shows_the_company_details(self):
        response = self.client.get(reverse("employer_company"))

        self.assertContains(response, "Galixo")
        self.assertContains(response, "Lahore")

    def test_it_marks_its_own_sidebar_entry(self):
        response = self.client.get(reverse("employer_company"))

        self.assertEqual(active_sidebar_ids(response), ["nav-company"])

    def test_the_employer_sidebar_offers_no_job_seeker_sections(self):
        response = self.client.get(reverse("employer_company"))
        body = response.content.decode()

        self.assertNotIn("Recommended Jobs", body)
        self.assertNotIn("Trending Jobs", body)
        self.assertNotIn("Search Jobs", body)
        self.assertNotIn("Saved Jobs", body)

    def test_an_employer_can_change_their_company_details(self):
        response = self.client.post(
            reverse("employer_company"),
            {
                "name": "  Bomstart.pk  ",
                "location": "  Lahore, Pakistan  ",
                "website": "https://galixo.ai",
                "founded_year": 2019,
                "description": "We build AI products.",
            },
        )

        self.company.refresh_from_db()

        self.assertEqual(self.company.name, "Bomstart.pk")
        self.assertEqual(self.company.location, "Lahore, Pakistan")
        self.assertEqual(self.company.founded_year, 2019)
        self.assertRedirects(response, reverse("employer_company"))

    def test_company_details_reject_invalid_field_values(self):
        invalid_submissions = (
            ({"name": "X"}, "name"),
            ({"name": "1234"}, "name"),
            ({"name": "Invalid@"}, "name"),
            ({"location": "Lahore 2"}, "location"),
            ({"location": "Lahore / Pakistan"}, "location"),
            ({"website": "company.com"}, "website"),
            ({"website": "https://company.c"}, "website"),
            ({"website": "https://company.com/path with spaces"}, "website"),
            ({"founded_year": "20a6"}, "founded_year"),
            ({"founded_year": "02026"}, "founded_year"),
            ({"description": "123 !!!"}, "description"),
            ({"description": "A" * 1001}, "description"),
        )
        for values, field in invalid_submissions:
            with self.subTest(values=values):
                response = self.client.post(
                    reverse("employer_company"),
                    {
                        "name": "Galixo",
                        "location": "Lahore",
                        "website": "",
                        "founded_year": "",
                        "description": "",
                        **values,
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)

    def test_company_form_renders_inline_validation_targets(self):
        response = self.client.get(reverse("employer_company"))

        for field in ("name", "location", "website", "founded_year", "description"):
            with self.subTest(field=field):
                self.assertContains(response, f'data-client-error="{field}"')

    def test_a_founding_year_in_the_future_is_refused(self):
        response = self.client.post(
            reverse("employer_company"),
            {"name": "Galixo", "location": "Lahore", "founded_year": 2500},
        )

        self.company.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.company.founded_year)


# =========================================================
# BRANCH OFFICES
# =========================================================

class EmployerBranchTests(TestCase):

    def setUp(self):
        self.user, self.company = make_employer()
        self.client.force_login(self.user)

    def test_an_employer_can_add_a_branch(self):
        response = self.client.post(
            reverse("employer_branches"),
            {"name": "Karachi office", "location": "Karachi"},
        )

        self.assertEqual(self.company.branches.count(), 1)
        self.assertRedirects(response, reverse("employer_branches"))

    def test_the_section_lists_the_branches(self):
        CompanyBranch.objects.create(
            company=self.company, name="Karachi office", location="Karachi"
        )

        response = self.client.get(reverse("employer_branches"))

        self.assertContains(response, "Karachi office")
        self.assertEqual(active_sidebar_ids(response), ["nav-branches"])

    def test_an_employer_can_rename_a_branch(self):
        branch = CompanyBranch.objects.create(
            company=self.company, name="Karachi office", location="Karachi"
        )

        self.client.post(
            reverse("employer_branch_edit", args=[branch.id]),
            {"name": "Korangi office", "location": "Korangi, Karachi"},
        )

        branch.refresh_from_db()

        self.assertEqual(branch.name, "Korangi office")
        self.assertEqual(branch.location, "Korangi, Karachi")

    def test_an_employer_can_delete_a_branch(self):
        branch = CompanyBranch.objects.create(
            company=self.company, name="Karachi office", location="Karachi"
        )

        self.client.post(reverse("employer_branch_delete", args=[branch.id]))

        self.assertEqual(self.company.branches.count(), 0)

    def test_another_employers_branch_might_as_well_not_exist(self):
        _, rival = make_employer(
            username="rival",
            email="rival@example.com",
            company_name="Rival Ltd",
            company_location="Karachi",
        )

        branch = CompanyBranch.objects.create(
            company=rival, name="Rival HQ", location="Karachi"
        )

        response = self.client.post(
            reverse("employer_branch_edit", args=[branch.id]),
            {"name": "Stolen", "location": "Lahore"},
        )

        branch.refresh_from_db()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(branch.name, "Rival HQ")

    def test_two_branches_cannot_share_a_name(self):
        CompanyBranch.objects.create(
            company=self.company, name="Karachi office", location="Karachi"
        )

        response = self.client.post(
            reverse("employer_branches"),
            {"name": "Karachi office", "location": "Korangi"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.company.branches.count(), 1)


# =========================================================
# POSTING IS EMPLOYER-ONLY
# =========================================================

class PostingIsEmployerOnlyTests(TestCase):

    def test_an_employee_posting_a_job_is_refused_and_creates_nothing(self):
        user = User.objects.create_user(
            username="seeker", email="seeker@example.com", password="Secret!1"
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("post_job"),
            {
                "title": "Django Developer",
                "company": "Galixo",
                "location": "Lahore",
                "description": "Build things.",
                "category": "web",
                "job_type": "Full-time",
                "salary_min": 60000,
                "salary_max": 90000,
                "job_link": "https://example.com/apply",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Job.objects.count(), 0)

    def test_an_employee_opening_the_post_form_is_told_why(self):
        user = User.objects.create_user(
            username="seeker", email="seeker@example.com", password="Secret!1"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("post_job"))

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "employer", status_code=403)

    def test_an_employee_cannot_delete_a_posting(self):
        owner, _ = make_employer()

        job = Job.objects.create(
            title="Django Developer", source="workvista", posted_by=owner
        )

        seeker = User.objects.create_user(
            username="seeker", email="seeker@example.com", password="Secret!1"
        )
        self.client.force_login(seeker)

        response = self.client.post(
            reverse("delete_posted_job", args=[job.id])
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Job.objects.filter(id=job.id).exists())


class EmployeeSidebarTests(TestCase):

    def test_the_job_seeker_sidebar_no_longer_offers_post_a_job(self):
        user = User.objects.create_user(
            username="seeker", email="seeker@example.com", password="Secret!1"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard_profile"))

        self.assertNotContains(response, 'id="nav-post-job"')
        self.assertNotContains(response, "Post a Job")


# =========================================================
# WHAT A POSTING IS STAMPED WITH
# =========================================================

def post_payload(**overrides):
    """A valid posting for an employer. No company or location: those
    are stamped from the employer's own company, never submitted."""

    data = {
        "title": "Django Developer",
        "branch": "",
        "description": "Build and maintain Django services.",
        "category": "technology",
        "job_type": "Full-time",
        "salary_currency": "PKR",
        "salary_min": 60000,
        "salary_max": 90000,
        "job_link": "https://example.com/apply",
    }

    data.update(overrides)

    return data


class PostingStampsTheCompanyTests(TestCase):

    def setUp(self):
        self.user, self.company = make_employer()
        self.client.force_login(self.user)

    def test_job_title_and_description_reject_disallowed_characters(self):
        invalid_submissions = (
            (
                {"title": "Developer 2"},
                "title",
                "Job title must be 3-100 characters",
            ),
            (
                {"title": "D!veloper"},
                "title",
                "Job title must be 3-100 characters",
            ),
            (
                {"description": "12345678901234567890"},
                "description",
                "Job description must contain at least one letter.",
            ),
            (
                {"description": "Short text"},
                "description",
                "Job description must be at least 20 characters.",
            ),
        )
        for values, field, message in invalid_submissions:
            with self.subTest(values=values):
                response = self.client.post(
                    reverse("post_job"), post_payload(**values)
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)
                self.assertContains(response, message)
                self.assertFalse(Job.objects.exists())

    def test_job_title_and_description_validation_also_applies_when_editing(self):
        job = Job.objects.create(
            title="Django Developer",
            description="Build and maintain Django services.",
            source="workvista",
            posted_by=self.user,
            company=self.company.name,
            location=self.company.location,
        )

        response = self.client.post(
            reverse("edit_posted_job", args=[job.id]),
            post_payload(title="Developer 2"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("title", response.context["form"].errors)
        job.refresh_from_db()
        self.assertEqual(job.title, "Django Developer")

    def test_post_form_shows_client_side_text_validation_messages(self):
        response = self.client.get(reverse("post_job"))

        self.assertContains(response, "job-title-input-error")
        self.assertContains(response, "job-description-input-error")
        self.assertContains(response, "Job title must be 3-100 characters")

    def test_the_posting_carries_the_employers_company_name(self):
        response = self.client.post(
            reverse("post_job"), post_payload(), follow=True
        )

        job = Job.objects.get(title="Django Developer")

        self.assertEqual(job.company, "Galixo")
        self.assertFalse(job.is_approved)
        self.assertContains(
            response,
            "Your job has been submitted and is waiting for admin approval.",
        )

    def test_head_office_stamps_the_company_location_and_no_branch(self):
        self.client.post(reverse("post_job"), post_payload())

        job = Job.objects.get(title="Django Developer")

        self.assertEqual(job.location, "Lahore")
        self.assertIsNone(job.branch)

    def test_choosing_a_branch_stamps_that_branchs_location(self):
        branch = CompanyBranch.objects.create(
            company=self.company, name="Karachi office", location="Karachi"
        )

        self.client.post(reverse("post_job"), post_payload(branch=branch.id))

        job = Job.objects.get(title="Django Developer")

        self.assertEqual(job.location, "Karachi")
        self.assertEqual(job.branch, branch)

    def test_a_submitted_company_name_is_ignored(self):
        self.client.post(
            reverse("post_job"),
            post_payload(company="Somebody Else Ltd", location="Atlantis"),
        )

        job = Job.objects.get(title="Django Developer")

        self.assertEqual(job.company, "Galixo")
        self.assertEqual(job.location, "Lahore")

    def test_another_companys_branch_is_rejected(self):
        _, rival = make_employer(
            username="rival",
            email="rival@example.com",
            company_name="Rival Ltd",
            company_location="Karachi",
        )

        branch = CompanyBranch.objects.create(
            company=rival, name="Rival HQ", location="Karachi"
        )

        response = self.client.post(
            reverse("post_job"), post_payload(branch=branch.id)
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Job.objects.count(), 0)

    def test_the_form_shows_the_company_name_locked(self):
        response = self.client.get(reverse("post_job"))

        self.assertContains(response, "Galixo")
        self.assertNotContains(response, 'name="company"')

    def test_an_employer_with_no_branches_gets_no_dropdown(self):
        response = self.client.get(reverse("post_job"))

        self.assertNotContains(response, '<select name="branch"')
        self.assertContains(response, 'name="branch"')

    def test_an_employer_with_branches_gets_a_dropdown(self):
        CompanyBranch.objects.create(
            company=self.company, name="Karachi office", location="Karachi"
        )

        response = self.client.get(reverse("post_job"))

        self.assertContains(response, '<select name="branch"')
        self.assertContains(response, "Karachi office")

    def test_a_posting_whose_branch_was_removed_falls_back_to_head_office(self):
        branch = CompanyBranch.objects.create(
            company=self.company, name="Karachi office", location="Karachi"
        )

        self.client.post(reverse("post_job"), post_payload(branch=branch.id))

        branch.delete()

        job = Job.objects.get(title="Django Developer")
        response = self.client.get(reverse("edit_posted_job", args=[job.id]))

        self.assertEqual(response.status_code, 200)


# =========================================================
# MY POSTINGS
# =========================================================

class EmployerPostingsSectionTests(TestCase):

    def setUp(self):
        self.user, self.company = make_employer()
        self.client.force_login(self.user)

    def test_it_lists_only_this_employers_postings(self):
        Job.objects.create(
            title="Mine", source="workvista", posted_by=self.user
        )

        rival, _ = make_employer(
            username="rival", email="rival@example.com", company_name="Rival Ltd"
        )
        Job.objects.create(title="Theirs", source="workvista", posted_by=rival)

        response = self.client.get(reverse("employer_postings"))

        self.assertContains(response, "Mine")
        self.assertNotContains(response, "Theirs")

    def test_it_offers_edit_and_delete_on_each_posting(self):
        job = Job.objects.create(
            title="Mine", source="workvista", posted_by=self.user
        )

        response = self.client.get(reverse("employer_postings"))

        self.assertContains(response, reverse("edit_posted_job", args=[job.id]))
        self.assertContains(response, reverse("delete_posted_job", args=[job.id]))

    def test_it_marks_its_own_sidebar_entry(self):
        response = self.client.get(reverse("employer_postings"))

        self.assertEqual(active_sidebar_ids(response), ["nav-postings"])

    def test_an_employer_with_nothing_posted_is_told_so(self):
        response = self.client.get(reverse("employer_postings"))

        self.assertContains(response, "haven't posted a job yet")

    def test_it_shows_pending_and_approved_statuses_without_denied_rows(self):
        Job.objects.create(
            title="Pending role", source="workvista", posted_by=self.user,
            is_approved=False,
        )
        Job.objects.create(
            title="Approved role", source="workvista", posted_by=self.user,
            is_approved=True,
        )

        response = self.client.get(reverse("employer_postings"))

        self.assertContains(response, "Pending role")
        self.assertContains(response, "Approved role")
        self.assertContains(response, "Pending")
        self.assertContains(response, "Approved")


def make_approval_staff(role="admin", username="reviewer"):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="Secret!1",
    )
    user.profile.role = role
    user.profile.save()
    return user


class EmployerJobApprovalTests(TestCase):

    def setUp(self):
        self.employer, self.company = make_employer()
        self.admin = make_approval_staff()
        self.client.force_login(self.admin)

    def make_pending_job(self, **overrides):
        values = {
            "title": "Platform Engineer",
            "company": self.company.name,
            "location": self.company.location,
            "source": "workvista",
            "posted_by": self.employer,
            "is_approved": False,
        }
        values.update(overrides)
        return Job.objects.create(**values)

    def test_admin_and_superadmin_dashboards_list_only_pending_employer_jobs(self):
        pending = self.make_pending_job()
        self.make_pending_job(title="Already approved", is_approved=True)
        Job.objects.create(title="Scraped job", source="mustakbil")

        response = self.client.get(
            reverse("admin_dashboard"), {"section": "employers"}
        )

        self.assertContains(response, pending.title)
        self.assertContains(response, self.company.name)
        self.assertContains(response, "Allow")
        self.assertContains(response, "Deny")
        self.assertNotContains(response, "Already approved")
        self.assertNotContains(response, "Scraped job")

        superadmin = make_approval_staff("superadmin", "root")
        self.client.force_login(superadmin)
        response = self.client.get(
            reverse("superadmin_dashboard"), {"section": "employers"}
        )
        self.assertContains(response, pending.title)

    def test_allow_approves_job_and_it_becomes_public(self):
        job = self.make_pending_job()

        response = self.client.post(reverse("allow_employer_job", args=[job.id]))

        self.assertRedirects(
            response,
            f"{reverse('admin_dashboard')}?section=employers",
        )
        job.refresh_from_db()
        self.assertTrue(job.is_approved)
        notice = Notification.objects.get(user=self.employer)
        self.assertEqual(notice.kind, "employer_job_approved")
        self.assertEqual(notice.title, "Your job was approved")
        self.assertEqual(
            notice.body,
            f'"{job.title}" at {self.company.name} is now live.',
        )
        self.assertContains(
            self.client.get(reverse("job_detail", args=[job.id])), job.title
        )

        self.client.force_login(self.employer)
        inbox = self.client.get(reverse("dashboard_notifications"))
        self.assertContains(inbox, "Your job was approved")
        self.assertContains(inbox, "is now live.")
        self.assertContains(inbox, "ago")

    def test_approval_notifies_and_emails_matching_job_seekers(self):
        from django.core import mail
        from django.test import override_settings
        from unittest.mock import patch

        from .alerts.digest import send_one_notification

        seeker = User.objects.create_user(
            username="matchseeker",
            email="matchseeker@example.com",
            password="Test-Pass-928!",
        )
        seeker_profile = seeker.profile
        seeker_profile.skills = ["python"]
        seeker_profile.job_title = "Platform Engineer"
        seeker_profile.location = "Lahore"
        seeker_profile.save()
        job = self.make_pending_job(description="Python is required.")

        def send_synchronously(notification_ids):
            for notification_id in notification_ids:
                notification = Notification.objects.get(pk=notification_id)
                send_one_notification(notification)

        with override_settings(JOB_ALERTS_ENABLED=True):
            with patch("jobs.refresh.spawn_digest"):
                with patch(
                    "jobs.alerts.digest.spawn_notification_emails",
                    side_effect=send_synchronously,
                ):
                    with self.captureOnCommitCallbacks(execute=True):
                        self.client.post(
                            reverse("allow_employer_job", args=[job.id])
                        )

        notification = Notification.objects.get(user=seeker, job=job)
        self.assertEqual(notification.kind, "job_match")
        self.assertEqual(notification.body, "Galixo · Lahore · Matched")
        seeker_emails = [
            message for message in mail.outbox
            if message.to == [seeker.email]
        ]
        self.assertEqual(len(seeker_emails), 1)
        self.assertIn(job.title, seeker_emails[0].body)
        self.assertIn(f"/jobs/{job.id}/", seeker_emails[0].body)
        employer_emails = [
            message for message in mail.outbox
            if message.to == [self.employer.email]
        ]
        self.assertEqual(len(employer_emails), 1)
        self.assertIn("Your job was approved", employer_emails[0].body)

    def test_deny_notifies_employer_and_deletes_job_and_cascaded_records(self):
        job = self.make_pending_job()
        seeker = User.objects.create_user(
            username="seeker", email="seeker@example.com", password="Secret!1"
        )
        saved = SavedJob.objects.create(user=seeker, job=job)
        application = Application.objects.create(user=seeker, job=job)
        activity = UserActivity.objects.create(
            user=seeker, activity_type="view", category="technology", job=job
        )
        Notification.objects.create(
            user=seeker, job=job, title="Existing job match"
        )

        response = self.client.post(reverse("deny_employer_job", args=[job.id]))

        self.assertRedirects(
            response,
            f"{reverse('admin_dashboard')}?section=employers",
        )
        self.assertFalse(Job.objects.filter(id=job.id).exists())
        self.assertFalse(SavedJob.objects.filter(id=saved.id).exists())
        self.assertFalse(Application.objects.filter(id=application.id).exists())
        self.assertFalse(UserActivity.objects.filter(id=activity.id).exists())
        self.assertFalse(Notification.objects.filter(title="Existing job match").exists())
        notice = Notification.objects.get(user=self.employer)
        self.assertIsNone(notice.job)
        self.assertIn(job.title, notice.body)
        self.assertIn(self.company.name, notice.body)

        self.client.force_login(self.employer)
        inbox = self.client.get(reverse("dashboard_notifications"))
        self.assertContains(inbox, "Your job was not approved")
        self.assertContains(inbox, job.title)

    def test_repeat_allow_and_deny_show_already_handled(self):
        approved = self.make_pending_job(title="Approved once")
        self.client.post(reverse("allow_employer_job", args=[approved.id]))
        response = self.client.post(
            reverse("allow_employer_job", args=[approved.id]), follow=True
        )
        self.assertContains(response, "This job has already been handled")

        denied = self.make_pending_job(title="Denied once")
        self.client.post(reverse("deny_employer_job", args=[denied.id]))
        response = self.client.post(
            reverse("deny_employer_job", args=[denied.id]), follow=True
        )
        self.assertContains(response, "This job has already been handled")

    def test_scraped_job_ids_cannot_be_approved_or_deleted(self):
        scraped = Job.objects.create(
            title="Scraped role", source="mustakbil", is_approved=True
        )

        for action in ("allow_employer_job", "deny_employer_job"):
            response = self.client.post(reverse(action, args=[scraped.id]))
            self.assertRedirects(
                response,
                f"{reverse('admin_dashboard')}?section=employers",
            )
            self.assertTrue(Job.objects.filter(id=scraped.id).exists())

    def test_only_admin_or_superadmin_can_manage_jobs_and_actions_require_post(self):
        job = self.make_pending_job()
        seeker = User.objects.create_user(
            username="seeker", email="seeker@example.com", password="Secret!1"
        )
        self.client.force_login(seeker)
        response = self.client.post(reverse("allow_employer_job", args=[job.id]))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(job.is_approved)

        self.client.force_login(self.employer)
        response = self.client.post(reverse("deny_employer_job", args=[job.id]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Job.objects.filter(id=job.id).exists())

        self.client.force_login(self.admin)
        response = self.client.get(reverse("deny_employer_job", args=[job.id]))
        self.assertEqual(response.status_code, 405)

    def test_admin_dashboard_approval_forms_require_csrf(self):
        job = self.make_pending_job()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)

        response = client.get(
            reverse("admin_dashboard"), {"section": "employers"}
        )
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, "return confirm(")

        response = client.post(reverse("allow_employer_job", args=[job.id]))
        self.assertEqual(response.status_code, 403)
        job.refresh_from_db()
        self.assertFalse(job.is_approved)

    def test_public_job_lookup_hides_pending_employer_jobs_but_keeps_scraped(self):
        pending = self.make_pending_job()
        scraped = Job.objects.create(title="Scraped role", source="mustakbil")

        self.assertEqual(
            self.client.get(reverse("job_detail", args=[pending.id])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("job_detail", args=[scraped.id])).status_code,
            200,
        )

        search = self.client.get(reverse("search_jobs"), {"q": ""})
        self.assertNotContains(search, pending.title)
        self.assertContains(search, scraped.title)


# =========================================================
# THE PUBLIC POST A JOB BUTTON
# =========================================================

class PublicPostJobButtonTests(TestCase):

    def test_a_signed_out_visitor_is_pointed_at_employer_signup(self):
        response = self.client.get(reverse("home"))

        self.assertContains(response, reverse("signup_employer"))
        self.assertContains(response, "Post a Job")

    def test_an_employer_is_pointed_at_the_post_form(self):
        user, _ = make_employer()
        self.client.force_login(user)

        response = self.client.get(reverse("home"))

        self.assertContains(response, reverse("post_job"))

    def test_an_employee_is_still_shown_the_button(self):
        user = User.objects.create_user(
            username="seeker", email="seeker@example.com", password="Secret!1"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("home"))

        self.assertContains(response, "Post a Job")


# =========================================================
# MIGRATING THE MEMBERS WHO HAD ALREADY POSTED
# =========================================================

class ExistingPosterMigrationTests(TestCase):
    """The backfill itself, run against a state built by hand.

    Django's test database already has every migration applied, so
    rather than rewinding it, this exercises the function the migration
    calls - which is where all the logic actually is.
    """

    def test_it_turns_a_member_who_has_posted_into_an_employer(self):
        from .migrations import _employer_backfill

        user = User.objects.create_user(
            username="oldposter", email="old@example.com", password="Secret!1"
        )
        user.first_name = "Old Poster"
        user.save()

        Job.objects.create(
            title="Django Developer",
            company="Galixo",
            location="Lahore",
            source="workvista",
            posted_by=user,
        )

        _employer_backfill(User, Profile, Job, Company)

        user.refresh_from_db()

        self.assertTrue(user.profile.is_employer)
        self.assertEqual(user.company.name, "Galixo")
        self.assertEqual(user.company.location, "Lahore")

    def test_it_leaves_admins_alone(self):
        from .migrations import _employer_backfill

        user = User.objects.create_user(
            username="boss", email="boss@example.com", password="Secret!1"
        )
        Profile.objects.filter(user=user).update(role="admin")

        Job.objects.create(
            title="Django Developer", source="workvista", posted_by=user
        )

        _employer_backfill(User, Profile, Job, Company)

        user.refresh_from_db()

        self.assertEqual(user.profile.role, "admin")
        self.assertFalse(Company.objects.filter(owner=user).exists())

    def test_a_blank_company_falls_back_to_the_members_name(self):
        from .migrations import _employer_backfill

        user = User.objects.create_user(
            username="oldposter", email="old@example.com", password="Secret!1"
        )
        user.first_name = "Old Poster"
        user.save()

        Job.objects.create(
            title="Django Developer", company="", source="workvista", posted_by=user
        )

        _employer_backfill(User, Profile, Job, Company)

        self.assertEqual(user.company.name, "Old Poster")

    def test_it_ignores_scraped_jobs(self):
        from .migrations import _employer_backfill

        Job.objects.create(title="Scraped", source="mustakbil", posted_by=None)

        _employer_backfill(User, Profile, Job, Company)

        self.assertEqual(Company.objects.count(), 0)

    def test_running_it_twice_changes_nothing(self):
        from .migrations import _employer_backfill

        user = User.objects.create_user(
            username="oldposter", email="old@example.com", password="Secret!1"
        )

        Job.objects.create(
            title="Django Developer",
            company="Galixo",
            location="Lahore",
            source="workvista",
            posted_by=user,
        )

        _employer_backfill(User, Profile, Job, Company)
        _employer_backfill(User, Profile, Job, Company)

        self.assertEqual(Company.objects.filter(owner=user).count(), 1)
