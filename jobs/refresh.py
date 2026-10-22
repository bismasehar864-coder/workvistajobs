"""Keeping the job listings fresh without anyone running a command.

WorkVista has no Celery, no Redis and no worker process, and it has to
keep working that way on a laptop running `manage.py runserver`. So the
refresh can be driven by ordinary web traffic: JobRefreshMiddleware asks
this module whether the shared 24-hour cooldown has elapsed, and if so
starts a background thread that runs all supported scrapers together.

The same entry point is a management command (`manage.py refresh_jobs`),
so once this is deployed somewhere with a scheduler, a cron line gets
exactly the same behaviour and the traffic trigger can be switched off
with JOB_REFRESH_ENABLED = False.

Three things this has to get right, all of them tested in
jobs/tests_refresh.py:

* Only one refresh at a time. Two workers can decide a refresh is due in
  the same instant, so the lock is a conditional UPDATE the database
  settles atomically - not a read-then-write.
* A killed process must not wedge it forever, so the lock expires.
* It must never break a page. Everything the middleware touches is
  wrapped; a broken refresh is invisible to the visitor and loud in the
  ScrapeRun table.
"""

import logging
import threading
import time
from contextvars import ContextVar
from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.db.models import Q
from django.utils import timezone

from .models import Job, ScrapeRun, ScrapeLock, ScraperSchedule


logger = logging.getLogger(__name__)
_active_scrape_run = ContextVar("active_scrape_run", default=None)


def get_active_scrape_run(source):
    """Return the refresh-owned run currently executing this source, if any."""

    run = _active_scrape_run.get()
    return run if run is not None and run.source == source else None


# ============================================================
# WHAT CAN BE REFRESHED
# ============================================================

# The single source of truth for "source key -> management command",
# shared with the admin dashboard's Run buttons (jobs/views.py).
SCRAPER_COMMANDS = {
    "mustakbil": "scrape_mustakbil",
    "python_org": "scrape_python",
    "njp": "scrape_njp",
    "ppsc": "scrape_ppsc",
    "remoteok": "scrape_remoteok",
    "brightspyre": "scrape_brightspyre",
}

# Plain HTTP scrapers. These are the sources started automatically.
AUTO_SOURCES = (
    "njp", "ppsc", "mustakbil", "python_org", "remoteok", "brightspyre",
)


DEFAULT_INTERVAL = timedelta(
    hours=getattr(settings, "JOB_REFRESH_INTERVAL_HOURS", 24)
)

# Long enough for the slowest scraper (Mustakbil, one request per
# posting) with room to spare, short enough that a killed
# process doesn't block the next refresh for long.
LOCK_TTL = timedelta(minutes=45)

# How often the middleware is allowed to ask the database whether
# anything is due. The answer can't change faster than the interval, so
# there is nothing to gain from checking on every request.
TRIGGER_THROTTLE_SECONDS = 300


# ============================================================
# FRESHNESS
# ============================================================

def sources_due(sources=None, interval=None, now=None):
    """Which of `sources` have not had a completed attempt within `interval`.

    Failed and blocked attempts also start the cooldown. Retrying them
    automatically sooner would violate the minimum interval; an admin
    can still retry immediately with a manual force-run.
    """

    sources = list(sources if sources is not None else AUTO_SOURCES)
    interval = interval or DEFAULT_INTERVAL
    now = now or timezone.now()

    cutoff = now - interval

    latest_finished = {}
    completed_runs = (
        ScrapeRun.objects
        .filter(
            source__in=sources,
            status__in=("success", "failed", "blocked"),
            finished_at__isnull=False,
        )
        .order_by("source", "-finished_at")
        .values_list("source", "finished_at")
    )
    for source, finished_at in completed_runs:
        latest_finished.setdefault(source, finished_at)

    return [
        source for source in sources
        if latest_finished.get(source) is None or latest_finished[source] <= cutoff
    ]


def automatic_batch_due(interval=None, now=None):
    """Whether the complete automatic scraper batch has reached its cooldown."""

    interval = interval or DEFAULT_INTERVAL
    now = now or timezone.now()
    schedule = ScraperSchedule.objects.filter(key="automatic").first()

    if schedule is None:
        return True

    next_allowed_at = schedule.next_allowed_at

    if schedule.last_completed_at is not None:
        after_completion = schedule.last_completed_at + interval
        if next_allowed_at is None or after_completion > next_allowed_at:
            next_allowed_at = after_completion

    return next_allowed_at is None or next_allowed_at <= now


def last_run_by_source():
    """The most recent run per source, for the admin dashboard."""

    latest = {}

    for run in ScrapeRun.objects.order_by("source", "-started_at"):

        latest.setdefault(run.source, run)

    return latest


# ============================================================
# LOCKING
# ============================================================

def acquire_lock(ttl=None, now=None):
    """Take the refresh lock, or return False if someone else holds it.

    The UPDATE carries its own condition, so the check and the claim are
    one statement the database settles for us. Doing this as a read then
    a write would let two workers both read "free" before either wrote.
    """

    ttl = ttl or LOCK_TTL
    now = now or timezone.now()

    ScrapeLock.objects.get_or_create(key="refresh")

    claimed = (
        ScrapeLock.objects
        .filter(key="refresh")
        .filter(Q(locked_until__isnull=True) | Q(locked_until__lt=now))
        .update(locked_until=now + ttl)
    )

    return bool(claimed)


def release_lock():
    ScrapeLock.objects.filter(key="refresh").update(locked_until=None)


# ============================================================
# RUNNING
# ============================================================

def _default_runner(command):
    call_command(command)


def run_refresh(
    sources=None,
    interval=None,
    force=False,
    runner=None,
    automatic_batch=False,
):
    """Scrape due sources, or all sources as one automatic batch.

    Safe to call from anywhere: it takes the lock itself and gives up
    quietly if another refresh is already under way. Automatic batches
    share one persisted 24-hour cooldown; explicit/manual source runs do not.
    """

    sources = list(sources if sources is not None else AUTO_SOURCES)
    runner = runner or _default_runner

    # An unknown key would otherwise blow up on the command lookup; the
    # sources come from settings and command-line flags, not code.
    known = [source for source in sources if source in SCRAPER_COMMANDS]

    for unknown in set(sources) - set(known):
        logger.warning("refresh_jobs: unknown source %r ignored", unknown)

    if automatic_batch:
        known = [source for source in AUTO_SOURCES if source in SCRAPER_COMMANDS]
        wanted = known if force or automatic_batch_due(interval=interval) else []
    else:
        wanted = known if force else sources_due(known, interval=interval)

    if not wanted:
        reason = "nothing due"
        if automatic_batch:
            reason = "nothing due; automatic batch cooldown has not elapsed"
        return {"started": False, "reason": reason, "results": {}}

    if not acquire_lock():
        logger.info("refresh_jobs: another refresh holds the lock, skipping")
        return {"started": False, "reason": "already running", "results": {}}

    if automatic_batch and not force and not automatic_batch_due(interval=interval):
        release_lock()
        return {
            "started": False,
            "reason": "nothing due; automatic batch cooldown has not elapsed",
            "results": {},
        }

    if automatic_batch:
        batch_started_at = timezone.now()
        cooldown = interval or DEFAULT_INTERVAL
        ScraperSchedule.objects.update_or_create(
            key="automatic",
            defaults={"next_allowed_at": batch_started_at + cooldown},
        )

    results = {}

    try:
        for source in wanted:
            results[source] = _run_one(source, runner)

        # Match the jobs that just landed against everyone's
        # preferences, so the bell is current the moment a refresh
        # finishes. Deliberately here and on this thread: it is already
        # off the request path, and it is a database-only pass measured
        # in milliseconds.
        #
        # Its own try/except: failing to notify must not mark a
        # successful scrape as failed.
        try:
            from jobs.alerts.notifications import generate_notifications

            generate_notifications()

        except Exception:
            logger.exception("refresh_jobs: generating alerts failed")

    finally:
        if automatic_batch:
            completed_at = timezone.now()
            ScraperSchedule.objects.update_or_create(
                key="automatic",
                defaults={
                    "last_completed_at": completed_at,
                    "next_allowed_at": completed_at + (interval or DEFAULT_INTERVAL),
                },
            )

        # Released even if a scraper raises something we didn't expect,
        # or the process is interrupted mid-run - otherwise the next
        # refresh waits for the whole lock TTL for no reason.
        release_lock()

    return {"started": True, "reason": "", "results": results}


def _run_one(source, runner):
    """Run one scraper, recording the attempt either way."""

    run = ScrapeRun.objects.create(source=source, status="running")

    try:
        before = Job.objects.filter(source=source).count()
        token = _active_scrape_run.set(run)
        try:
            runner(SCRAPER_COMMANDS[source])
        finally:
            _active_scrape_run.reset(token)

    except Exception as error:
        # Deliberately broad. A scraper reaches the open internet and
        # can fail in ways we can't enumerate; one bad source must not
        # take the rest of the refresh down with it.
        logger.exception("refresh_jobs: %s failed", source)

        run.status = "failed"
        run.message = f"{type(error).__name__}: {error}"[:2000]
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "message", "finished_at"])

        return {"status": "failed", "error": str(error)}

    if run.status == "running":
        after = Job.objects.filter(source=source).count()

        run.status = "success"
        run.jobs_saved = max(0, after - before)
        run.jobs_found = run.jobs_saved
        run.finished_at = timezone.now()
        run.save(update_fields=[
            "status", "jobs_found", "jobs_saved", "finished_at",
        ])

    return {
        "status": run.status,
        "new_jobs": run.jobs_saved,
        "jobs_found": run.jobs_found,
        "error": run.message,
    }


# ============================================================
# THE TRAFFIC TRIGGER
# ============================================================

_last_checked_at = 0.0
_check_guard = threading.Lock()


def reset_trigger_throttle():
    """Forget when we last checked. For tests."""

    global _last_checked_at

    _last_checked_at = 0.0


def _throttle_expired():
    """True at most once per TRIGGER_THROTTLE_SECONDS, per process."""

    global _last_checked_at

    now = time.monotonic()

    with _check_guard:

        if now - _last_checked_at < TRIGGER_THROTTLE_SECONDS:
            return False

        _last_checked_at = now

        return True


def _refresh_in_background():
    try:
        run_refresh(automatic_batch=True)

    except Exception:
        logger.exception("refresh_jobs: background refresh failed")

    finally:
        # The thread owns this connection; leaving it open would leak one
        # per refresh for the life of the process.
        connection.close()


def spawn_refresh():
    """Start a refresh on a daemon thread."""

    thread = threading.Thread(
        target=_refresh_in_background,
        name="workvista-job-refresh",
        daemon=True,
    )

    thread.start()

    return thread


def maybe_start_refresh():
    """Start a refresh if one is due. Returns whether it started one."""

    if not getattr(settings, "JOB_REFRESH_ENABLED", True):
        return False

    if not _throttle_expired():
        return False

    if not automatic_batch_due():
        return False

    spawn_refresh()

    return True


# ============================================================
# THE DIGEST FALLBACK
# ============================================================
#
# send_job_alerts is meant to be driven by cron. Until someone sets
# that up, this makes the feature work anyway: the first page view
# after 24 hours without a digest spawns one on a background thread.
#
# Same shape as the refresh trigger above - a process-local throttle
# so the database is barely touched, and a daemon thread so nobody's
# page load waits on an SMTP server.

_last_digest_at = 0.0
_digest_guard = threading.Lock()


def reset_digest_throttle():
    """Forget when the last digest went out. For tests."""

    global _last_digest_at

    _last_digest_at = 0.0


def _digest_throttle_expired():

    global _last_digest_at

    interval = getattr(settings, "JOB_ALERTS_DIGEST_INTERVAL_HOURS", 24) * 3600

    now = time.monotonic()

    with _digest_guard:

        if _last_digest_at and now - _last_digest_at < interval:
            return False

        _last_digest_at = now

        return True


def _digest_in_background():
    from jobs.alerts.digest import send_pending_digests

    try:
        send_pending_digests()

    except Exception:
        logger.exception("job alerts: background digest failed")

    finally:
        # The thread owns this connection; leaving it open would leak
        # one per digest for the life of the process.
        connection.close()


def spawn_digest():
    """Start a digest send on a daemon thread."""

    thread = threading.Thread(
        target=_digest_in_background,
        name="workvista-job-digest",
        daemon=True,
    )

    thread.start()

    return thread


def maybe_send_digests():
    """Send the daily digest if one is due. Returns whether it started."""

    if not getattr(settings, "JOB_ALERTS_ENABLED", True):
        return False

    if not _digest_throttle_expired():
        return False

    spawn_digest()

    return True


class JobRefreshMiddleware:
    """Lets ordinary page views keep the listings up to date.

    Cheap by design: the throttle means the database is asked "is
    anything due?" at most once every few minutes per process, and the
    scraping itself happens on a background thread, so the visitor's
    response is never held up by it.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        try:
            maybe_start_refresh()

        except Exception:
            # A stale listing is a far smaller problem than a 500 on
            # every page, so this can never be allowed to propagate.
            logger.exception("refresh_jobs: trigger failed")

        try:
            maybe_send_digests()

        except Exception:
            logger.exception("job alerts: digest trigger failed")

        return self.get_response(request)
