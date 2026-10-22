from django.core.management.base import BaseCommand

from jobs.models import Job
from jobs.recommender.categorize import categorize_job


class Command(BaseCommand):

    help = "Recompute Job.category for every job from its title/skills."

    def handle(self, *args, **options):

        updated = 0

        for job in Job.objects.all():

            category = categorize_job(job.title, job.skills)

            if category != job.category:

                job.category = category
                job.save(update_fields=["category"])
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Recomputed categories for {Job.objects.count()} jobs "
                f"({updated} changed)."
            )
        )
