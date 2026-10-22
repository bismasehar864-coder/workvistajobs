"""Match new jobs to people, and email them the result.

The real driver for this feature. Both halves in one command so a
single cron line is the whole setup:

    # every morning at nine
    0 9 * * *  cd /path/to/workvista && venv311/bin/python manage.py send_job_alerts

Matching also runs off the back of every scrape (jobs/refresh.py), so
by the time this runs the notifications usually already exist and it
only sends. It re-runs matching anyway because it is cheap and because
it makes this command correct on its own, with no scraper involved.
"""

from django.core.management.base import BaseCommand

from jobs.alerts.digest import pending_for, send_pending_digests
from jobs.alerts.notifications import generate_notifications
from jobs.models import Profile


class Command(BaseCommand):

    help = "Match newly scraped jobs to members and email them a digest."

    def add_arguments(self, parser):

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be sent without sending or stamping anything.",
        )

        parser.add_argument(
            "--skip-matching",
            action="store_true",
            help="Only send what is already waiting; don't look for new matches.",
        )

    def handle(self, *args, **options):

        if not options["skip_matching"] and not options["dry_run"]:

            created = generate_notifications()

            self.stdout.write(
                f"Created {created} notification{'' if created == 1 else 's'}."
            )

        elif not options["skip_matching"]:

            self.stdout.write("Dry run: skipping matching, which would write rows.")

        if options["dry_run"]:

            waiting = 0

            for profile in Profile.objects.filter(
                role="user", email_job_alerts=True
            ).select_related("user"):

                count = pending_for(profile.user).count()

                if count and profile.user.email:

                    waiting += 1

                    self.stdout.write(
                        f"  would email {profile.user.email}: {count} job(s)"
                    )

            self.stdout.write(f"Dry run: would email {waiting} user(s).")

            return

        sent = send_pending_digests()

        self.stdout.write(
            self.style.SUCCESS(f"Sent {sent} email{'' if sent == 1 else 's'}.")
        )
