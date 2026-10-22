from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Profile


class StaffProfileFlowTests(TestCase):
    role = "admin"
    profile_url = "admin_profile"
    update_url = "admin_update_profile"
    dashboard_url = "admin_dashboard"

    def setUp(self):
        self.user = User.objects.create_user(
            username=f"{self.role}-account",
            email=f"{self.role}@example.com",
            password="Original-password-47!",
            first_name="Original Name",
        )
        Profile.objects.filter(user=self.user).update(role=self.role)
        User.objects.create_user(
            username="existing-account",
            email="taken@example.com",
            password="Original-password-47!",
        )
        self.client.force_login(self.user)

    def profile_data(self, **overrides):
        data = {
            "name": "Updated Name",
            "email": " UPDATED@EXAMPLE.COM ",
            "new_password": "",
            "confirm_password": "",
        }
        data.update(overrides)
        return data

    def test_profile_and_update_page_show_current_user_fields(self):
        response = self.client.get(reverse(self.profile_url))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Original Name")
        self.assertContains(response, f"{self.role}@example.com")
        self.assertContains(response, reverse(self.update_url))

        response = self.client.get(reverse(self.update_url))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="Original Name"')
        self.assertContains(response, f'value="{self.role}@example.com"')
        self.assertContains(response, "Update Profile")
        self.assertContains(response, "toggleProfilePassword")
        self.assertContains(response, "Name can only contain letters.")
        self.assertContains(response, "Enter a valid email address.")

    def test_update_saves_normalized_account_data_and_optional_password(self):
        new_password = "Cobalt-River-47!Maple"
        response = self.client.post(
            reverse(self.update_url),
            self.profile_data(
                new_password=new_password,
                confirm_password=new_password,
            ),
        )
        self.assertRedirects(
            response,
            reverse(self.profile_url),
            fetch_redirect_response=False,
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Updated Name")
        self.assertEqual(self.user.email, "updated@example.com")
        self.assertTrue(self.user.check_password(new_password))

        response = self.client.get(reverse(self.profile_url))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Updated Name")
        self.assertContains(response, "updated@example.com")
        self.assertContains(response, "Profile updated successfully.")

        self.client.logout()
        response = self.client.post(
            reverse("signin"),
            {"email": "updated@example.com", "password": new_password},
        )
        self.assertRedirects(response, reverse(self.dashboard_url))

    def test_update_without_password_keeps_existing_password(self):
        response = self.client.post(
            reverse(self.update_url),
            self.profile_data(),
        )
        self.assertRedirects(response, reverse(self.profile_url))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Original-password-47!"))

    def test_invalid_name_email_and_duplicate_email_are_rejected(self):
        invalid_submissions = (
            ({"name": "   "}, "name"),
            ({"name": "Updated1"}, "name"),
            ({"name": "Updated!"}, "name"),
            ({"email": "not-an-email"}, "email"),
            ({"email": "TAKEN@example.com"}, "email"),
        )
        for values, field in invalid_submissions:
            with self.subTest(values=values):
                response = self.client.post(
                    reverse(self.update_url),
                    self.profile_data(**values),
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)
                if values.get("name") in {"Updated1", "Updated!"}:
                    self.assertContains(response, "Name can only contain letters.")
                if values.get("email") == "not-an-email":
                    self.assertContains(response, "Enter a valid email address.")
                if values.get("email", "").upper() == "TAKEN@EXAMPLE.COM":
                    self.assertContains(response, "This email is already in use.")

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Original Name")
        self.assertEqual(self.user.email, f"{self.role}@example.com")

    def test_mismatched_and_weak_passwords_are_rejected_and_not_refilled(self):
        response = self.client.post(
            reverse(self.update_url),
            self.profile_data(
                new_password="Cobalt-River-47!Maple",
                confirm_password="different-password",
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("confirm_password", response.context["form"].errors)
        self.assertNotContains(response, 'value="Cobalt-River-47!Maple"')

        response = self.client.post(
            reverse(self.update_url),
            self.profile_data(new_password="weak", confirm_password="weak"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("new_password", response.context["form"].errors)
        self.assertNotContains(response, 'value="weak"')

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Original-password-47!"))


class SuperAdminProfileFlowTests(StaffProfileFlowTests):
    role = "superadmin"
    profile_url = "superadmin_profile"
    update_url = "superadmin_update_profile"
    dashboard_url = "superadmin_dashboard"


class StaffProfileAccessTests(TestCase):
    def setUp(self):
        self.accounts = {}
        for role in ("admin", "superadmin", "user", "employer"):
            user = User.objects.create_user(
                username=f"{role}-account",
                email=f"{role}@example.com",
                password="Original-password-47!",
            )
            Profile.objects.filter(user=user).update(role=role)
            self.accounts[role] = user

    def test_staff_profile_and_update_urls_enforce_role(self):
        role_urls = {
            "admin": ("admin_profile", "admin_update_profile"),
            "superadmin": ("superadmin_profile", "superadmin_update_profile"),
        }
        for role, names in role_urls.items():
            for account_role, user in self.accounts.items():
                self.client.force_login(user)
                for name in names:
                    with self.subTest(role=role, account_role=account_role, url=name):
                        response = self.client.get(reverse(name))
                        expected_status = 200 if role == account_role else 403
                        self.assertEqual(response.status_code, expected_status)
                self.client.logout()

    def test_anonymous_visitors_are_redirected_to_signin(self):
        for name in (
            "admin_profile",
            "admin_update_profile",
            "superadmin_profile",
            "superadmin_update_profile",
        ):
            with self.subTest(url=name):
                response = self.client.get(reverse(name))
                self.assertRedirects(
                    response,
                    f"{reverse('signin')}?next={reverse(name)}",
                    fetch_redirect_response=False,
                )

    def test_update_form_rejects_requests_without_csrf(self):
        client = self.client_class(enforce_csrf_checks=True)
        client.force_login(self.accounts["admin"])
        response = client.get(reverse("admin_update_profile"))
        self.assertEqual(response.status_code, 200)
        response = client.post(
            reverse("admin_update_profile"),
            {
                "name": "Changed Name",
                "email": "admin@example.com",
                "new_password": "",
                "confirm_password": "",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_profile_pages_are_read_only(self):
        self.client.force_login(self.accounts["admin"])
        response = self.client.post(
            reverse("admin_profile"),
            {"name": "Changed Name", "email": "changed@example.com"},
        )
        self.assertEqual(response.status_code, 405)
        self.accounts["admin"].refresh_from_db()
        self.assertEqual(self.accounts["admin"].first_name, "")
