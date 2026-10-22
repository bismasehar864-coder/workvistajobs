# jobs/recommender/recommend.py
#
# "Recommended for you" - one ranked list built from a personalization
# score plus a trending tiebreaker. See RECOMMENDATIONS.md for the
# full write-up.
#
# The personalization score blends four independent, optional
# signals - a brand-new user with none of them yet still gets a sane,
# non-empty list rather than nothing:
#
# 1. CV / profile skill match     (40%) - skill_match_score()
# 2. Explicit preferences         (15%) - profile job_title/location/job_type
# 3. CV field match               (20%) - does the job's category match
#    what the CV's most recent job title, education degree, or skills
#    imply the user's field is (infer_user_category() - the same
#    function that defaults Trending's category filter). This is what
#    lets a CS degree or past job title pull relevant jobs up even
#    before any skills/preferences are explicitly set, or before any
#    browsing history exists.
# 4. Behavioral category affinity (25%) - what they've actually viewed
#    or searched most, recency-weighted (jobs/models.py: UserActivity)
#
# Trending score is deliberately NOT a fifth additive term. It's a
# tiebreaker: a job with any real personalization signal always
# outranks one with none, however fresh the zero-signal job is - see
# get_recommended_jobs()'s sort key below for why that matters with a
# small dataset.

from collections import Counter

from django.utils import timezone

from .matcher import (
    skill_match_score,
    title_match_score,
    location_match_score,
    job_type_match_score,
    get_job_skills,
)
from .trending import compute_trending_jobs
from .matcher import normalize_text
from .categorize import infer_user_category

SKILL_WEIGHT = 0.4
PREFERENCE_WEIGHT = 0.15
CV_FIELD_WEIGHT = 0.2
AFFINITY_WEIGHT = 0.25

# How far back activity still counts, and how fast it decays within
# that window - browsing Marketing jobs two months ago shouldn't
# outrank Design jobs someone's actively looking at this week.
AFFINITY_WINDOW_DAYS = 60
AFFINITY_HALF_LIFE_DAYS = 14

# A view is a much stronger signal of interest than a search that may
# not even have returned what the user wanted.
VIEW_WEIGHT = 2
SEARCH_WEIGHT = 1


def log_activity(user, activity_type, category='', job=None):
    """Best-effort activity logging - a logging failure should never
    break the page the user is actually trying to see."""

    if not user or not user.is_authenticated:
        return

    from jobs.models import UserActivity

    try:
        UserActivity.objects.create(
            user=user,
            activity_type=activity_type,
            category=category,
            job=job,
        )
    except Exception:
        pass


def _category_affinity(user):
    """{category: score 0-100}, recency-weighted, from the user's
    recent view/search activity. Empty dict if they have none yet."""

    from jobs.models import UserActivity

    cutoff = timezone.now() - timezone.timedelta(days=AFFINITY_WINDOW_DAYS)

    activity = UserActivity.objects.filter(
        user=user,
        created_at__gte=cutoff,
    ).exclude(category='')

    if not activity:
        return {}

    now = timezone.now()
    weights = Counter()

    for a in activity:
        age_days = max((now - a.created_at).total_seconds() / 86400, 0)
        decay = 0.5 ** (age_days / AFFINITY_HALF_LIFE_DAYS)
        weight = VIEW_WEIGHT if a.activity_type == 'view' else SEARCH_WEIGHT
        weights[a.category] += weight * decay

    if not weights:
        return {}

    top = max(weights.values())

    return {cat: (score / top) * 100 for cat, score in weights.items()}


def get_recommended_jobs(user, profile=None, cv_data=None, limit=12, exclude_job_id=None):
    """The user's personalized ranked job list. Falls back gracefully:
    with no CV, no preferences and no activity yet, this degrades to
    the same order as compute_trending_jobs() - a reasonable default
    rather than an empty list for a brand-new user."""

    if not user or not user.is_authenticated:
        return []

    if profile is None or cv_data is None:
        from jobs.models import Profile, CVData

        if profile is None:
            profile = Profile.objects.filter(user=user).first()

        if cv_data is None:
            cv_data = CVData.objects.filter(user=user).first()

    user_skills = set()

    if profile and profile.skills:
        user_skills.update(
            str(s).lower().strip() for s in profile.skills if s
        )

    if cv_data and cv_data.skills:
        user_skills.update(
            str(s).lower().strip() for s in cv_data.skills if s
        )

    affinity = _category_affinity(user)

    cv_field_category = infer_user_category(profile, cv_data)

    trending = compute_trending_jobs()

    if not trending:
        return []

    max_trending = max((j.trending_score for j in trending), default=1) or 1

    # The same real-world posting sometimes exists as more than one
    # Job row (a source re-scraped it under a link that changed
    # slightly between runs - see TRENDING.md). Recommending someone
    # the exact listing they're already looking at, or the same title
    # three times over, reads as broken even though each row is
    # technically distinct - so dedupe by (title, company) for display.
    exclude_key = None

    if exclude_job_id:
        from jobs.models import Job as JobModel
        current = JobModel.objects.filter(id=exclude_job_id).values('title', 'company').first()
        if current:
            exclude_key = (normalize_text(current['title']), normalize_text(current['company']))

    scored = []
    seen_keys = set()

    for job in trending:

        if exclude_job_id and job.id == exclude_job_id:
            continue

        key = (normalize_text(job.title), normalize_text(job.company))

        if key == exclude_key or key in seen_keys:
            continue

        seen_keys.add(key)

        skill_score = (
            skill_match_score(user_skills, get_job_skills(job))
            if user_skills else 0
        )

        pref_total = 0
        pref_signals = 0

        if profile:
            if profile.job_title:
                pref_total += title_match_score(profile.job_title, job)
                pref_signals += 1
            if profile.location:
                pref_total += location_match_score(profile.location, job.location)
                pref_signals += 1
            if profile.job_type:
                pref_total += job_type_match_score(profile.job_type, job.job_type)
                pref_signals += 1

        pref_score = (pref_total / pref_signals) if pref_signals else 0

        cv_field_score = (
            100 if cv_field_category and job.category == cv_field_category else 0
        )

        affinity_score = affinity.get(job.category, 0)

        trending_norm = (job.trending_score / max_trending) * 100

        # Personalization score and trending score are NOT just
        # summed - a job with real signal (any skill/preference/
        # affinity match) must always outrank one with none, no
        # matter how fresh the zero-signal job is. With a small
        # dataset, many jobs get scraped in the same batch and end up
        # with near-identical trending scores; if trending were added
        # in as a same-scale term, those ties could push completely
        # irrelevant postings up alongside genuine matches. So the
        # sort key is lexicographic: personalization decides first,
        # trending only breaks ties *within* equal personalization -
        # exactly the fallback role described in RECOMMENDATIONS.md.
        personalization_score = round(
            skill_score * SKILL_WEIGHT
            + pref_score * PREFERENCE_WEIGHT
            + cv_field_score * CV_FIELD_WEIGHT
            + affinity_score * AFFINITY_WEIGHT,
            2,
        )

        job.recommend_score = personalization_score
        job._sort_key = (personalization_score, trending_norm)

        scored.append(job)

    scored.sort(key=lambda j: j._sort_key, reverse=True)

    return scored[:limit]
