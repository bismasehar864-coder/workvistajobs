# jobs/recommender/filters.py
#
# Time-window filtering for job listings ("posted in the last 24
# hours / 7 days / 30 days"). Always filters on Job.first_seen_at -
# the moment our scraper first saved this job_link - never on
# scraped_at (which updates on every re-scrape, even for jobs we've
# seen many times before) and never on the free-text `posted` field
# (format varies per source - "3 days ago" vs "02 July 2026" - and
# isn't reliably parseable across all four scrapers). See TRENDING.md.

from django.utils import timezone

TIME_WINDOWS = {
    "24h": timezone.timedelta(hours=24),
    "7d": timezone.timedelta(days=7),
    "30d": timezone.timedelta(days=30),
}

TIME_WINDOW_LABELS = {
    "24h": "Past 24 hours",
    "7d": "Past week",
    "30d": "Past month",
}


def apply_time_window(queryset, window_key):
    delta = TIME_WINDOWS.get(window_key)

    if not delta:
        return queryset

    cutoff = timezone.now() - delta

    return queryset.filter(first_seen_at__gte=cutoff)
