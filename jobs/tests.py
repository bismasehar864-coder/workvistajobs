from datetime import timedelta
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Job, Profile
from .recommender.categorize import CATEGORY_KEYWORDS, categorize_job
from .management.commands.scrape_njp import (
    parse_listing_page,
    parse_detail_page,
    save_jobs,
)
from .management.commands.scrape_ppsc import (
    parse_ppsc_table,
    save_jobs as save_ppsc_jobs,
)
from .management.commands.scrape_mustakbil import (
    parse_sitemap,
    parse_job_posting,
    save_jobs as save_mustakbil_jobs,
)


def make_user(username="poster", email="poster@example.com", fullname="Ayesha Khan"):
    user = User.objects.create_user(
        username=username,
        email=email,
        password="Secret!1",
    )

    user.first_name = fullname
    user.save()

    return user


def make_posting_employer(
    username="poster", email="poster@example.com", fullname="Ayesha Khan"
):
    """A member who is allowed to post - i.e. an employer with a company.

    Posting used to be open to anyone, so these suites signed in as a
    plain user. The behaviour under test hasn't changed, only who is
    permitted to trigger it.
    """

    from .models import Company

    user = make_user(username=username, email=email, fullname=fullname)

    # Through the instance the post_save signal attached, not a queryset
    # update - that would leave the cached user.profile stale.
    profile = user.profile
    profile.role = "employer"
    profile.save()

    Company.objects.create(owner=user, name="Galixo", location="Lahore")

    return user


def valid_post_data(**overrides):
    # No company or location: they are stamped from the posting
    # employer's own company, never submitted.
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


# =========================================================
# ACCESS CONTROL
# =========================================================

class PostJobAccessTests(TestCase):

    def test_anonymous_visitor_is_sent_to_signin_with_next(self):
        response = self.client.get(reverse("post_job"))

        self.assertRedirects(
            response,
            f"{reverse('signin')}?next={reverse('post_job')}",
            target_status_code=200,
        )

    def test_signin_returns_an_employer_to_the_next_page(self):
        make_posting_employer()

        response = self.client.post(
            f"{reverse('signin')}?next={reverse('post_job')}",
            {"email": "poster@example.com", "password": "Secret!1"},
        )

        self.assertRedirects(response, reverse("post_job"))

    def test_signin_sends_admin_to_admin_dashboard_despite_next(self):
        user = make_user(username="boss", email="boss@example.com")

        Profile.objects.filter(user=user).update(role="admin")

        response = self.client.post(
            f"{reverse('signin')}?next={reverse('post_job')}",
            {"email": "boss@example.com", "password": "Secret!1"},
        )

        self.assertRedirects(
            response,
            f"{reverse('admin_dashboard')}?section=profile",
            fetch_redirect_response=False,
        )

    def test_signin_sends_superadmin_to_superadmin_dashboard_at_profile(self):
        user = make_user(username="chief", email="chief@example.com")

        Profile.objects.filter(user=user).update(role="superadmin")

        response = self.client.post(
            reverse("signin"),
            {"email": "chief@example.com", "password": "Secret!1"},
        )

        self.assertRedirects(
            response,
            f"{reverse('superadmin_dashboard')}?section=profile",
            fetch_redirect_response=False,
        )


# =========================================================
# CREATING A POSTING
# =========================================================

class PostJobCreateTests(TestCase):

    def setUp(self):
        self.user = make_posting_employer()
        self.client.force_login(self.user)

    def test_valid_submission_creates_a_workvista_job_owned_by_the_user(self):
        self.client.post(reverse("post_job"), valid_post_data())

        job = Job.objects.get(title="Django Developer")

        self.assertEqual(job.source, "workvista")
        self.assertEqual(job.posted_by, self.user)
        self.assertEqual(job.company, "Galixo")
        self.assertEqual(job.location, "Lahore")
        self.assertEqual(job.category, "technology")
        self.assertEqual(job.job_type, "Full-time")
        self.assertEqual(job.job_link, "https://example.com/apply")

    def test_salary_range_is_rendered_into_the_display_field(self):
        self.client.post(reverse("post_job"), valid_post_data())

        job = Job.objects.get(title="Django Developer")

        self.assertEqual(job.salary_min, 60000)
        self.assertEqual(job.salary_max, 90000)
        self.assertEqual(job.salary, "PKR 60,000 - 90,000 /month")
        self.assertEqual(job.salary_display, "PKR 60,000 - 90,000 /month")

    def test_minimum_salary_above_maximum_is_rejected(self):
        response = self.client.post(
            reverse("post_job"),
            valid_post_data(salary_min=90000, salary_max=60000),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Job.objects.exists())
        self.assertContains(
            response,
            "Minimum salary cannot be greater than maximum salary.",
        )

    def test_salary_amounts_are_optional_and_currency_is_saved(self):
        self.client.post(
            reverse("post_job"),
            valid_post_data(salary_currency="USD", salary_min="", salary_max=""),
        )

        job = Job.objects.get(title="Django Developer")
        self.assertIsNone(job.salary_min)
        self.assertIsNone(job.salary_max)
        self.assertEqual(job.salary, "USD")
        self.assertEqual(job.salary_display, "")

    def test_one_salary_amount_is_saved_and_formatted(self):
        self.client.post(
            reverse("post_job"),
            valid_post_data(salary_currency="EUR", salary_min=40000, salary_max=""),
        )

        job = Job.objects.get(title="Django Developer")
        self.assertEqual(job.salary_min, 40000)
        self.assertIsNone(job.salary_max)
        self.assertEqual(job.salary_display, "EUR 40,000 /month")

    def test_non_numeric_salary_amount_is_rejected(self):
        response = self.client.post(
            reverse("post_job"),
            valid_post_data(salary_min="40k"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Job.objects.exists())

    def test_the_page_lists_only_the_signed_in_users_own_postings(self):
        other = make_user(username="rival", email="rival@example.com")

        Job.objects.create(title="Mine", source="workvista", posted_by=self.user)
        Job.objects.create(title="Theirs", source="workvista", posted_by=other)
        Job.objects.create(title="Scraped", source="mustakbil")

        # The list moved off the post form and onto its own section, so
        # the form page stays one job. Its behaviour is unchanged.
        response = self.client.get(reverse("employer_postings"))
        titles = [job.title for job in response.context["my_jobs"]]

        self.assertEqual(titles, ["Mine"])


# =========================================================
# AUTHOR ATTRIBUTION
# =========================================================

class PostedJobAuthorTests(TestCase):

    def test_job_detail_shows_the_name_of_the_author(self):
        user = make_user(fullname="Ayesha Khan")

        job = Job.objects.create(
            title="Django Developer",
            source="workvista",
            posted_by=user,
        )

        response = self.client.get(reverse("job_detail", args=[job.id]))

        self.assertContains(response, "Ayesha Khan")

    def test_job_detail_of_a_scraped_job_names_no_author(self):
        job = Job.objects.create(title="Scraped Role", source="mustakbil")

        response = self.client.get(reverse("job_detail", args=[job.id]))

        self.assertNotContains(response, "Posted by")


# =========================================================
# EDITING A POSTING
# =========================================================

class PostedJobEditTests(TestCase):

    def setUp(self):
        self.user = make_posting_employer()
        self.client.force_login(self.user)

        self.job = Job.objects.create(
            title="Django Developer",
            source="workvista",
            posted_by=self.user,
            salary_min=60000,
            salary_max=90000,
            salary="USD 60,000 - 90,000 /month",
        )

    def test_edit_form_prefills_salary_range_and_currency(self):
        response = self.client.get(reverse("edit_posted_job", args=[self.job.id]))

        self.assertContains(response, 'name="salary_min" value="60000"')
        self.assertContains(response, 'name="salary_max" value="90000"')
        self.assertContains(response, 'value="USD" selected')

    def test_author_can_change_their_posting(self):
        self.client.post(
            reverse("edit_posted_job", args=[self.job.id]),
            valid_post_data(title="Senior Django Developer", salary_max=120000),
        )

        self.job.refresh_from_db()

        self.assertEqual(self.job.title, "Senior Django Developer")
        self.assertEqual(self.job.salary, "PKR 60,000 - 120,000 /month")
        self.assertEqual(self.job.posted_by, self.user)
        self.assertEqual(self.job.source, "workvista")

    def test_another_user_cannot_edit_someone_elses_posting(self):
        self.client.force_login(
            make_posting_employer(username="rival", email="rival@example.com")
        )

        response = self.client.post(
            reverse("edit_posted_job", args=[self.job.id]),
            valid_post_data(title="Hijacked"),
        )

        self.job.refresh_from_db()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.job.title, "Django Developer")

    def test_a_scraped_job_cannot_be_edited(self):
        scraped = Job.objects.create(title="Scraped Role", source="mustakbil")

        response = self.client.get(reverse("edit_posted_job", args=[scraped.id]))

        self.assertEqual(response.status_code, 404)


# =========================================================
# SALARY DISPLAY
# =========================================================

class SalaryDisplayTests(TestCase):

    def test_job_card_and_detail_share_formatted_salary_display(self):
        employer = make_posting_employer()
        self.client.force_login(employer)
        job = Job.objects.create(
            title="Django Developer",
            source="workvista",
            posted_by=employer,
            salary_min=40000,
            salary_max=120000,
            salary="PKR 40000 - 120000 /month",
        )

        postings_response = self.client.get(reverse("employer_postings"))
        detail_response = self.client.get(reverse("job_detail", args=[job.id]))

        self.assertContains(
            postings_response,
            "PKR 40,000 - 120,000 /month",
        )
        self.assertContains(
            detail_response,
            "PKR 40,000 - 120,000 /month",
        )


# =========================================================
# DELETING A POSTING
# =========================================================

class PostedJobDeleteTests(TestCase):

    def setUp(self):
        self.user = make_posting_employer()
        self.client.force_login(self.user)

        self.job = Job.objects.create(
            title="Django Developer",
            source="workvista",
            posted_by=self.user,
        )

    def test_author_can_delete_their_posting(self):
        self.client.post(reverse("delete_posted_job", args=[self.job.id]))

        self.assertFalse(Job.objects.filter(id=self.job.id).exists())

    def test_another_user_cannot_delete_someone_elses_posting(self):
        self.client.force_login(
            make_posting_employer(username="rival", email="rival@example.com")
        )

        response = self.client.post(reverse("delete_posted_job", args=[self.job.id]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Job.objects.filter(id=self.job.id).exists())


# =========================================================
# SOURCE FILTER
# =========================================================

class SourceFilterTests(TestCase):

    def setUp(self):
        self.user = make_user()

        self.posted = Job.objects.create(
            title="Django Developer",
            source="workvista",
            category="technology",
            posted_by=self.user,
        )

        self.scraped = Job.objects.create(
            title="Django Engineer",
            source="mustakbil",
            category="technology",
        )

    def test_search_page_filtered_by_workvista_returns_only_posted_jobs(self):
        response = self.client.get(reverse("search_jobs"), {"source": "workvista"})

        titles = [job.title for job in response.context["jobs"]]

        self.assertEqual(titles, ["Django Developer"])

    def test_search_page_can_filter_remoteok_jobs(self):
        remote_job = Job.objects.create(
            title="Remote Python Engineer",
            source="remoteok",
            category="technology",
        )

        response = self.client.get(reverse("search_jobs"), {"source": "remoteok"})

        self.assertEqual(
            [job.id for job in response.context["jobs"]],
            [remote_job.id],
        )
        self.assertIn("remoteok", dict(Job.SOURCE_CHOICES))

    def test_search_page_without_a_source_returns_every_job(self):
        response = self.client.get(reverse("search_jobs"), {"q": "django"})

        titles = sorted(job.title for job in response.context["jobs"])

        self.assertEqual(titles, ["Django Developer", "Django Engineer"])

    def test_dashboard_search_filtered_by_workvista_returns_only_posted_jobs(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("user_dashboard"),
            {"source": "workvista", "category": ""},
        )

        titles = [job.title for job in response.context["jobs"]]

        self.assertEqual(titles, ["Django Developer"])

# =========================================================
# ENTRY POINTS AND CONTROLS
# =========================================================

class PostJobEntryPointTests(TestCase):

    def test_home_page_shows_nine_trending_jobs_from_distinct_categories(self):
        categories = [
            "technology", "design", "finance", "education",
            "healthcare", "marketing", "sales", "hr", "research",
        ]
        for category in categories:
            Job.objects.create(
                title=f"{category.title()} role",
                source="workvista",
                category=category,
            )

        response = self.client.get(reverse("home"))

        self.assertEqual(len(response.context["category_highlights"]), 9)
        self.assertContains(response, "Technology role")
        self.assertContains(response, "Research role")

    def test_home_page_offers_post_a_job_to_a_signed_out_visitor(self):
        """A signed-out visitor has no account to post from, so the
        button starts them on employer signup rather than a sign-in
        wall for a page they could not use anyway."""

        response = self.client.get(reverse("home"))

        self.assertContains(response, reverse("signup_employer"))
        self.assertContains(response, "Post a Job")

    def test_post_job_page_marks_its_sidebar_entry_active(self):
        self.client.force_login(make_posting_employer())

        response = self.client.get(reverse("post_job"))

        self.assertContains(response, 'id="nav-post-job"')
        self.assertContains(response, 'class="active"')

    def test_search_page_offers_workvista_as_a_source(self):
        response = self.client.get(reverse("search_jobs"))

        self.assertContains(response, '<select name="source">')
        self.assertContains(response, '<option value="workvista"')

    def test_edit_page_is_prefilled_with_the_existing_posting(self):
        user = make_posting_employer()
        self.client.force_login(user)

        job = Job.objects.create(
            title="Django Developer",
            company="Galixo",
            source="workvista",
            posted_by=user,
            salary_min=60000,
            salary_max=90000,
        )

        response = self.client.get(reverse("edit_posted_job", args=[job.id]))

        self.assertContains(response, 'value="Django Developer"')
        self.assertContains(response, "Galixo")            # shown locked
        self.assertNotContains(response, 'name="company"')
        self.assertContains(response, 'value="60000"')


class OwnerControlsTests(TestCase):

    def setUp(self):
        self.user = make_posting_employer()

        self.job = Job.objects.create(
            title="Django Developer",
            source="workvista",
            posted_by=self.user,
        )

    def test_the_author_sees_edit_and_delete_on_their_own_job(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("job_detail", args=[self.job.id]))

        self.assertContains(response, reverse("edit_posted_job", args=[self.job.id]))
        self.assertContains(response, reverse("delete_posted_job", args=[self.job.id]))

    def test_another_member_sees_no_edit_or_delete_controls(self):
        self.client.force_login(
            make_posting_employer(username="rival", email="rival@example.com")
        )

        response = self.client.get(reverse("job_detail", args=[self.job.id]))

        self.assertNotContains(response, reverse("edit_posted_job", args=[self.job.id]))
        self.assertNotContains(response, reverse("delete_posted_job", args=[self.job.id]))


# =========================================================
# WHICH DASHBOARD SECTION OPENS
# =========================================================
#
# The dashboard's tab sections used to be chosen entirely client-side
# from localStorage. A GET form submission drops the URL fragment, so
# searching lost "#search" and the page came back on whatever section
# was last remembered - usually Trending - with the results sitting in
# a hidden div. The server now names the section the URL implies.

class DashboardActiveSectionTests(TestCase):

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_a_search_request_opens_the_search_section(self):
        response = self.client.get(reverse("user_dashboard"), {"q": "developer"})

        self.assertEqual(response.context["active_section"], "search")
        self.assertContains(response, '<div class="section active" id="search">')

    def test_a_bare_source_filter_still_opens_the_search_section(self):
        response = self.client.get(reverse("user_dashboard"), {"source": "workvista"})

        self.assertEqual(response.context["active_section"], "search")

    def test_a_trending_filter_opens_the_trending_section(self):
        response = self.client.get(
            reverse("user_dashboard"),
            {"trend_category": "technology"},
        )

        self.assertEqual(response.context["active_section"], "trending")

    def test_a_plain_visit_opens_the_profile(self):
        # Was "leave it to the browser", which is what let a
        # redirect-after-save land on whichever tab localStorage
        # remembered. The server always names a section now.
        response = self.client.get(reverse("user_dashboard"))

        self.assertEqual(response.context["active_section"], "profile")
        self.assertContains(response, '<div class="section active" id="profile">')

    def test_an_explicit_section_parameter_wins(self):
        response = self.client.get(reverse("user_dashboard"), {"section": "saved"})

        self.assertEqual(response.context["active_section"], "saved")

    def test_an_unknown_section_parameter_falls_back_to_the_profile(self):
        response = self.client.get(reverse("user_dashboard"), {"section": "bogus"})

        self.assertEqual(response.context["active_section"], "profile")


class SearchPageNavigationTests(TestCase):

    def test_the_standalone_search_page_still_shows_the_navbar(self):
        response = self.client.get(reverse("search_jobs"), {"q": "developer"})

        self.assertContains(response, '<nav class="navbar"')


# =========================================================
# SALARY RANGE FORM
# =========================================================

class SalaryRangeFormTests(TestCase):

    def setUp(self):
        self.client.force_login(make_posting_employer())

    def test_the_range_can_also_be_typed_in(self):
        response = self.client.get(reverse("post_job"))

        self.assertContains(response, 'type="text" name="salary_min"')
        self.assertContains(response, 'type="text" name="salary_max"')
        self.assertContains(response, 'inputmode="numeric"')
        self.assertContains(response, 'value="PKR" selected')
        self.assertContains(response, 'placeholder="Min"')
        self.assertContains(response, 'placeholder="Max"')
        self.assertNotContains(response, 'name="salary_min" value="40000"')
        self.assertNotContains(response, 'name="salary_max" value="120000"')
        for name in ("salary_min", "salary_max"):
            field = response.context["form"].fields[name]
            self.assertFalse(field.required)
            self.assertIsNone(field.min_value)
            self.assertIsNone(field.max_value)
            self.assertNotIn("pattern", field.widget.attrs)
            self.assertNotIn("min", field.widget.attrs)
            self.assertNotIn("max", field.widget.attrs)
            self.assertNotIn("step", field.widget.attrs)

    def test_a_typed_range_is_what_gets_saved(self):
        self.client.post(
            reverse("post_job"),
            valid_post_data(salary_min=61234, salary_max=98765),
        )

        job = Job.objects.get(title="Django Developer")

        self.assertEqual(job.salary_min, 61234)
        self.assertEqual(job.salary_max, 98765)
        self.assertEqual(job.salary, "PKR 61,234 - 98,765 /month")

    def test_salary_maximum_can_be_entered_without_a_minimum(self):
        self.client.post(
            reverse("post_job"),
            valid_post_data(salary_min="", salary_max=120000),
        )

        job = Job.objects.get(title="Django Developer")
        self.assertIsNone(job.salary_min)
        self.assertEqual(job.salary_max, 120000)
        self.assertEqual(job.salary_display, "PKR 120,000 /month")

    def test_large_salary_values_can_be_entered_without_a_ceiling(self):
        self.client.post(
            reverse("post_job"),
            valid_post_data(salary_min=400000, salary_max=4000000000),
        )

        job = Job.objects.get(title="Django Developer")

        self.assertEqual(job.salary_min, 400000)
        self.assertEqual(job.salary_max, 4000000000)
        self.assertEqual(
            job.salary_display,
            "PKR 400,000 - 4,000,000,000 /month",
        )


# =========================================================
# JOB FIELD CATEGORIES
# =========================================================
#
# categorize_job() checks CATEGORY_KEYWORDS in order and takes the
# first match, so these tests pin down the specific-beats-general
# ordering as much as the keywords themselves: "Android Engineer" has
# to land in mobile rather than the broad technology bucket, and a
# plain "Software Engineer" still has to land in technology.

class CategorizeJobTests(TestCase):

    def assert_category(self, title, expected):
        self.assertEqual(categorize_job(title), expected, msg=title)

    def test_ai_roles(self):
        for title in [
            "Machine Learning Engineer",
            "AI Engineer",
            "Deep Learning Researcher",
            "Computer Vision Engineer",
            "NLP Engineer",
            "Prompt Engineer",
        ]:
            self.assert_category(title, "ai")

    def test_mobile_roles(self):
        for title in [
            "Android Developer",
            "iOS Engineer",
            "Flutter Developer",
            "React Native Developer",
            "Kotlin Multiplatform Engineer",
            "KMP Developer",
            "Compose Multiplatform Engineer",
            "Cross Platform Mobile App Developer",
            "SwiftUI Developer",
        ]:
            self.assert_category(title, "mobile")

    def test_web_roles(self):
        for title in [
            "Web Developer",
            "Frontend Developer",
            "Backend Engineer",
            "Full Stack Developer",
            "Django Developer",
            "Laravel Developer",
            "Angular Developer",
        ]:
            self.assert_category(title, "web")

    def test_data_roles(self):
        for title in [
            "Data Analyst",
            "Data Scientist",
            "Data Engineer",
            "Business Intelligence Developer",
            "Power BI Developer",
        ]:
            self.assert_category(title, "data")

    def test_devops_roles(self):
        for title in [
            "DevOps Engineer",
            "Site Reliability Engineer",
            "Kubernetes Administrator",
            "Cloud Engineer",
            "AWS Solutions Architect",
        ]:
            self.assert_category(title, "devops")

    def test_research_roles(self):
        for title in [
            "Research Assistant",
            "Researcher",
            "Research Associate",
        ]:
            self.assert_category(title, "research")

    def test_writing_roles(self):
        for title in [
            "Assignment Writer",
            "Academic Writer",
            "Technical Writer",
            "Thesis Writer",
        ]:
            self.assert_category(title, "writing")

    def test_video_roles(self):
        for title in [
            "Video Editor",
            "AI Video Editor",
            "Motion Graphics Designer",
            "Videographer",
        ]:
            self.assert_category(title, "video")

    def test_administration_and_government_roles(self):
        # njp.gov.pk is mostly public-sector administrative posts. Before
        # this category existed, 51 of the first 59 NJP jobs scraped
        # landed in "other".
        for title in [
            "Assistant Manager",
            "Revenue Assistant",
            "Legal Assistant",
            "Managing Director, Daanish Schools Authority",
            "Office Superintendent",
            "Data Entry Operator",
            "Stenographer",
            "Deputy Secretary",
        ]:
            self.assert_category(title, "administration")

    def test_administration_never_steals_a_more_specific_field(self):
        # 'manager'/'officer' are broad enough to swallow half the site
        # if they ran before the specific fields, so administration is
        # matched last of all.
        self.assert_category("Marketing Manager", "marketing")
        self.assert_category("Sales Manager", "sales")
        self.assert_category("HR Manager", "hr")
        self.assert_category("Finance Officer", "finance")
        self.assert_category("Engineering Manager", "technology")
        self.assert_category("Android Team Manager", "mobile")

    def test_the_fields_that_already_worked_still_do(self):
        self.assert_category("Software Engineer", "technology")
        self.assert_category("Graphic Designer", "design")
        self.assert_category("UI/UX Designer", "design")
        self.assert_category("Accountant", "finance")
        self.assert_category("Maths Tutor", "education")
        self.assert_category("Staff Nurse", "healthcare")
        self.assert_category("Customer Support Agent", "customer_service")

    def test_a_computer_science_degree_still_infers_technology(self):
        self.assert_category("BS Computer Science", "technology")

    def test_every_category_keyword_group_is_a_declared_choice(self):
        declared = {value for value, _ in Job.CATEGORY_CHOICES}
        keyed = {category for category, _ in CATEGORY_KEYWORDS}

        self.assertTrue(
            keyed.issubset(declared),
            msg=f"not declared in CATEGORY_CHOICES: {keyed - declared}",
        )


# =========================================================
# NATIONAL JOB PORTAL (njp.gov.pk) SCRAPER
# =========================================================
#
# Parsing is tested against HTML saved from the real site
# (jobs/tests_data/), so these break loudly when NJP changes its
# markup - which is how the Mustakbil scraper silently rotted into
# returning 0 results for every query.

def read_fixture(name):
    path = Path(__file__).resolve().parent / "tests_data" / name

    return path.read_text(encoding="utf-8")


class NjpParsingTests(TestCase):

    def setUp(self):
        self.rows = parse_listing_page(read_fixture("njp_listing.html"))

    def test_every_card_on_the_page_is_parsed(self):
        self.assertEqual(len(self.rows), 3)

    def test_the_title_and_link_come_from_the_heading(self):
        row = self.rows[0]

        self.assertEqual(
            row["title"],
            "Managing Director, Daanish Schools Authority (DSA), "
            "Ministry of Federal Education & Professional Training",
        )
        self.assertEqual(row["job_link"], "https://www.njp.gov.pk/jobs/9616")

    def test_the_hiring_body_is_read_without_its_by_prefix(self):
        self.assertEqual(
            self.rows[0]["company"],
            "Ministry of Federal Education and Professional Training",
        )

    def test_the_first_badge_is_taken_as_the_job_type(self):
        self.assertEqual(self.rows[0]["job_type"], "Contract")

    def test_experience_and_deadline_badges_are_read(self):
        row = self.rows[0]

        self.assertEqual(row["experience"], "25 Years+")
        self.assertEqual(row["posted"], "Available Till Sep 19, 2026")

    def test_a_page_with_no_cards_yields_nothing(self):
        self.assertEqual(parse_listing_page("<html><body></body></html>"), [])

    def test_the_description_is_read_from_a_detail_page(self):
        description = parse_detail_page(read_fixture("njp_detail.html"))

        self.assertIn("Minimum Master", description)
        self.assertNotIn("<div", description)


class NjpSavingTests(TestCase):

    def setUp(self):
        self.rows = parse_listing_page(read_fixture("njp_listing.html"))

    def test_saving_records_the_jobs_against_the_njp_source(self):
        save_jobs(self.rows)

        self.assertEqual(Job.objects.filter(source="njp").count(), 3)

    def test_a_saved_job_is_located_in_pakistan(self):
        # NJP publishes no location field at all - it is a national
        # portal - and leaving it blank would render as "Remote",
        # which a federal government post certainly is not.
        save_jobs(self.rows)

        self.assertEqual(Job.objects.first().location, "Pakistan")

    def test_saving_the_same_listing_twice_does_not_duplicate_it(self):
        save_jobs(self.rows)
        save_jobs(self.rows)

        self.assertEqual(Job.objects.count(), 3)

    def test_a_row_with_no_link_is_skipped(self):
        saved = save_jobs([{"title": "Ghost", "job_link": ""}])

        self.assertEqual(saved, 0)
        self.assertFalse(Job.objects.exists())

    def test_njp_is_an_offered_source_filter(self):
        self.assertIn("njp", dict(Job.SOURCE_CHOICES))


# =========================================================
# SEARCH: "NO FILTER" MEANS EVERYTHING
# =========================================================
#
# Pressing Search with every dropdown on "All ..." and the time pill on
# "Any time" used to fall through to the untouched-page empty state,
# because every value was blank. The form always submits all of its
# fields, so key *presence* - not a non-empty value - is what says the
# visitor actually searched.

class SearchShowsEverythingTests(TestCase):

    ALL_CLEARED = {
        "q": "", "location": "", "type": "",
        "posted": "", "category": "", "source": "",
    }

    def setUp(self):
        self.recent = Job.objects.create(
            title="Django Developer", source="workvista",
            category="web", job_type="Full-time", location="Lahore",
            skills=["Django", "PostgreSQL"],
        )

        self.old = Job.objects.create(
            title="Accounts Officer", source="mustakbil",
            category="finance", job_type="Contract", location="Karachi",
        )

        # first_seen_at is auto_now_add, so age it after the fact.
        Job.objects.filter(pk=self.old.pk).update(
            first_seen_at=timezone.now() - timedelta(days=10)
        )

    def titles(self, response):
        return sorted(job.title for job in response.context["jobs"])

    def test_searching_with_every_filter_cleared_returns_every_job(self):
        response = self.client.get(reverse("search_jobs"), self.ALL_CLEARED)

        self.assertEqual(self.titles(response), ["Accounts Officer", "Django Developer"])

    def test_a_fresh_visit_still_shows_the_empty_state(self):
        response = self.client.get(reverse("search_jobs"))

        self.assertEqual(list(response.context["jobs"]), [])
        self.assertContains(response, "Search for your next opportunity")

    def test_a_time_pill_alone_returns_everything_recent(self):
        response = self.client.get(
            reverse("search_jobs"),
            dict(self.ALL_CLEARED, posted="24h"),
        )

        self.assertEqual(self.titles(response), ["Django Developer"])

    def test_a_source_alone_returns_everything_from_that_source(self):
        response = self.client.get(
            reverse("search_jobs"),
            dict(self.ALL_CLEARED, source="mustakbil"),
        )

        self.assertEqual(self.titles(response), ["Accounts Officer"])

    def test_a_title_still_narrows_the_results(self):
        response = self.client.get(
            reverse("search_jobs"),
            dict(self.ALL_CLEARED, q="django"),
        )

        self.assertEqual(self.titles(response), ["Django Developer"])

    def test_a_title_is_matched_against_skills_too(self):
        response = self.client.get(
            reverse("search_jobs"),
            dict(self.ALL_CLEARED, q="postgresql"),
        )

        self.assertEqual(self.titles(response), ["Django Developer"])

    def test_the_dashboard_search_behaves_the_same_way(self):
        self.client.force_login(make_user())

        response = self.client.get(reverse("user_dashboard"), self.ALL_CLEARED)

        self.assertEqual(self.titles(response), ["Accounts Officer", "Django Developer"])


# =========================================================
# MUSTAKBIL SCRAPER
# =========================================================
#
# The old Selenium version broke silently: Mustakbil renamed its BEM
# classes (.job-title__link -> .jc-title__link, .job-company ->
# .jc-byline__company, and so on), every card lookup threw, and the
# scraper reported 0 results for every query without failing. The
# rewrite reads the site's published sitemap and each posting's
# schema.org JobPosting JSON-LD instead of its CSS classes, and these
# tests run against saved copies of both so a change fails loudly.

class MustakbilSitemapTests(TestCase):

    def setUp(self):
        self.entries = parse_sitemap(read_fixture("mustakbil_sitemap.xml"))

    def test_every_url_in_the_sitemap_is_read(self):
        self.assertEqual(len(self.entries), 6)

    def test_entries_come_back_newest_first(self):
        dates = [entry["lastmod"] for entry in self.entries]

        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_an_entry_carries_its_job_url(self):
        self.assertTrue(
            self.entries[0]["url"].startswith("https://www.mustakbil.com/jobs/job/")
        )

    def test_an_empty_sitemap_yields_nothing(self):
        self.assertEqual(parse_sitemap("<urlset></urlset>"), [])


class MustakbilJobPostingTests(TestCase):

    def setUp(self):
        self.row = parse_job_posting(read_fixture("mustakbil_job.html"))

    def test_the_headline_fields_are_read(self):
        self.assertEqual(
            self.row["title"], "Customer Service & Sales Support Officer"
        )
        self.assertEqual(self.row["company"], "HeavenBlu (Pvt.) Ltd.")

    def test_the_location_is_built_from_the_postal_address(self):
        self.assertEqual(self.row["location"], "Taxila, PK")

    def test_the_schema_employment_type_becomes_one_of_ours(self):
        # JobPosting says FULL_TIME; the rest of WorkVista says
        # "Full-time" - see Job.JOB_TYPE_CHOICES.
        self.assertEqual(self.row["job_type"], "Full-time")

    def test_the_salary_range_is_read_as_numbers_and_as_text(self):
        self.assertEqual(self.row["salary_min"], 40000)
        self.assertEqual(self.row["salary_max"], 45000)
        self.assertEqual(self.row["salary"], "PKR 40,000 - 45,000 /month")

    def test_the_description_is_plain_text_not_markup(self):
        self.assertIn("VONABLU", self.row["description"])
        self.assertNotIn("<b>", self.row["description"])

    def test_a_page_without_a_job_posting_yields_nothing(self):
        self.assertIsNone(parse_job_posting("<html><body>nope</body></html>"))


class MustakbilSavingTests(TestCase):

    def test_a_parsed_posting_saves_against_the_mustakbil_source(self):
        row = parse_job_posting(read_fixture("mustakbil_job.html"))
        row["job_link"] = "https://www.mustakbil.com/jobs/job/1433974"

        save_mustakbil_jobs([row])

        job = Job.objects.get()

        self.assertEqual(job.source, "mustakbil")
        self.assertEqual(job.company, "HeavenBlu (Pvt.) Ltd.")
        self.assertEqual(job.salary_min, 40000)
        self.assertEqual(job.category, "customer_service")

    def test_re_scraping_the_same_posting_does_not_duplicate_it(self):
        row = parse_job_posting(read_fixture("mustakbil_job.html"))
        row["job_link"] = "https://www.mustakbil.com/jobs/job/1433974"

        save_mustakbil_jobs([row])
        save_mustakbil_jobs([row])

        self.assertEqual(Job.objects.count(), 1)


# =========================================================
# PPSC SCRAPER
# =========================================================
#
# PPSC publishes its live advertisements as one plain HTML table.
# There are no per-job URLs - the POST NAME cells are ASP.NET
# __doPostBack handlers - so the case number, which is unique per
# advertisement, is what identifies a posting across re-scrapes.

class PpscParsingTests(TestCase):

    def setUp(self):
        self.rows = parse_ppsc_table(read_fixture("ppsc_jobs.html"))

    def test_every_advertised_post_is_read(self):
        self.assertEqual(len(self.rows), 3)

    def test_the_header_row_is_not_mistaken_for_a_job(self):
        self.assertNotIn("POST NAME", [row["title"] for row in self.rows])

    def test_the_post_name_and_department_are_read(self):
        row = self.rows[1]

        self.assertEqual(row["title"], "SENIOR REGISTRAR NEONATOLOGY")
        self.assertTrue(row["company"].startswith("SPECIALIZED HEALTHCARE"))

    def test_the_closing_date_is_kept(self):
        self.assertEqual(self.rows[0]["posted"], "06-09-2026")
        self.assertIn("Closing date: 21-09-2026", self.rows[0]["description"])

    def test_the_case_number_becomes_a_stable_identity(self):
        self.assertEqual(
            self.rows[0]["job_link"],
            "https://www.ppsc.gop.pk/Jobs.aspx#58G2026",
        )

    def test_a_page_without_the_table_yields_nothing(self):
        self.assertEqual(parse_ppsc_table("<html><body></body></html>"), [])


class PpscSavingTests(TestCase):

    def setUp(self):
        self.rows = parse_ppsc_table(read_fixture("ppsc_jobs.html"))

    def test_saving_records_the_posts_against_the_ppsc_source(self):
        save_ppsc_jobs(self.rows)

        self.assertEqual(Job.objects.filter(source="ppsc").count(), 3)

    def test_posts_are_located_in_punjab(self):
        save_ppsc_jobs(self.rows)

        self.assertEqual(Job.objects.first().location, "Punjab, Pakistan")

    def test_re_scraping_does_not_duplicate_the_advertisements(self):
        save_ppsc_jobs(self.rows)
        save_ppsc_jobs(self.rows)

        self.assertEqual(Job.objects.count(), 3)

    def test_a_medical_post_is_categorised_as_healthcare(self):
        save_ppsc_jobs(self.rows)

        job = Job.objects.get(title="SENIOR REGISTRAR NEONATOLOGY")

        self.assertEqual(job.category, "healthcare")
