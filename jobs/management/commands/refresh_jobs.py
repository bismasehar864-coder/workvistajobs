"""Refresh stale job sources.

The same entry point the traffic trigger uses (jobs/refresh.py), so a
cron line and a page view behave identically - including the lock, so
the two can safely be used together.

    # Check every minute; all sources run together after the shared cooldown.
    * * * * *  cd /path/to/workvista && venv311/bin/python manage.py refresh_jobs
"""

from django.core.management.base import BaseCommand

from jobs import refresh


class Command(BaseCommand):

    help = "Re-scrape job sources whose cooldown has elapsed."

    def add_arguments(self, parser):

        parser.add_argument(
            "--sources",
            default="",
            help=(
                "Comma-separated source keys to consider "
                f"({', '.join(sorted(refresh.SCRAPER_COMMANDS))}). "
                "Defaults to all supported sources."
            ),
        )

        parser.add_argument(
            "--force",
            action="store_true",
            help="Scrape every named source even if it was refreshed recently.",
        )

    def handle(self, *args, **options):

        sources = self._resolve_sources(options)

        self.stdout.write(f"Considering: {', '.join(sources)}")

        summary = refresh.run_refresh(
            sources=sources,
            force=options["force"],
            automatic_batch=not bool(options["sources"]),
        )

        if not summary["started"]:

            self.stdout.write(
                self.style.WARNING(f"No refresh started - {summary['reason']}.")
            )

            return

        failed = 0

        for source, result in summary["results"].items():

            if result["status"] == "success":

                self.stdout.write(
                    self.style.SUCCESS(
                        f"  {source}: success ({result['new_jobs']} new)"
                    )
                )

            else:
                failed += 1

                self.stdout.write(
                    self.style.ERROR(f"  {source}: failed - {result['error']}")
                )

        self.stdout.write(
            self.style.SUCCESS("Refresh complete.")
            if not failed
            else self.style.WARNING(f"Refresh complete - {failed} source(s) failed.")
        )

    def _resolve_sources(self, options):

        if options["sources"]:

            return [
                part.strip()
                for part in options["sources"].split(",")
                if part.strip()
            ]

        return list(refresh.AUTO_SOURCES)
