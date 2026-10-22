"""Migration helpers.

`_employer_backfill` lives here rather than inside the migration module
so it can be tested directly. A migration module's functions are awkward
to import (the filename starts with a digit) and the state a data
migration receives is awkward to fake, but the logic is worth a test in
its own right.
"""


def _employer_backfill(User, Profile, Job, Company):
    """Turn everyone who has already posted a job into an employer.

    Posting used to be open to any member. Now it belongs to companies,
    so every account with a WorkVista posting behind it needs the role
    and the company it should have had all along - otherwise it loses
    access to jobs it created.

    Idempotent: an account that already has a company is left alone, so
    re-running this is safe.
    """

    poster_ids = (
        Job.objects
        .filter(source="workvista", posted_by__isnull=False)
        .values_list("posted_by_id", flat=True)
        .distinct()
    )

    for user in User.objects.filter(id__in=list(poster_ids)):

        profile = Profile.objects.filter(user=user).first()

        # Admins and super admins are not demoted into employers - they
        # are staff accounts that happen to have posted something.
        if profile is None or profile.role in ("admin", "superadmin"):
            continue

        if Company.objects.filter(owner=user).exists():
            continue

        latest = (
            Job.objects
            .filter(source="workvista", posted_by=user)
            .order_by("-first_seen_at")
            .first()
        )

        Company.objects.create(
            owner=user,
            # A scraped-style blank company would fail the required
            # field, so fall back to whoever posted it.
            name=(latest.company or user.first_name or user.username),
            location=(latest.location or ""),
        )

        profile.role = "employer"

        profile.save()
