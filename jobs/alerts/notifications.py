"""Create dashboard notifications for new jobs that match a job seeker."""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from jobs.models import CVData, Job, Notification, Profile, public_job_queryset

from .matching import job_match_details, user_skills_for_matching


logger = logging.getLogger(__name__)

LOOKBACK_WHEN_NEVER_CHECKED = timedelta(days=1)
MAX_PER_RUN = 20


def _describe(job):
    """Include job context and the concise dashboard match label."""

    details = " · ".join(part for part in (job.company, job.location) if part)
    return f"{details} · Matched" if details else "Matched"


def queue_notification_emails(notification_ids):
    notification_ids = tuple(notification_ids)
    if not notification_ids or not getattr(settings, "JOB_ALERTS_ENABLED", True):
        return

    def spawn():
        try:
            from .digest import spawn_notification_emails

            spawn_notification_emails(notification_ids)
        except Exception:
            logger.exception(
                "job alerts: could not queue notification emails %s",
                notification_ids,
            )

    transaction.on_commit(spawn)


def _create_notification(profile, job, score, matched_fields, now):
    return Notification.objects.get_or_create(
        user=profile.user,
        job=job,
        kind="job_match",
        defaults={
            "title": job.title,
            "body": _describe(job),
            "score": score,
            "created_at": now,
        },
    )


def notify_job_matches(job, now=None):
    """Create and email matches for one newly published job.

    Employer postings are only eligible after approval. A failed email is
    logged and left unstamped so the existing digest can retry it later.
    """

    now = now or timezone.now()
    if not public_job_queryset().filter(pk=job.pk).exists():
        return 0

    created_total = 0
    notification_ids = []
    profiles = Profile.objects.filter(role="user").select_related("user")

    for profile in profiles:
        cv_data = CVData.objects.filter(user=profile.user).first()
        user_skills = user_skills_for_matching(profile, cv_data)
        score, matched_fields = job_match_details(user_skills, profile, job)
        if not matched_fields:
            continue

        notification, created = _create_notification(
            profile, job, score, matched_fields, now
        )
        if not created:
            continue

        created_total += 1
        notification_ids.append(notification.pk)

    queue_notification_emails(notification_ids)
    return created_total


def generate_notifications(users=None, now=None):
    """Notify job seekers about public jobs added since their last scan."""

    now = now or timezone.now()
    profiles = Profile.objects.filter(role="user").select_related("user")

    if users is not None:
        profiles = profiles.filter(user__in=users)

    created_total = 0
    notification_ids = []

    for profile in profiles:
        cv_data = CVData.objects.filter(user=profile.user).first()
        user_skills = user_skills_for_matching(profile, cv_data)
        if not user_skills:
            continue

        since = profile.alerts_checked_at or (now - LOOKBACK_WHEN_NEVER_CHECKED)
        fresh_jobs = public_job_queryset().filter(first_seen_at__gt=since)
        matches = []

        for job in fresh_jobs:
            score, matched_fields = job_match_details(user_skills, profile, job)
            if matched_fields:
                matches.append((score, job, matched_fields))

        matches.sort(key=lambda item: item[0], reverse=True)
        for score, job, matched_fields in matches[:MAX_PER_RUN]:
            notification, created = _create_notification(
                profile, job, score, matched_fields, now
            )
            if created:
                created_total += 1
                notification_ids.append(notification.pk)

        profile.alerts_checked_at = now
        profile.save(update_fields=["alerts_checked_at"])

    queue_notification_emails(notification_ids)
    return created_total
