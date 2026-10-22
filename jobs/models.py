from django.db import models
from django.db.models import Q
from django.contrib.auth.models import User
from django.utils import timezone


# -------------------------------
# SCRAPER WEBSITES
# -------------------------------
class ScraperWebsite(models.Model):
    name = models.CharField(max_length=100)
    url = models.URLField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


# -------------------------------
# JOBS
# -------------------------------
class Job(models.Model):

    SALARY_CURRENCIES = (
        "PKR", "USD", "INR", "GBP", "EUR", "AED", "SAR", "CAD", "AUD",
    )

    SOURCE_CHOICES = (
        ('mustakbil', 'Mustakbil'),
        ('python_org', 'Python.org'),
        ('ppsc', 'PPSC'),
        ('njp', 'National Job Portal'),
        ('remoteok', 'Remote OK'),
        ('brightspyre', 'BrightSpyre'),
        ('workvista', 'WorkVista'),
    )

    # The job types offered anywhere a type can be chosen - the Post a
    # Job form, and the job-type dropdowns on search. Kept here so the
    # posting form and the search filters can't drift apart.
    JOB_TYPE_CHOICES = (
        ('Full-time', 'Full-time'),
        ('Part-time', 'Part-time'),
        ('Remote', 'Remote'),
        ('Contract', 'Contract'),
    )

    # 'technology' is the general software bucket and stays the
    # fallback for anything that doesn't match a narrower field - the
    # tech-specific entries below it (ai, mobile, web, data, devops) are
    # matched first. See jobs/recommender/categorize.py, where the
    # keyword order is what actually decides this.
    CATEGORY_CHOICES = (
        ('technology', 'Technology'),
        ('ai', 'AI & Machine Learning'),
        ('web', 'Web Development'),
        ('mobile', 'Mobile Development'),
        ('data', 'Data & Analytics'),
        ('devops', 'DevOps & Cloud'),
        ('design', 'Design & UI/UX'),
        ('video', 'Video & Motion'),
        ('writing', 'Writing & Assignments'),
        ('research', 'Research'),
        ('marketing', 'Marketing'),
        ('sales', 'Sales'),
        ('hr', 'HR'),
        ('customer_service', 'Customer Service'),
        ('finance', 'Finance & Accounting'),
        ('education', 'Education & Tutoring'),
        ('administration', 'Administration & Government'),
        ('healthcare', 'Healthcare'),
        ('logistics', 'Logistics'),
        ('other', 'Other'),
    )

    title = models.CharField(
        max_length=500
    )

    company = models.CharField(
        max_length=255,
        blank=True
    )

    location = models.CharField(
        max_length=255,
        blank=True
    )

    salary = models.CharField(
        max_length=255,
        blank=True
    )

    # Scraped salaries arrive as free text in wildly different shapes,
    # so `salary` above stays the single field everything displays and
    # salary_match_score() reads. These two are populated only for jobs
    # posted through WorkVista, where we actually collect a numeric
    # range, and `salary` is rendered from them at save time.
    salary_min = models.BigIntegerField(
        null=True,
        blank=True
    )

    salary_max = models.BigIntegerField(
        null=True,
        blank=True
    )

    experience = models.CharField(
        max_length=255,
        blank=True
    )

    job_type = models.CharField(
        max_length=100,
        blank=True
    )

    education = models.TextField(
        blank=True
    )

    skills = models.JSONField(
        default=list,
        blank=True
    )

    posted = models.CharField(
        max_length=100,
        blank=True
    )

    job_link = models.URLField(
        max_length=1000,
        blank=True
    )

    source = models.CharField(
        max_length=50,
        choices=SOURCE_CHOICES
    )

    # Set only for jobs posted through WorkVista itself (source =
    # 'workvista'). Null on every scraped job - there is no local user
    # behind those. Ownership is what gates editing and deleting a
    # posting, so it is always checked alongside the id.
    posted_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='posted_jobs'
    )

    # Existing and scraped listings remain public by default. Employer
    # submissions explicitly start unapproved in the posting view.
    is_approved = models.BooleanField(default=True)

    # Which of the employer's offices this opening is at. Null means the
    # head office, and stays null on every scraped job.
    #
    # `company` and `location` above remain the free text that job
    # cards, search and the recommender read - they are stamped from the
    # company and this branch when a posting is saved. SET_NULL because
    # closing a branch office must not delete the jobs posted from it.
    branch = models.ForeignKey(
        'CompanyBranch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='jobs'
    )

    # Auto-assigned from the title/skills at save time - see
    # jobs/recommender/categorize.py. Lets jobs be filtered and
    # trending be computed per category instead of one flat list.
    category = models.CharField(
        max_length=30,
        choices=CATEGORY_CHOICES,
        default='other',
        db_index=True,
    )

    description = models.TextField(
        blank=True
    )

    scraped_at = models.DateTimeField(
        auto_now=True
    )

    # Set once, the first time this job_link is ever saved. scraped_at
    # refreshes on every re-scrape (update_or_create touches it even for
    # jobs we've seen many times before), so it can't answer "how old is
    # this posting" - first_seen_at can, and is what trending/time-window
    # filtering is based on. See TRENDING.md.
    first_seen_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ['-scraped_at']

    def __str__(self):
        return f"{self.title} - {self.company}"

    @property
    def author_name(self):
        """Display name of the member who posted this job, or ''.

        signup() stores the member's full name in User.first_name, but
        that can be blank for accounts created another way (e.g.
        createsuperuser), so fall back to the username.
        """
        if not self.posted_by:
            return ""

        return self.posted_by.first_name or self.posted_by.username

    @property
    def salary_display(self):
        """Format WorkVista salary amounts while preserving scraped salary text."""
        if self.salary_min is None and self.salary_max is None:
            if self.salary in self.SALARY_CURRENCIES:
                return ""
            return self.salary

        currency = (self.salary or "").split(maxsplit=1)[0]
        if currency not in self.SALARY_CURRENCIES:
            if self.salary:
                return self.salary
            currency = "PKR"

        amounts = [
            f"{amount:,}"
            for amount in (self.salary_min, self.salary_max)
            if amount is not None
        ]
        return f"{currency} {' - '.join(amounts)} /month"


# -------------------------------
# SCRAPE RUNS
# -------------------------------
class ScrapeRun(models.Model):
    """One attempt at refreshing one source.

    The automatic scheduler's shared batch cooldown is recorded in
    ScraperSchedule. See jobs/refresh.py.
    """

    STATUS_CHOICES = (
        ('running', 'Running'),
        ('success', 'Succeeded'),
        ('failed', 'Failed'),
        ('blocked', 'Blocked by Cloudflare'),
    )

    source = models.CharField(
        max_length=50
    )

    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='running'
    )

    started_at = models.DateTimeField(
        auto_now_add=True
    )

    finished_at = models.DateTimeField(
        null=True,
        blank=True
    )

    jobs_saved = models.PositiveIntegerField(
        default=0
    )

    jobs_found = models.PositiveIntegerField(
        default=0
    )

    jobs_updated = models.PositiveIntegerField(
        default=0
    )

    jobs_failed = models.PositiveIntegerField(
        default=0
    )

    # Failure detail. Kept so a source that has been quietly erroring
    # for days can actually be seen to be erroring - the previous
    # generation of scrapers failed silently for months.
    message = models.TextField(
        blank=True
    )

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['source', '-started_at']),
        ]

    def __str__(self):
        return f"{self.source} {self.status} @ {self.started_at:%Y-%m-%d %H:%M}"

    @property
    def duration_seconds(self):
        if not self.finished_at:
            return None

        return int((self.finished_at - self.started_at).total_seconds())


# -------------------------------
# AUTOMATIC SCRAPER SCHEDULE
# -------------------------------
class ScraperSchedule(models.Model):
    """Shared cooldown timestamp for the automatic all-scraper batch."""

    key = models.CharField(
        max_length=50,
        unique=True,
        default='automatic',
    )

    last_completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    next_allowed_at = models.DateTimeField(
        null=True,
        blank=True,
    )


# -------------------------------
# SCRAPE LOCK
# -------------------------------
class ScrapeLock(models.Model):
    """A single row used as a mutex around the whole refresh.

    Two web workers can handle requests in the same instant and both
    decide a refresh is due. Acquiring is a single conditional UPDATE
    (see jobs/refresh.py::acquire_lock), which the database applies
    atomically, so exactly one of them wins.

    `locked_until` rather than a boolean so that a run whose process was
    killed can't wedge the refresh forever - the lock simply expires.
    """

    key = models.CharField(
        max_length=50,
        unique=True,
        default='refresh'
    )

    locked_until = models.DateTimeField(
        null=True,
        blank=True
    )

    def __str__(self):
        return f"{self.key} until {self.locked_until}"


# -------------------------------
# SAVED JOBS
# -------------------------------
class SavedJob(models.Model):

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    job = models.ForeignKey(
        Job,
        on_delete=models.CASCADE
    )

    saved_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        unique_together = ('user', 'job')

    def __str__(self):
        return f"{self.user.username} - {self.job.title}"


# -------------------------------
# USER ACTIVITY (for recommendations)
# -------------------------------
class UserActivity(models.Model):

    ACTIVITY_CHOICES = (
        ('view', 'Viewed job'),
        ('search', 'Searched'),
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='activities'
    )

    activity_type = models.CharField(
        max_length=10,
        choices=ACTIVITY_CHOICES
    )

    # The job's (or search result's inferred) category - what the
    # recommendation engine's affinity signal is actually built from.
    # See jobs/recommender/recommend.py.
    category = models.CharField(
        max_length=30,
        blank=True
    )

    job = models.ForeignKey(
        Job,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
        ]

    def __str__(self):
        return f"{self.user.username} {self.activity_type} ({self.category})"


# -------------------------------
# USER PROFILE
# -------------------------------
class Profile(models.Model):

    ROLE_CHOICES = (
        ('user', 'User'),
        ('employer', 'Employer'),
        ('admin', 'Admin'),
        ('superadmin', 'Super Admin'),
    )

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='user'
    )

    cv = models.FileField(
        upload_to='cvs/',
        null=True,
        blank=True
    )

    skills = models.JSONField(
        null=True,
        blank=True
    )

    job_title = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    location = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    salary = models.IntegerField(
        null=True,
        blank=True
    )

    salary_currency = models.CharField(
        max_length=3,
        default='PKR'
    )
    # A user can prefer more than one job type (e.g. both Full-time
    # and Remote) - stored as a list. job_type_match_score() in
    # jobs/recommender/matcher.py checks a job's single type against
    # all of these.
    job_type = models.JSONField(
        default=list,
        blank=True
    )

    # Alerts. On by default: a member who set preferences asked to be
    # matched. The profile toggle and the one-click link in every
    # digest both turn it off.
    email_job_alerts = models.BooleanField(
        default=True
    )

    # The watermark: when this member was last scanned for new matches.
    # A job is new *to them* if first_seen_at is later than this.
    #
    # A watermark rather than a fixed "last 24 hours" window because it
    # is self-healing - if alerts don't run for three days, the next
    # run picks up everything since, instead of silently dropping it.
    #
    # Null is read as "24 hours ago", never "the beginning of time":
    # otherwise the first run would scan all 216 existing jobs for
    # every existing account at once.
    alerts_checked_at = models.DateTimeField(
        null=True,
        blank=True
    )

    # Views and templates ask these rather than comparing role to a
    # string literal, so a renamed role is one edit here and not a
    # grep across the project.
    @property
    def is_employer(self):
        return self.role == "employer"

    @property
    def is_job_seeker(self):
        return self.role == "user"

    def __str__(self):
        return self.user.username


# -------------------------------
# CV EXTRACTED DATA
# -------------------------------
class CVData(models.Model):

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE
    )

    name = models.CharField(
        max_length=255,
        null=True,
        blank=True
    )

    email = models.EmailField(
        null=True,
        blank=True
    )

    phone = models.CharField(
        max_length=20,
        null=True,
        blank=True
    )

    skills = models.JSONField(
        null=True,
        blank=True
    )

    education = models.JSONField(
        null=True,
        blank=True
    )

    experience = models.JSONField(
        null=True,
        blank=True
    )

    certifications = models.JSONField(
        null=True,
        blank=True
    )

    honours = models.JSONField(
        null=True,
        blank=True,
        help_text="Honours, awards, and recognitions."
    )

    training = models.JSONField(
        null=True,
        blank=True,
        help_text="Training courses attended, distinct from formal education."
    )

    languages = models.JSONField(
        null=True,
        blank=True,
        help_text="Spoken/written languages, e.g. from a Europass CV's language table."
    )

    def __str__(self):
        return self.user.username

# -------------------------------
# EMPLOYER COMPANY
# -------------------------------
class Company(models.Model):
    """The company behind an employer account.

    OneToOne rather than ForeignKey: an employer account *is* a company.
    `name` and `location` are required because every job this employer
    posts is stamped with them - a company missing either could not post
    at all.
    """

    owner = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='company'
    )

    name = models.CharField(
        max_length=255
    )

    # The head office. Used as a posting's location whenever no branch
    # is chosen, which is every posting for a company with no branches.
    location = models.CharField(
        max_length=255
    )

    website = models.URLField(
        max_length=500,
        blank=True
    )

    description = models.TextField(
        blank=True
    )

    # A year, not a date - nobody knows the day their company was
    # founded, and a year is all that's ever displayed. The upper bound
    # is checked on the form rather than here, so rows already saved
    # can't become unsaveable simply because time passed.
    founded_year = models.PositiveSmallIntegerField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        verbose_name_plural = "companies"

    def __str__(self):
        return self.name


# -------------------------------
# COMPANY BRANCHES
# -------------------------------
class CompanyBranch(models.Model):
    """An additional office. Entirely optional.

    A company with no branches posts every job against its head office,
    so nothing downstream has to special-case their absence.
    """

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='branches'
    )

    name = models.CharField(
        max_length=255
    )

    location = models.CharField(
        max_length=255
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ['name']

        # So the branch dropdown on the post form can never offer two
        # entries the employer has no way to tell apart.
        unique_together = ('company', 'name')

    def __str__(self):
        return f"{self.company.name} - {self.name}"


# -------------------------------
# NOTIFICATIONS
# -------------------------------
class Notification(models.Model):
    """Something worth telling a member about.

    Only job matches produce these today, but `kind` exists from day
    one so a second sort (an employer's posting hitting N views, say)
    is a choices change rather than a migration.
    """

    KIND_CHOICES = (
        ('job_match', 'New job match'),
        ('employer_job_denied', 'Employer job not approved'),
        ('employer_job_approved', 'Employer job approved'),
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications'
    )

    kind = models.CharField(
        max_length=30,
        choices=KIND_CHOICES,
        default='job_match',
        db_index=True
    )

    # Null for kinds that aren't about a specific job. CASCADE because
    # a notification pointing at a deleted job is a dead link, not a
    # record worth keeping.
    job = models.ForeignKey(
        Job,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications'
    )

    # Stored, not rendered from the job at display time. This is a
    # record of what we told someone - if the job is re-scraped later
    # under a different title, the notification should still read the
    # way it read when it was sent.
    title = models.CharField(
        max_length=255
    )

    body = models.CharField(
        max_length=500,
        blank=True
    )

    # What it scored when it fired. Kept for tuning: it is the only way
    # to answer "what was scraping past 40 that shouldn't have been"
    # once there is real usage to look at.
    score = models.PositiveSmallIntegerField(
        default=0
    )

    # Timestamps rather than booleans - the same information plus when
    # it happened, for the same storage.
    read_at = models.DateTimeField(
        null=True,
        blank=True
    )

    emailed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    # default= rather than auto_now_add= so a batch of matches from one
    # scrape can be given a single shared timestamp. auto_now_add
    # silently ignores the value you pass and stamps each row
    # microseconds apart, which made "newest first" order a batch by
    # insertion order - showing the weakest match at the top.
    created_at = models.DateTimeField(
        default=timezone.now,
        db_index=True
    )

    class Meta:
        ordering = ['-created_at', '-score']

        # Nobody is ever told about the same job twice. A database
        # constraint rather than a check in the code, so two refreshes
        # racing each other can't slip a duplicate through. MySQL
        # permits many NULLs in a unique index, so future kinds with no
        # job are not blocked by this.
        unique_together = ('user', 'job', 'kind')

        indexes = [
            models.Index(fields=['user', 'read_at']),
        ]

    def __str__(self):
        return f"{self.user.username}: {self.title}"

class Application(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='applications'
    )

    job = models.ForeignKey(
        Job,
        on_delete=models.CASCADE,
        related_name='applications'
    )

    applied_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ['-applied_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'job'],
                name='unique_user_job_application'
            ),
        ]

    def __str__(self):
        return f"{self.user.username} applied for {self.job.title}"


def public_job_queryset():
    """Scraped listings plus employer listings explicitly approved."""

    return Job.objects.filter(Q(posted_by__isnull=True) | Q(is_approved=True))
