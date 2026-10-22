"""Shared guard for the job-seeker-only dashboard sections."""

from .models import Profile


def seeker_profile(request):
    """The signed-in job seeker's profile, or None if they aren't one.

    Employers, admins and super admins have their own dashboards;
    callers redirect them to `dashboard`, which routes by role rather
    than guessing where they belong.
    """

    profile = Profile.objects.filter(user=request.user).first()

    if profile is None or not profile.is_job_seeker:
        return None

    return profile
