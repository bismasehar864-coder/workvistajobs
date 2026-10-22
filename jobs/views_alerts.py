"""Notification and alert views.

Kept out of views.py, which is already 2,800 lines, and out of
views_employer.py, which these have nothing to do with.
"""

from django.shortcuts import render

from .alerts.digest import user_from_token


def alerts_unsubscribe(request, token):
    """One-click unsubscribe from a link in a digest email.

    No login required, by design: someone who wants these emails to
    stop should not have to remember a password first. The token is
    signed, so it cannot be edited into anybody else's account.
    """

    user = user_from_token(token)

    if user is None:

        return render(
            request,
            "alerts/unsubscribed.html",
            {"valid": False},
        )

    profile = getattr(user, "profile", None)

    if profile is not None:

        profile.email_job_alerts = False

        profile.save(update_fields=["email_job_alerts"])

    return render(
        request,
        "alerts/unsubscribed.html",
        {"valid": True, "unsubscribed_user": user},
    )


# =========================================================
# THE NOTIFICATIONS SECTION
# =========================================================

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.utils import timezone

from .models import Notification, Profile


@login_required
def dashboard_notifications(request):
    """Every job that matched this member, newest first.

    Opening the page is what marks them read - that is what the sidebar
    badge means, and making people click each one to clear a count they
    have already seen would be busywork.

    The ones that were unread on arrival keep a marker for this render
    only, captured before the update. Without that, opening the page
    would erase the very thing you opened it to see.
    """

    profile = Profile.objects.filter(user=request.user).first()
    if profile is None or profile.role not in ("user", "employer"):
        return redirect("dashboard")

    # Newest first; score breaks ties for matches from the same scrape.
    notifications = list(
        Notification.objects
        .filter(user=request.user)
        .select_related("job")
        .order_by("-created_at", "-score")[:60]
    )

    newly_read_ids = {
        note.id for note in notifications if note.read_at is None
    }

    if newly_read_ids:
        Notification.objects.filter(id__in=newly_read_ids).update(
            read_at=timezone.now()
        )

    return render(
        request,
        "dashboard/notifications.html",
        {
            "active_section": "notifications",
            "notifications": notifications,
            "newly_read_ids": newly_read_ids,
            "new_count": len(newly_read_ids),
            "is_employer": profile.role == "employer",
            "layout_template": (
                "dashboard/base_employer.html"
                if profile.role == "employer"
                else "dashboard/base_dashboard.html"
            ),
        },
    )
