"""Dashboard navigation: every section is a real, refreshable URL.

The dashboard used to be one page whose visible tab was decided purely
in the browser, from a hash and localStorage. That meant the section was
lost by anything that reloaded the page without a fragment - a refresh,
a shared link, and above all the redirect after saving a form, which
dropped you on whatever tab happened to be remembered rather than the
one you were working in.

Each section now has its own path, so clicking updates the URL,
refreshing stays put, and a form returns you to the section it lives in.
"""

from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from bs4 import BeautifulSoup

from .middleware import NoCacheAuthenticatedMiddleware
from .models import CVData, Job, Profile


def active_sidebar_ids(response):
    """Which sidebar entries the server marked as the open one."""

    soup = BeautifulSoup(response.content.decode(), "html.parser")

    return [
        link.get("id")
        for link in soup.select(".sidebar ul li a")
        if "active" in (link.get("class") or [])
    ]


SECTION_URLS = {
    "profile": "dashboard_profile",
    "recommended": "dashboard_recommended",
    "trending": "dashboard_trending",
    "search": "dashboard_search",
    "saved": "dashboard_saved",
}


def make_user(username="nav", email="nav@example.com"):
    user = User.objects.create_user(
        username=username, email=email, password="Secret!1"
    )
    user.first_name = "Nav Tester"
    user.save()
    return user


def make_posting_employer(username="navhirer", email="navhirer@example.com"):
    """An employer with a company - the only kind of member who can post."""

    from .models import Company

    user = make_user(username=username, email=email)

    profile = user.profile
    profile.role = "employer"
    profile.save()

    Company.objects.create(owner=user, name="Galixo", location="Lahore")

    return user


class SectionUrlTests(TestCase):

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_each_section_has_its_own_address(self):
        for section, name in SECTION_URLS.items():
            self.assertEqual(
                reverse(name),
                f"/dashboard/user/{section}/",
                msg=f"{section} url",
            )

    def test_opening_a_section_url_opens_that_section(self):
        for section, name in SECTION_URLS.items():
            response = self.client.get(reverse(name))

            self.assertEqual(response.context["active_section"], section)
            self.assertContains(
                response,
                f'<div class="section active" id="{section}">',
                msg_prefix=section,
            )

    def test_only_one_section_is_ever_open(self):
        response = self.client.get(reverse("dashboard_saved"))

        self.assertEqual(response.content.decode().count('class="section active"'), 1)

    def test_reloading_a_section_url_keeps_that_section(self):
        first = self.client.get(reverse("dashboard_trending"))
        again = self.client.get(reverse("dashboard_trending"))

        self.assertEqual(first.context["active_section"], "trending")
        self.assertEqual(again.context["active_section"], "trending")

    def test_the_bare_dashboard_opens_the_profile(self):
        response = self.client.get(reverse("user_dashboard"))

        self.assertEqual(response.context["active_section"], "profile")

    def test_the_sidebar_links_to_every_section_url(self):
        response = self.client.get(reverse("user_dashboard"))

        for name in SECTION_URLS.values():
            self.assertContains(response, f'href="{reverse(name)}"')
        self.assertNotContains(response, "no_back.js")

    def test_the_sidebar_does_not_offer_posting(self):
        """Posting belongs to employers, who have a dashboard of their own."""

        response = self.client.get(reverse("user_dashboard"))

        self.assertNotContains(response, f'href="{reverse("post_job")}"')

    def test_the_sidebar_marks_the_open_section(self):
        response = self.client.get(reverse("dashboard_saved"))

        self.assertEqual(active_sidebar_ids(response), ["nav-saved"])

    def test_the_sidebar_marks_exactly_one_entry_per_section(self):
        for section, name in SECTION_URLS.items():
            response = self.client.get(reverse(name))

            self.assertEqual(
                active_sidebar_ids(response), [f"nav-{section}"], msg=section
            )

    def test_a_section_url_is_private(self):
        self.client.logout()

        response = self.client.get(reverse("dashboard_saved"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("signin"), response["Location"])


class BrowserNavigationAuthTests(TestCase):

    def setUp(self):
        self.user = make_user(username="history", email="history@example.com")

    def test_signing_in_opens_my_profile(self):
        response = self.client.post(
            reverse("signin"),
            {"email": "history@example.com", "password": "Secret!1"},
        )

        self.assertRedirects(
            response,
            reverse("user_dashboard"),
            fetch_redirect_response=False,
        )
        profile_response = self.client.get(response["Location"])
        self.assertEqual(profile_response.context["active_section"], "profile")

    def test_authenticated_users_are_redirected_from_guest_only_pages(self):
        self.client.force_login(self.user)

        guest_pages = [
            reverse("signin"),
            reverse("login"),
            reverse("signup"),
            reverse("signup_employee"),
            reverse("signup_employer"),
            reverse("password_reset"),
            reverse("password_reset_done"),
            reverse(
                "password_reset_confirm",
                kwargs={"uidb64": "unused", "token": "unused"},
            ),
            reverse("password_reset_complete"),
        ]

        for url in guest_pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertRedirects(
                    response,
                    reverse("dashboard"),
                    fetch_redirect_response=False,
                )

    def test_private_pages_are_not_cached_and_require_login_after_logout(self):
        self.client.force_login(self.user)
        private_pages = [
            reverse("dashboard"),
            reverse("user_dashboard"),
            reverse("dashboard_profile"),
            reverse("dashboard_search"),
            reverse("dashboard_trending"),
            reverse("dashboard_saved"),
            reverse("edit_profile"),
            reverse("dashboard_notifications"),
            reverse("dashboard_settings"),
            reverse("cv_upload"),
            reverse("preferences"),
            reverse("edit_cv_data"),
            reverse("saved_jobs"),
            reverse("applied_jobs"),
            reverse("employer_dashboard"),
            reverse("employer_company"),
            reverse("admin_dashboard"),
            reverse("admin_profile"),
            reverse("superadmin_dashboard"),
            reverse("superadmin_profile"),
        ]

        for url in private_pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(
                    response["Cache-Control"],
                    "no-store, no-cache, must-revalidate, max-age=0",
                )
                self.assertEqual(response["Pragma"], "no-cache")

        logout_response = self.client.get(reverse("logout"))
        self.assertRedirects(
            logout_response,
            reverse("home"),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            logout_response["Cache-Control"],
            "no-store, no-cache, must-revalidate, max-age=0",
        )

        for url in private_pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("signin"), response["Location"])

    def test_public_pages_remain_cacheable_while_signed_in(self):
        job = Job.objects.create(
            title="Public Django role",
            company="WorkVista",
            location="Lahore",
            source="mustakbil",
            job_link="https://example.com/jobs/public",
        )
        self.client.force_login(self.user)

        public_pages = (
            reverse("home"),
            reverse("job_detail", args=[job.id]),
            reverse("search_jobs"),
            reverse("trending_jobs"),
            reverse("signin"),
            reverse("signup"),
            reverse("password_reset"),
        )
        for url in public_pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertNotIn("Cache-Control", response)
                self.assertNotIn("Pragma", response)

    def test_authenticated_static_and_media_responses_are_not_cache_modified(self):
        request_factory = RequestFactory()
        middleware = NoCacheAuthenticatedMiddleware(
            lambda request: HttpResponse("asset")
        )

        for path in ("/static/css/base.css", "/media/cvs/private.pdf"):
            with self.subTest(path=path):
                request = request_factory.get(path)
                request.user = self.user
                response = middleware(request)
                self.assertNotIn("Cache-Control", response)
                self.assertNotIn("Pragma", response)

    def test_public_home_and_job_details_remain_cacheable_for_visitors(self):
        job = Job.objects.create(
            title="Public Django role",
            company="WorkVista",
            location="Lahore",
            source="mustakbil",
            job_link="https://example.com/jobs/public",
        )

        public_pages = (
            reverse("home"),
            reverse("search_jobs"),
            reverse("trending_jobs"),
            reverse("job_detail", args=[job.id]),
            reverse("signin"),
            reverse("signup"),
            reverse("password_reset"),
        )
        for url in public_pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("Cache-Control", response)
                self.assertNotIn("Pragma", response)
                self.assertNotContains(response, "no_back.js")


class RoleIsolationTests(TestCase):

    def setUp(self):
        self.role_users = {}
        for role in ("user", "employer", "admin", "superadmin"):
            user = make_user(
                username=f"role_{role}",
                email=f"{role}@example.com",
            )
            profile = user.profile
            profile.role = role
            profile.save()
            self.role_users[role] = user

        self.pages_by_role = {
            "user": (
                "dashboard_profile",
                "edit_profile",
                "dashboard_settings",
                "cv_upload",
                "preferences",
                "edit_cv_data",
                "saved_jobs",
                "applied_jobs",
            ),
            "employer": ("employer_company",),
            "admin": ("admin_dashboard", "admin_profile"),
            "superadmin": ("superadmin_dashboard", "superadmin_profile"),
        }

    def test_each_role_is_blocked_from_every_other_roles_pages(self):
        for actor_role, user in self.role_users.items():
            self.client.force_login(user)
            for page_role, page_names in self.pages_by_role.items():
                if actor_role == page_role:
                    continue
                for page_name in page_names:
                    with self.subTest(actor=actor_role, page=page_name):
                        response = self.client.get(reverse(page_name))
                        self.assertIn(response.status_code, (302, 403))

    def test_signed_in_users_are_routed_from_login_and_register_to_their_role(self):
        role_dashboards = {
            "user": "user_dashboard",
            "employer": "employer_dashboard",
            "admin": "admin_dashboard",
            "superadmin": "superadmin_dashboard",
        }
        guest_pages = (
            "signin",
            "login",
            "signup",
            "signup_employee",
            "signup_employer",
        )

        for role, user in self.role_users.items():
            self.client.force_login(user)
            for page_name in guest_pages:
                with self.subTest(role=role, page=page_name):
                    response = self.client.get(reverse(page_name))
                    self.assertRedirects(
                        response,
                        reverse("dashboard"),
                        fetch_redirect_response=False,
                    )

            response = self.client.get(reverse("dashboard"))
            self.assertRedirects(
                response,
                reverse(role_dashboards[role]),
                fetch_redirect_response=False,
            )


class ProfileFormReturnTests(TestCase):
    """Saving on My Profile must come back to My Profile."""

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        CVData.objects.get_or_create(user=self.user)

    def test_saving_preferences_returns_to_settings(self):
        response = self.client.post(
            reverse("dashboard_settings"),
            {
                "update_preferences": "1",
                "job_title": "Django Developer",
                "location": "Lahore",
                "job_type": ["Full-time", "Remote"],
                "salary": "90000",
            },
        )

        self.assertRedirects(response, reverse("dashboard_settings"))

    def test_saving_preferences_stores_what_was_entered(self):
        # Preferences moved from My Profile to Settings; what they do
        # is unchanged, only where the form lives.
        self.client.post(
            reverse("dashboard_settings"),
            {
                "update_preferences": "1",
                "job_title": "Django Developer",
                "location": "Lahore",
                "job_type": ["Full-time", "Remote"],
                "salary": "90000",
            },
        )

        profile = Profile.objects.get(user=self.user)

        self.assertEqual(profile.job_title, "Django Developer")
        self.assertEqual(profile.location, "Lahore")
        self.assertEqual(profile.job_type, ["Full-time", "Remote"])
        self.assertEqual(profile.salary, 90000)

    def test_saving_preferences_confirms_it_saved(self):
        response = self.client.post(
            reverse("dashboard_settings"),
            {
                "update_preferences": "1",
                "job_title": "Django Developer",
                "location": "Lahore",
                "job_type": ["Full-time"],
                "salary": "90000",
            },
            follow=True,
        )

        self.assertContains(response, "Preferences saved")

    def test_the_confirmation_is_a_dismissable_toast(self):
        response = self.client.post(
            reverse("dashboard_profile"),
            {
                "update_preferences": "1",
                "job_title": "Django Developer",
                "location": "Lahore",
                "job_type": ["Full-time"],
                "salary": "90000",
            },
            follow=True,
        )

        self.assertContains(response, "toast")

    def test_a_rejected_preference_returns_to_settings_too(self):
        response = self.client.post(
            reverse("dashboard_settings"),
            {"update_preferences": "1", "job_title": ""},
        )

        self.assertRedirects(response, reverse("dashboard_settings"))

    def test_updating_the_email_returns_to_the_profile(self):
        response = self.client.post(
            reverse("dashboard_profile"),
            {"update_email": "1", "email": "changed@example.com"},
        )

        self.assertRedirects(response, reverse("dashboard_profile"))

    def test_an_unrecognised_post_returns_to_the_profile(self):
        response = self.client.post(reverse("dashboard_profile"), {})

        self.assertRedirects(response, reverse("dashboard_profile"))


class OnboardingPreferencesTests(TestCase):

    def setUp(self):
        self.user = make_user(username="onboarding")
        self.client.force_login(self.user)

    def test_preference_form_shows_salary_currency_and_month_suffix(self):
        response = self.client.get(reverse("preferences"))

        self.assertContains(response, 'name="salary_currency"')
        self.assertContains(response, 'value="PKR"')
        self.assertContains(response, "/month")
        self.assertContains(response, 'type="text" id="salary"')

    def test_preference_save_persists_currency_and_amount(self):
        response = self.client.post(
            reverse("preferences"),
            {
                "job_title": "Django Developer",
                "salary_currency": "USD",
                "salary": "90000",
            },
        )

        self.user.profile.refresh_from_db()

        self.assertEqual(self.user.profile.salary, 90000)
        self.assertEqual(self.user.profile.salary_currency, "USD")
        self.assertRedirects(response, reverse("user_dashboard"))

    def test_preference_save_allows_blank_salary(self):
        response = self.client.post(
            reverse("preferences"),
            {
                "job_title": "Django Developer",
                "salary_currency": "EUR",
                "salary": "",
            },
        )

        self.user.profile.refresh_from_db()

        self.assertIsNone(self.user.profile.salary)
        self.assertEqual(self.user.profile.salary_currency, "EUR")
        self.assertRedirects(response, reverse("user_dashboard"))

    def test_preference_save_rejects_non_digit_salary(self):
        response = self.client.post(
            reverse("preferences"),
            {
                "job_title": "Django Developer",
                "salary_currency": "USD",
                "salary": "90000x",
            },
        )

        self.user.profile.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Salary must contain digits only.")
        self.assertIsNone(self.user.profile.salary)
        self.assertEqual(self.user.profile.salary_currency, "PKR")


class SectionFormTargetTests(TestCase):
    """A section's own form must submit back to that section."""

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_the_search_form_submits_to_the_search_section(self):
        response = self.client.get(reverse("dashboard_search"))

        self.assertContains(
            response,
            f'<form method="get" class="search-bar" action="{reverse("dashboard_search")}">',
        )

    def test_the_trending_filter_submits_to_the_trending_section(self):
        response = self.client.get(reverse("dashboard_trending"))

        self.assertContains(
            response,
            f'<form method="get" class="filter-bar" action="{reverse("dashboard_trending")}">',
        )

    def test_searching_stays_on_the_search_section(self):
        Job.objects.create(title="Django Developer", source="workvista")

        response = self.client.get(reverse("dashboard_search"), {"q": "django"})

        self.assertEqual(response.context["active_section"], "search")
        self.assertEqual(
            [job.title for job in response.context["jobs"]], ["Django Developer"]
        )

    def test_filtering_trending_stays_on_the_trending_section(self):
        response = self.client.get(
            reverse("dashboard_trending"), {"trend_window": "7d"}
        )

        self.assertEqual(response.context["active_section"], "trending")


class PostJobNavigationTests(TestCase):

    def setUp(self):
        self.user = make_posting_employer()
        self.client.force_login(self.user)

    def test_post_a_job_marks_its_own_sidebar_entry(self):
        response = self.client.get(reverse("post_job"))

        self.assertEqual(active_sidebar_ids(response), ["nav-post-job"])

    def test_it_does_not_mark_any_dashboard_section(self):
        response = self.client.get(reverse("post_job"))

        self.assertNotContains(response, 'class="section active"')

    def test_posting_a_job_returns_to_the_post_a_job_page(self):
        response = self.client.post(
            reverse("post_job"),
            {
                "title": "Django Developer",
                "branch": "",
                "description": "Build things.",
                "category": "web",
                "job_type": "Full-time",
                "salary_min": 60000,
                "salary_max": 90000,
                "job_link": "https://example.com/apply",
            },
        )

        self.assertRedirects(response, reverse("post_job"))

    def test_editing_a_job_returns_to_the_post_a_job_page(self):
        job = Job.objects.create(
            title="Old", source="workvista", posted_by=self.user
        )

        response = self.client.post(
            reverse("edit_posted_job", args=[job.id]),
            {
                "title": "New",
                "branch": "",
                "description": "Build things.",
                "category": "web",
                "job_type": "Full-time",
                "salary_min": 60000,
                "salary_max": 90000,
                "job_link": "https://example.com/apply",
            },
        )

        self.assertRedirects(response, reverse("post_job"))

    def test_deleting_a_job_returns_to_the_post_a_job_page(self):
        job = Job.objects.create(
            title="Old", source="workvista", posted_by=self.user
        )

        response = self.client.post(reverse("delete_posted_job", args=[job.id]))

        self.assertRedirects(response, reverse("post_job"))


class SavedJobNavigationTests(TestCase):

    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.job = Job.objects.create(title="Django Developer", source="workvista")

    def test_saving_from_a_page_returns_to_that_page(self):
        # The bookmark button carries the page it was pressed on, so it
        # can't dump the visitor back on some other tab.
        response = self.client.post(
            reverse("toggle_save_job", args=[self.job.id]),
            {"next": reverse("dashboard_search")},
        )

        self.assertRedirects(response, reverse("dashboard_search"))

    def test_an_off_site_next_is_refused(self):
        response = self.client.post(
            reverse("toggle_save_job", args=[self.job.id]),
            {"next": "https://evil.example.com/"},
        )

        self.assertNotIn("evil.example.com", response["Location"])


# =========================================================
# ADMIN SHELL
# =========================================================
#
# Same defect as the user dashboard had: the admin tabs read ?section=
# from the URL on load, but clicking one never put it there - so a
# reload, or the redirect after running a scraper, snapped back to the
# first tab.

def make_staff(role, username, email):
    user = User.objects.create_user(
        username=username, email=email, password="Secret!1"
    )
    Profile.objects.filter(user=user).update(role=role)
    return user


class AdminNavigationTests(TestCase):

    sections = ["profile", "users", "scraper", "employers"]
    dashboard = "admin_dashboard"

    def setUp(self):
        self.user = make_staff("admin", "boss", "boss@example.com")
        self.client.force_login(self.user)

    def test_admin_navigation_does_not_include_manage_admins(self):
        admin = make_staff(
            "admin", "navigation-admin", "navigation-admin@example.com"
        )
        self.client.force_login(admin)
        response = self.client.get(reverse("admin_dashboard"))

        self.assertNotContains(response, "Manage admins")

    def test_each_tab_is_a_link_that_puts_the_section_in_the_url(self):
        response = self.client.get(reverse(self.dashboard))

        for section in self.sections:
            self.assertContains(
                response,
                f'href="{reverse(self.dashboard)}?section={section}"',
            )

    def test_no_tab_relies_on_a_click_handler(self):
        response = self.client.get(reverse(self.dashboard))

        self.assertNotContains(response, "showSection(")

    def test_the_requested_section_is_the_one_opened(self):
        for section in self.sections:
            response = self.client.get(
                reverse(self.dashboard), {"section": section}
            )

            self.assertContains(
                response,
                f'<div class="section active" id="{section}">',
                msg_prefix=section,
            )

    def test_the_first_tab_opens_by_default(self):
        response = self.client.get(reverse(self.dashboard))

        self.assertContains(
            response, '<div class="section active" id="profile">'
        )

    def test_an_unknown_section_falls_back_to_profile(self):
        response = self.client.get(reverse(self.dashboard), {"section": "bogus"})

        self.assertContains(
            response, '<div class="section active" id="profile">'
        )

    def test_exactly_one_tab_is_open(self):
        response = self.client.get(
            reverse(self.dashboard), {"section": self.sections[-1]}
        )

        self.assertEqual(
            response.content.decode().count('class="section active"'), 1
        )

    def test_messages_are_shown_as_toasts(self):
        response = self.client.get(reverse(self.dashboard))

        self.assertNotContains(response, 'class="alert alert-')


class SuperAdminNavigationTests(AdminNavigationTests):

    sections = ["profile", "admins", "users", "scraper", "employers"]
    dashboard = "superadmin_dashboard"

    def setUp(self):
        self.user = make_staff("superadmin", "chief", "chief@example.com")
        self.client.force_login(self.user)

    def test_superadmin_navigation_includes_manage_admins(self):
        response = self.client.get(reverse(self.dashboard))

        self.assertContains(response, "Manage admins")

    def test_superadmin_can_create_admin(self):
        response = self.client.post(
            reverse("add_admin"),
            {
                "username": "New Admin",
                "email": "new.admin@example.com",
                "password": "secret1",
            },
        )

        created_user = User.objects.get(email="new.admin@example.com")
        self.assertEqual(created_user.first_name, "New Admin")
        self.assertTrue(created_user.check_password("secret1"))
        self.assertEqual(Profile.objects.get(user=created_user).role, "admin")
        self.assertRedirects(
            response, "/dashboard/superadmin/?section=admins"
        )

    def test_superadmin_cannot_create_admin_with_invalid_email(self):
        response = self.client.post(
            reverse("add_admin"),
            {
                "username": "New Admin",
                "email": "not-an-email",
                "password": "secret1",
            },
        )

        self.assertFalse(User.objects.filter(username="New Admin").exists())
        self.assertRedirects(
            response, "/dashboard/superadmin/?section=admins"
        )
