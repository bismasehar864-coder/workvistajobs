"""Settings come from the environment, not from settings.py.

The secret key, the database password and the mail credentials used to
be literals in config/settings.py - which meant they were in every copy
of the project and could not be changed per machine. They now come from
a .env file that is gitignored, read by config/settings.py::env().
"""

import os
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from config.settings import env, env_bool, env_list


class EnvHelperTests(TestCase):

    def test_it_reads_a_variable(self):
        with patch.dict(os.environ, {"WV_TEST_KEY": "value"}):
            self.assertEqual(env("WV_TEST_KEY"), "value")

    def test_it_falls_back_to_the_default(self):
        self.assertEqual(env("WV_TEST_ABSENT", "fallback"), "fallback")

    def test_a_required_variable_that_is_missing_says_which_one(self):
        with self.assertRaises(ImproperlyConfigured) as caught:
            env("WV_TEST_REQUIRED_MISSING", required=True)

        message = str(caught.exception)

        self.assertIn("WV_TEST_REQUIRED_MISSING", message)
        self.assertIn(".env", message)

    def test_a_required_variable_set_to_empty_counts_as_missing(self):
        """An empty password is not a password."""

        with patch.dict(os.environ, {"WV_TEST_EMPTY": ""}):
            with self.assertRaises(ImproperlyConfigured):
                env("WV_TEST_EMPTY", required=True)


class EnvBoolTests(TestCase):

    def test_the_usual_ways_of_writing_true(self):
        for written in ("1", "true", "True", "TRUE", "yes", "on"):
            with patch.dict(os.environ, {"WV_TEST_BOOL": written}):
                self.assertTrue(env_bool("WV_TEST_BOOL"), msg=written)

    def test_anything_else_is_false(self):
        for written in ("0", "false", "False", "no", "off", ""):
            with patch.dict(os.environ, {"WV_TEST_BOOL": written}):
                self.assertFalse(env_bool("WV_TEST_BOOL"), msg=written)

    def test_it_falls_back_to_the_default(self):
        self.assertTrue(env_bool("WV_TEST_BOOL_ABSENT", True))
        self.assertFalse(env_bool("WV_TEST_BOOL_ABSENT", False))


class EnvListTests(TestCase):

    def test_it_splits_on_commas_and_trims(self):
        with patch.dict(os.environ, {"WV_TEST_LIST": "a, b ,c"}):
            self.assertEqual(env_list("WV_TEST_LIST"), ["a", "b", "c"])

    def test_an_empty_value_is_an_empty_list_not_a_blank_entry(self):
        """ALLOWED_HOSTS = [''] would be a host nobody can ever match."""

        with patch.dict(os.environ, {"WV_TEST_LIST": ""}):
            self.assertEqual(env_list("WV_TEST_LIST"), [])

    def test_trailing_commas_do_not_produce_blanks(self):
        with patch.dict(os.environ, {"WV_TEST_LIST": "a,,b,"}):
            self.assertEqual(env_list("WV_TEST_LIST"), ["a", "b"])


class NoSecretsInSettingsTests(TestCase):

    def test_settings_py_contains_no_literal_credentials(self):
        """The whole point of the change. A regression here means a
        password went back into a file that gets shared."""

        source = (settings.BASE_DIR / "config" / "settings.py").read_text()

        for secret in ("Root@1234", "django-insecure-", "tgxv"):
            self.assertNotIn(secret, source)

    def test_the_app_password_is_stripped_of_spaces(self):
        """Google shows it as four groups of four; SMTP wants sixteen
        characters. Either form must work in .env."""

        self.assertNotIn(" ", settings.EMAIL_HOST_PASSWORD)

    def test_a_real_env_file_is_never_committed(self):
        gitignore = (settings.BASE_DIR / ".gitignore").read_text()

        self.assertIn(".env", gitignore)
