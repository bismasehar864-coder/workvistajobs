"""Phase two: one email a day, listing what the bell already knows.

Separate from notifications.py because this is the part that reaches an
SMTP server and can hang or fail. Notifications are already in the
database by the time this runs; all this does is describe them and
stamp the ones it managed to send.
"""

import logging
import threading

from django.conf import settings
from django.contrib.auth.models import User
from django.db import connection, transaction
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from jobs.models import Notification, Profile


logger = logging.getLogger(__name__)


# Salted so a token minted here can't be replayed against any other
# signed value in the project.
UNSUBSCRIBE_SALT = "job-alerts-unsubscribe"


def unsubscribe_token(user):
    """A signed, non-expiring token naming one user.

    Deliberately without a timestamp: an unsubscribe link that has
    expired is worse than no unsubscribe link at all - the reader's
    remaining option is the spam button.
    """

    return signing.dumps(user.pk, salt=UNSUBSCRIBE_SALT)


def user_from_token(token):
    """The user a token names, or None if it is forged, damaged, or
    points at an account that no longer exists."""

    try:
        user_id = signing.loads(token, salt=UNSUBSCRIBE_SALT)

    except signing.BadSignature:
        return None

    return User.objects.filter(pk=user_id).first()


def site_url():
    return getattr(settings, "SITE_URL", "http://127.0.0.1:8000").rstrip("/")


def pending_for(user):
    """This user's notifications that have not been emailed yet.

    Being read in the bell is not a reason to leave it out: the two
    channels are independent, and someone who glanced at the bell on
    their phone still wants the morning email.
    """

    return (
        Notification.objects
        .filter(user=user, emailed_at__isnull=True)
        .select_related("job")
        .order_by("-score", "-created_at")
    )


def _recipients():
    """Job seekers who want email, have an address, and have something
    waiting."""

    return (
        User.objects
        .filter(
            profile__role="user",
            profile__email_job_alerts=True,
            notifications__emailed_at__isnull=True,
        )
        .exclude(email="")
        .distinct()
    )


def send_one_digest(user, now=None):
    """Email one user everything waiting for them. Returns True if it
    went out."""

    now = now or timezone.now()

    with transaction.atomic():
        pending = list(
            Notification.objects
            .select_for_update()
            .filter(user=user, emailed_at__isnull=True)
            .select_related("job")
            .order_by("-score", "-created_at")
        )

        if not pending:
            return False

        return _send_notifications_email(user, pending, now)


def send_one_notification(notification, now=None):
    """Email one newly matched job immediately when the user opted in."""

    now = now or timezone.now()

    with transaction.atomic():
        locked_notification = (
            Notification.objects
            .select_for_update()
            .select_related("user", "job")
            .filter(pk=notification.pk, emailed_at__isnull=True)
            .first()
        )
        if locked_notification is None:
            return False

        return _send_notifications_email(
            locked_notification.user,
            [locked_notification],
            now,
        )


def _send_notifications_email(user, pending, now):
    """Send the shared job-alert template for one or more notifications."""

    profile = Profile.objects.filter(user=user).first()
    if profile is None or not profile.email_job_alerts:
        return False

    recipient = getattr(profile, "email", "") or user.email
    if not recipient:
        return False

    base = site_url()

    context = {
        "user": user,
        "notifications": pending,
        "count": len(pending),
        "is_job_match": all(note.kind == "job_match" for note in pending),
        "site_url": base,
        "dashboard_url": f"{base}{reverse('dashboard')}",
        "unsubscribe_url": (
            f"{base}{reverse('alerts_unsubscribe', args=[unsubscribe_token(user)])}"
        ),
    }

    if context["is_job_match"]:
        subject = (
            "1 new job matches your profile"
            if len(pending) == 1
            else f"{len(pending)} new jobs match your profile"
        )
    elif len(pending) == 1:
        subject = f"WorkVista: {pending[0].title[:50]}"
    else:
        subject = "New WorkVista notifications"

    message = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string("email/job_alert.txt", context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )

    # Both parts, always. The plain-text alternative is not a courtesy -
    # it is most of what keeps a bulk message out of a spam folder.
    message.attach_alternative(
        render_to_string("email/job_alert.html", context),
        "text/html",
    )

    if message.send() != 1:
        raise RuntimeError(f"Email to {recipient} was not accepted for delivery.")

    Notification.objects.filter(
        id__in=[note.id for note in pending]
    ).update(emailed_at=now)

    return True


def _send_notifications_in_background(notification_ids):
    try:
        for notification_id in notification_ids:
            notification = (
                Notification.objects
                .select_related("user", "job")
                .filter(pk=notification_id)
                .first()
            )
            if notification is None:
                continue

            try:
                send_one_notification(notification)
            except Exception:
                logger.exception(
                    "job alerts: notification email %s to user %s failed",
                    notification.pk,
                    notification.user_id,
                )
    except Exception:
        logger.exception("job alerts: notification email worker failed")
    finally:
        connection.close()


def spawn_notification_emails(notification_ids):
    """Send newly created notifications without delaying their caller."""

    thread = threading.Thread(
        target=_send_notifications_in_background,
        args=(tuple(notification_ids),),
        name="workvista-notification-email",
        daemon=True,
    )
    thread.start()
    return thread


def send_pending_digests(now=None):
    """Email every job seeker with unsent matches. Returns how many
    emails went out."""

    now = now or timezone.now()

    sent = 0

    for user in _recipients():

        try:
            if send_one_digest(user, now=now):
                sent += 1

        except Exception:
            # One bad address, or one SMTP hiccup, must not cost
            # everybody else their digest. emailed_at stays null, so
            # this user is simply retried on the next run.
            logger.exception("job alerts: digest to %s failed", user.pk)

    return sent
