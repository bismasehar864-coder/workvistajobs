"""Who is allowed where.

Posting a job belongs to companies, so the post form and everything
around it is employer-only. A signed-in job seeker who reaches one of
those pages is told why: redirecting them instead would lose the
explanation and look like the click simply did nothing.
"""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect, render
from django.urls import reverse

from .models import Profile


def employer_required(view):
    """Employers only. Implies login_required - never stack the two."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):

        if not request.user.is_authenticated:

            # Django's own helper rather than a hand-built query string,
            # so an anonymous visitor is bounced in exactly the shape
            # @login_required uses - path separators left unescaped.
            return redirect_to_login(
                request.get_full_path(),
                reverse("signin"),
            )

        profile = getattr(request.user, "profile", None)

        if profile is None or not profile.is_employer:

            return render(
                request,
                "dashboard/employer_only.html",
                status=403,
            )

        return view(request, *args, **kwargs)

    return wrapper


def job_seeker_required(view):
    """Job seekers only. Other signed-in roles return to their dashboard."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(),
                reverse("signin"),
            )

        profile = Profile.objects.filter(user=request.user).first()
        if profile is None or not profile.is_job_seeker:
            return redirect("dashboard")

        return view(request, *args, **kwargs)

    return wrapper
