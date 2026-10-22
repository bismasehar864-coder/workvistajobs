# jobs/recommender/trending.py
#
# Computes a "trending" score for scraped jobs. See TRENDING.md at the
# project root for the full write-up of why this formula was chosen -
# short version: it's the Hacker News "hot" ranking formula, with the
# raw vote count replaced by a weighted blend of two signals we
# actually have (saved-by-users count, and how many other postings
# right now share the same role - market demand), divided by post age
# raised to a gravity exponent so old postings decay out over time.

import math
from collections import Counter

from django.db.models import Count
from django.utils import timezone

from .matcher import normalize_text

# How many days back count towards the "similar postings" demand
# signal. Outside this window a role being common historically
# shouldn't keep boosting today's ranking.
DEMAND_WINDOW_DAYS = 30

# Weight given to real user engagement (a job someone bothered to
# save) vs. market demand (many employers hiring for the same role
# right now). Engagement is a stronger, less noisy signal, so it
# carries more weight.
ENGAGEMENT_WEIGHT = 5
DEMAND_WEIGHT = 2

# Same role as the Hacker News/Reddit "hot" ranking exponent: how fast
# a posting's score decays as it ages. Jobs stay open for weeks, not
# hours, so this is gentler than HN's 1.8.
GRAVITY = 1.5

# Log-dampen both signals so one outlier (a job saved 200 times, or a
# generic title like "Software Engineer" that matches everything)
# can't single-handedly dominate the ranking.
def _log_boost(count):
    return math.log1p(max(count, 0))


def _normalized_title(title):
    return normalize_text(title)


def compute_trending_jobs(queryset=None, limit=None):
    """
    Returns a list of Job instances ordered by trending score,
    descending. Each returned job has a `.trending_score` attribute
    attached for callers that want to display or debug it.
    """

    if queryset is None:
        queryset = _default_queryset()

    jobs = list(
        queryset.annotate(saved_count=Count('savedjob'))
    )

    if not jobs:
        return []

    # Demand signal: how many *other* jobs currently posted (within
    # the demand window) share this job's normalized title. Computed
    # in Python rather than the DB because titles need normalizing
    # (case/whitespace) before they can be grouped.
    cutoff = timezone.now() - timezone.timedelta(days=DEMAND_WINDOW_DAYS)
    recent_titles = Counter(
        _normalized_title(j.title)
        for j in jobs
        if j.first_seen_at >= cutoff
    )

    now = timezone.now()
    scored = []

    for job in jobs:
        age_hours = max(
            (now - job.first_seen_at).total_seconds() / 3600,
            0,
        )

        similar_count = max(
            recent_titles[_normalized_title(job.title)] - 1,
            0,
        )

        signal = (
            1
            + ENGAGEMENT_WEIGHT * _log_boost(job.saved_count)
            + DEMAND_WEIGHT * _log_boost(similar_count)
        )

        job.trending_score = signal / (age_hours + 2) ** GRAVITY
        job.similar_postings = similar_count

        scored.append(job)

    scored.sort(key=lambda j: j.trending_score, reverse=True)

    if limit is not None:
        scored = scored[:limit]

    return scored


def _default_queryset():
    from jobs.models import public_job_queryset

    return public_job_queryset()


def top_job_per_category(limit_categories=6):
    """
    The single highest-trending job in each category, for the
    homepage's "Trending by category" section - one representative
    pick per category rather than one flat list. Categories are
    ordered by their top job's own trending score, so the category
    with the hottest single posting leads.
    """

    ranked = compute_trending_jobs()

    picks = []
    seen_categories = set()

    for job in ranked:

        if job.category in seen_categories:
            continue

        seen_categories.add(job.category)
        picks.append(job)

        if len(picks) >= limit_categories:
            break

    return picks
