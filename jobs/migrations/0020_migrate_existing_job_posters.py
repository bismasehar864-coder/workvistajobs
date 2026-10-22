from django.db import migrations

from . import _employer_backfill


def forwards(apps, schema_editor):
    _employer_backfill(
        apps.get_model("auth", "User"),
        apps.get_model("jobs", "Profile"),
        apps.get_model("jobs", "Job"),
        apps.get_model("jobs", "Company"),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0019_alter_profile_role_company_companybranch_job_branch"),
    ]

    operations = [
        # Not reversible: this migration cannot know which accounts were
        # already employers before it ran, so guessing on the way back
        # would silently demote real employer accounts.
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
