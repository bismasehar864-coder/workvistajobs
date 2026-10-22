from django.db import migrations, models


def ensure_salary_currency_column(apps, schema_editor):
    profile = apps.get_model("jobs", "Profile")
    table = profile._meta.db_table

    with schema_editor.connection.cursor() as cursor:
        columns = schema_editor.connection.introspection.get_table_description(
            cursor, table
        )

    if not any(column.name == "salary_currency" for column in columns):
        schema_editor.add_field(
            profile,
            profile._meta.get_field("salary_currency"),
        )


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0028_alter_job_source_add_rozee"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    ensure_salary_currency_column,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[],
        ),
        migrations.AlterField(
            model_name="notification",
            name="kind",
            field=models.CharField(
                choices=[
                    ("job_match", "New job match"),
                    ("employer_job_denied", "Employer job not approved"),
                    ("employer_job_approved", "Employer job approved"),
                ],
                db_index=True,
                default="job_match",
                max_length=30,
            ),
        ),
    ]
