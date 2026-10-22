from functools import wraps
import logging
import re

from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Q,Count
from django.db import transaction
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from .models import (
    Application,
    Profile,
    ScraperWebsite,
    CVData,
    Job,
    SavedJob,
    Company,
    CompanyBranch,
    Notification,
    public_job_queryset,
)

from .forms import (
    SignUpForm,
    SigninForm,
    StaffProfileForm,
    EmployerSignUpForm,
    BranchFormSet,
    PROFILE_SALARY_CURRENCY_CHOICES,
)

from .utils import (
    extract_cv_text,
    is_valid_cv,
    save_cv_data,
)

from .resume_parser import parse_resume
from .refresh import SCRAPER_COMMANDS, last_run_by_source, run_refresh
from .roles import job_seeker_required


logger = logging.getLogger(__name__)

def _role_home_url(user):
    """Logged-in user ka apna dashboard URL (role ke hisaab se)."""
    profile = Profile.objects.filter(user=user).first()
    role = profile.role if profile else "user"

    if role == "superadmin":
        return f"{reverse('superadmin_dashboard')}?section=profile"
    if role == "admin":
        return f"{reverse('admin_dashboard')}?section=profile"
    if role == "employer":
        return reverse("employer_dashboard")
    return reverse("user_dashboard")



# The tab sections on the user dashboard. Used to validate an incoming
# ?section= so an arbitrary string can't be echoed into the template's
# class attribute.
DASHBOARD_SECTIONS = frozenset({
    "profile",
    "recommended",
    "trending",
    "search",
    "saved",
})

# What the bare /dashboard/user/ opens, and where a form on the profile
# tab returns to. Never blank: an unset section used to fall through to
# whatever tab the browser happened to remember, which is how saving
# your preferences could land you on Search Jobs.
DEFAULT_DASHBOARD_SECTION = "profile"

# The admin shells are separate pages with their own tabs. Same rule as
# the user dashboard: the address says which tab is open, so a reload -
# or the redirect after running a scraper - lands back on it. Profile is
# the first entry so it is also the default.
ADMIN_SECTIONS = ("profile", "users", "scraper", "employers")
SUPERADMIN_SECTIONS = ("profile", "admins", "users", "scraper", "employers")


def resolve_section(request, allowed):
    """The requested ?section=, or the first tab if it isn't one of ours."""

    requested = request.GET.get("section", "").strip()

    return requested if requested in allowed else allowed[0]


# Every field on the search form. The form submits all of them on every
# submission, so a key being PRESENT - even with an empty value - is what
# tells us the visitor actually searched. Testing the values instead
# meant "All sources / All categories / All job types / Any time" looked
# identical to a page nobody had touched, and pressing Search with
# everything cleared fell through to the empty state instead of showing
# every job. See search_was_submitted().
SEARCH_PARAM_KEYS = ("q", "location", "type", "posted", "category", "source")


def search_was_submitted(request):
    return any(key in request.GET for key in SEARCH_PARAM_KEYS)


def apply_search_filters(jobs, query="", location="", job_type="",
                         posted_window="", category="", source=""):
    """Narrow `jobs` by whichever search filters were actually set.

    Every filter is optional and each one is skipped when blank, so a
    search with nothing filled in returns the queryset untouched - i.e.
    every job. Shared by the standalone Search Jobs page and the search
    section of the user dashboard, which are otherwise two parallel
    implementations that have already drifted apart once.
    """

    if posted_window:
        jobs = apply_time_window(jobs, posted_window)

    if category:
        jobs = jobs.filter(category=category)

    if source:
        jobs = jobs.filter(source=source)

    if query:
        # Matched against everything a posting carries as text. skills
        # is a JSON list, and icontains on it is a substring test over
        # the stored JSON - good enough to find "postgresql" in
        # ["Django", "PostgreSQL"], which is what a skill search means
        # to someone typing in the box.
        jobs = jobs.filter(
            Q(title__icontains=query)
            | Q(company__icontains=query)
            | Q(description__icontains=query)
            | Q(skills__icontains=query)
        )

    if location:
        jobs = jobs.filter(location__icontains=location)

    if job_type:
        jobs = jobs.filter(job_type__icontains=job_type)

    return jobs.distinct()

# =========================================================
# RECOMMENDER
# =========================================================

from .recommender.ranking import rank_jobs
from .recommender.trending import compute_trending_jobs, top_job_per_category
from .recommender.filters import apply_time_window
from .recommender.matcher import title_match_score
from .recommender.categorize import available_categories, categorize_job, infer_user_category
from .recommender.recommend import get_recommended_jobs, log_activity


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def get_saved_job_ids(request):
    """IDs of jobs the current user has saved, for the bookmark button
    on job cards/detail pages to render its filled vs outline state."""

    if not request.user.is_authenticated:
        return set()

    return set(
        SavedJob.objects.filter(
            user=request.user,
            job__in=public_job_queryset(),
        ).values_list('job_id', flat=True)
    )


def get_applied_job_ids(request):
    """Job IDs already applied to by the current user."""

    if not request.user.is_authenticated:
        return set()

    return set(
        Application.objects.filter(user=request.user).values_list('job_id', flat=True)
    )


def get_user_skills(profile, cv_data=None):
    """
    Collect skills from both:
    1. Profile.skills
    2. CVData.skills

    Returns a normalized set of skills.
    """

    skills = set()

    # -----------------------------------------------------
    # PROFILE SKILLS
    # -----------------------------------------------------

    if profile and profile.skills:

        if isinstance(profile.skills, list):

            for skill in profile.skills:

                if skill:

                    skills.add(
                        str(skill).lower().strip()
                    )

        elif isinstance(profile.skills, str):

            for skill in profile.skills.split(","):

                if skill.strip():

                    skills.add(
                        skill.lower().strip()
                    )


    # -----------------------------------------------------
    # CV SKILLS
    # -----------------------------------------------------

    if cv_data and cv_data.skills:

        if isinstance(cv_data.skills, list):

            for skill in cv_data.skills:

                if skill:

                    skills.add(
                        str(skill).lower().strip()
                    )

        elif isinstance(cv_data.skills, str):

            for skill in cv_data.skills.split(","):

                if skill.strip():

                    skills.add(
                        skill.lower().strip()
                    )


    return skills


def clean_json_list(value):
    """
    Convert form text into a list suitable for JSONField.

    Accepts:
    Python list
    Comma-separated text
    Newline-separated text
    """

    if isinstance(value, list):

        return [
            str(item).strip()
            for item in value
            if str(item).strip()
        ]


    if not value:

        return []


    value = str(value).strip()


    # -----------------------------------------------------
    # SUPPORT COMMA + NEWLINE SEPARATED VALUES
    # -----------------------------------------------------

    value = value.replace("\r\n", "\n")

    parts = []

    for line in value.split("\n"):

        for item in line.split(","):

            item = item.strip()

            if item:

                parts.append(item)


    return parts


def clean_salary(value):
    """
    Safely convert salary input to IntegerField value.
    """

    if not value:

        return None


    try:

        return int(value)

    except (ValueError, TypeError):

        return None


# =========================================================
# HOME
# =========================================================

def home(request):

    if request.user.is_authenticated:
        return redirect(_role_home_url(request.user))

    return render(
        request,
        "home.html",
        {
            "category_highlights": top_job_per_category(limit_categories=9),
            "saved_job_ids": get_saved_job_ids(request),
        }
    )


# =========================================================
# JOB DETAIL
# =========================================================

def job_detail(request, job_id):

    job = get_object_or_404(public_job_queryset(), id=job_id)

    log_activity(request.user, "view", category=job.category, job=job)

    # "More in <category>" only shows to a logged-out visitor -
    # a signed-in user gets "Recommended for you" instead (see
    # job_detail.html). No point running the query otherwise.
    similar_jobs = []

    if not request.user.is_authenticated:

        # Same duplicate-posting caveat as get_recommended_jobs() -
        # dedupe by (title, company) so a re-scraped listing doesn't
        # show twice.
        candidates = public_job_queryset().filter(
            category=job.category
        ).exclude(
            id=job.id
        ).order_by(
            "-first_seen_at"
        )[:20]

        seen_keys = {(job.title.strip().lower(), job.company.strip().lower())}

        for candidate in candidates:
            key = (candidate.title.strip().lower(), candidate.company.strip().lower())
            if key in seen_keys:
                continue
            seen_keys.add(key)
            similar_jobs.append(candidate)
            if len(similar_jobs) >= 4:
                break

    recommended_jobs = get_recommended_jobs(
        request.user,
        limit=4,
        exclude_job_id=job.id,
    )

    # A signed-in user already has the dashboard's sidebar for
    # navigation (My Profile / Recommended / Trending / Search /
    # Saved / Logout) - showing the public top nav (Home / Trending
    # Jobs / Dashboard / Logout) on top of that is redundant. So a
    # signed-in user gets this page inside the dashboard shell
    # instead of the public one; job_detail.html renders the same
    # body content into whichever shell this points at.
    layout_template = (
        "dashboard/base_dashboard.html"
        if request.user.is_authenticated
        else "base.html"
    )

    return render(
        request,
        "job_detail.html",
        {
            "job": job,
            "similar_jobs": similar_jobs,
            "recommended_jobs": recommended_jobs,
            "saved_job_ids": get_saved_job_ids(request),
            "applied_job_ids": get_applied_job_ids(request),
            "layout_template": layout_template,
        }
    )


@job_seeker_required
@require_POST
def apply_job(request, job_id):
    job = get_object_or_404(public_job_queryset(), id=job_id)
    _, created = Application.objects.get_or_create(user=request.user, job=job)

    if created:
        messages.success(request, "You have successfully applied for this job.")
    else:
        messages.info(request, "You have already applied for this job.")

    next_url = request.POST.get("next", "")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)

    return redirect("job_detail", job_id=job.id)


# =========================================================
# SIGN IN
# =========================================================

def signin(request):

    if request.user.is_authenticated:
        return redirect(_role_home_url(request.user))
    
    form = SigninForm(request.POST or None)

    if request.method == "POST":

        if form.is_valid():

            user = form.user

            login(
                request,
                user
            )

            # -------------------------------------------------
            # GET EXISTING PROFILE OR CREATE ONE
            # -------------------------------------------------

            profile, created = Profile.objects.get_or_create(
                user=user,
                defaults={
                    "role": "user"
                }
            )


            # -------------------------------------------------
            # SUPER ADMIN
            # -------------------------------------------------

            if profile.role == "superadmin":

                return redirect(
                    f"{reverse('superadmin_dashboard')}?section=profile"
                )


            # -------------------------------------------------
            # ADMIN
            # -------------------------------------------------

            elif profile.role == "admin":

                return redirect(
                    f"{reverse('admin_dashboard')}?section=profile"
                )


            # -------------------------------------------------
            # NORMAL USER
            # -------------------------------------------------
            #
            # Honour ?next= so that clicking "Post a Job" while signed
            # out lands on the Post a Job page after signing in, not on
            # the dashboard the visitor never asked for. Only for normal
            # users: admins and super admins are routed to their own
            # dashboards above, which is where they belong regardless of
            # what link sent them here. url_has_allowed_host_and_scheme
            # keeps ?next= from becoming an open redirect off-site.

            # -------------------------------------------------
            # EMPLOYER
            # -------------------------------------------------
            #
            # Falls through to the ?next= handling below rather than
            # redirecting straight away, so an employer who clicked
            # "Post a Job" while signed out is returned to the post
            # form. Admins above are not given that, because their own
            # dashboard is where they belong regardless of what link
            # sent them here.

            home = (
                "employer_dashboard"
                if profile.role == "employer"
                else "user_dashboard"
            )


            next_url = request.GET.get(
                "next"
            ) or request.POST.get(
                "next"
            )

            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):

                return redirect(
                    next_url
                )


            return redirect(
                home
            )


    return render(
        request,
        "signin.html",
        {
            "form": form
        }
    )


def _unique_username(email):
    """A username derived from the email, suffixed until it's free.

    Shared by both signup paths so an employee and an employer signing
    up with the same mailbox prefix can't collide.
    """

    base = email.split("@")[0]

    username = base
    counter = 1

    while User.objects.filter(username=username).exists():

        username = f"{base}{counter}"

        counter += 1

    return username


# =========================================================
# SIGN UP - CHOOSING A ROLE
# =========================================================

def signup_choose(request):

    if request.user.is_authenticated:
        return redirect(_role_home_url(request.user))
    """Which kind of account to create.

    Two links, nothing created. Keeps the name `signup` so every
    existing {% url 'signup' %} in the templates still resolves.
    """

    return render(
        request,
        "signup_choose.html"
    )


# =========================================================
# SIGN UP - JOB SEEKER
# =========================================================

def signup_employee(request):

    if request.user.is_authenticated:
        return redirect(_role_home_url(request.user))

    form = SignUpForm(request.POST or None)

    if request.method == "POST":

        if form.is_valid():

            fullname = form.cleaned_data["fullname"]
            email = form.cleaned_data["email"]
            password = form.cleaned_data["password"]

            user = User.objects.create_user(
                username=_unique_username(email),
                email=email,
                password=password,
            )

            user.first_name = fullname

            user.save()

            # The post_save signal has already made the profile with
            # role "user", which is what a job seeker is.

            login(
                request,
                user
            )

            return redirect(
                "cv_upload"
            )

    return render(
        request,
        "signup.html",
        {
            "form": form
        }
    )


# =========================================================
# SIGN UP - EMPLOYER
# =========================================================

def signup_employer(request):
    
    if request.user.is_authenticated:
        return redirect(_role_home_url(request.user))
    """Create the account and the company it posts under, together.

    Atomic because a half-created employer - a User with no Company - is
    an account that cannot post and cannot be repaired from the UI.
    """

    form = EmployerSignUpForm(request.POST or None)

    branches = BranchFormSet(
        request.POST or None,
        prefix="branches"
    )

    if request.method == "POST":

        if form.is_valid() and branches.is_valid():

            email = form.cleaned_data["email"]

            with transaction.atomic():

                user = User.objects.create_user(
                    username=_unique_username(email),
                    email=email,
                    password=form.cleaned_data["password"],
                )

                user.first_name = form.cleaned_data["fullname"]

                user.save()

                # The post_save signal already made the profile.
                profile = user.profile

                profile.role = "employer"

                profile.save()

                company = Company.objects.create(
                    owner=user,
                    name=form.cleaned_data["company_name"],
                    location=form.cleaned_data["company_location"],
                    website=form.cleaned_data.get("website") or "",
                    description=form.cleaned_data.get("description") or "",
                    founded_year=form.cleaned_data.get("founded_year"),
                )

                # Untouched rows carry nothing and are simply skipped -
                # branches are optional, so an employer who has none
                # should not have to delete an empty row to get past.
                CompanyBranch.objects.bulk_create([
                    CompanyBranch(
                        company=company,
                        name=branch_form.cleaned_data["name"],
                        location=branch_form.cleaned_data["location"],
                    )
                    for branch_form in branches
                    if not branch_form.is_blank
                ])

            login(
                request,
                user
            )

            return redirect(
                "employer_company"
            )

    return render(
        request,
        "signup_employer.html",
        {
            "form": form,
            "branches": branches,
        }
    )


# =========================================================
# DASHBOARD REDIRECT
# =========================================================

@login_required
def dashboard(request):

    profile, created = Profile.objects.get_or_create(
        user=request.user,
        defaults={
            "role": "user"
        }
    )


    # -------------------------------------------------
    # SUPER ADMIN
    # -------------------------------------------------

    if profile.role == "superadmin":

        return redirect(
            "superadmin_dashboard"
        )


    # -------------------------------------------------
    # ADMIN
    # -------------------------------------------------

    elif profile.role == "admin":

        return redirect(
            "admin_dashboard"
        )


    # -------------------------------------------------
    # EMPLOYER
    # -------------------------------------------------

    elif profile.role == "employer":

        return redirect(
            "employer_dashboard"
        )


    # -------------------------------------------------
    # NORMAL USER
    # -------------------------------------------------

    return redirect(
        "user_dashboard"
    )


# =========================================================
# USER DASHBOARD
# =========================================================

@login_required
def user_dashboard(request, section=None):

    profile, created = Profile.objects.get_or_create(
        user=request.user,
        defaults={
            "role": "user"
        }
    )


    # =========================================================
    # PREVENT EMPLOYERS / ADMINS / SUPER ADMINS
    # =========================================================

    if profile.role == "admin":

        return redirect(
            "admin_dashboard"
        )


    elif profile.role == "superadmin":

        return redirect(
            "superadmin_dashboard"
        )


    elif profile.role == "employer":

        return redirect(
            "employer_dashboard"
        )


    # =========================================================
    # CV DATA
    # =========================================================

    cv_data, created = CVData.objects.get_or_create(
        user=request.user
    )


    # =========================================================
    # TRENDING JOBS
    # =========================================================

    # IMPORTANT:
    # Trending jobs come from Job, NOT ScraperWebsite, ranked by
    # compute_trending_jobs() (see TRENDING.md) - the same ranking
    # used on the standalone Trending Jobs page, so the two stay
    # consistent with each other.
    #
    # Trending is NOT personalized.
    # It remains separate from Search Jobs.
    #
    # Defaults to "past 24 hours" on first load, same reasoning as the
    # standalone Trending Jobs page - see trending_jobs() below.

    if "trend_window" in request.GET:
        trend_window = request.GET.get("trend_window", "")
    else:
        trend_window = "24h"

    # Same default-from-CV reasoning as the standalone Trending Jobs
    # page (trending_jobs() below) - this is the logged-in user's own
    # dashboard, so profile/cv_data are already loaded, no extra query
    # needed.
    if "trend_category" in request.GET:
        trend_category = request.GET.get("trend_category", "")
    else:
        trend_category = infer_user_category(profile, cv_data) or ""

    trending_qs = public_job_queryset()

    if trend_window:
        trending_qs = apply_time_window(trending_qs, trend_window)

    trend_categories = available_categories(trending_qs)

    if trend_category:
        trending_qs = trending_qs.filter(category=trend_category)

    trending_jobs = compute_trending_jobs(trending_qs, limit=20)


    # =========================================================
    # REGISTERED USER SEARCH
    # =========================================================

    jobs = Job.objects.none()


    query = request.GET.get(
        "q",
        ""
    ).strip()


    location = request.GET.get(
        "location",
        ""
    ).strip()


    job_type = request.GET.get(
        "type",
        ""
    ).strip()


    posted_window = request.GET.get(
        "posted",
        ""
    ).strip()


    source = request.GET.get(
        "source",
        ""
    ).strip()


    # Same "did they actually search" test as the standalone Search Jobs
    # view - see SEARCH_PARAM_KEYS and the comment there.
    submitted = search_was_submitted(request)

    engaged = submitted

    if "category" in request.GET:
        category = request.GET.get("category", "").strip()
    elif engaged:
        category = infer_user_category(profile, cv_data) or ""
    else:
        category = ""


    categories = available_categories()


    # =========================================================
    # WHICH SECTION OPENS
    # =========================================================
    #
    # The dashboard's tabs used to be chosen purely client-side from
    # localStorage. That broke search: the search form is a GET form,
    # and submitting one drops the URL fragment, so "#search" was gone
    # by the time the results came back and dashboard.js fell back to
    # whatever tab was last remembered - usually Trending - leaving the
    # results in a hidden div. The server now names the section the URL
    # implies, and dashboard.js honours it over localStorage.
    #
    # Both dashboard forms post an explicit `section`, so a search that
    # happens to carry trending's hidden fields (or the reverse) still
    # lands on the form the user actually used. The inferred values
    # below are the fallback for hand-typed or bookmarked URLs.

    if section in DASHBOARD_SECTIONS:

        # Came in on /dashboard/user/<section>/ - the address is the
        # answer, and it survives a reload.
        active_section = section

    elif "section" in request.GET:

        active_section = request.GET.get("section", "").strip()

        if active_section not in DASHBOARD_SECTIONS:
            active_section = DEFAULT_DASHBOARD_SECTION

    elif engaged:

        active_section = "search"

    elif "trend_window" in request.GET or "trend_category" in request.GET:

        active_section = "trending"

    else:

        active_section = DEFAULT_DASHBOARD_SECTION


    # =========================================================
    # SEARCH JOB DATABASE
    # =========================================================

    if submitted:

        log_activity(
            request.user,
            "search",
            category=category or (categorize_job(query) if query else ""),
        )

        jobs = apply_search_filters(
            public_job_queryset(),
            query=query,
            location=location,
            job_type=job_type,
            posted_window=posted_window,
            category=category,
            source=source,
        )


        # =====================================================
        # PERSONALIZED RANKING
        # =====================================================

        user_skills = get_user_skills(
            profile,
            cv_data
        )


        ranked_jobs = rank_jobs(

            jobs=jobs,

            user_skills=user_skills,

            search_query=query,

            # Saved preference is used for personalization.
            # If the user has no saved location preference,
            # the searched location is used.

            user_location=(
                profile.location
                or location
            ),

            user_job_type=(
                profile.job_type
                or job_type
            ),

            user_salary=profile.salary,

        )


        # -----------------------------------------------------
        # ONLY SEND JOB OBJECTS TO TEMPLATE
        # -----------------------------------------------------
        #
        # The internal score is deliberately removed here.
        #
        # Template receives:
        #
        # Job
        # Job
        # Job
        #
        # NOT:
        #
        # Job + score
        #
        # Therefore no percentage/match score is displayed.

        jobs = [
            item["job"]
            for item in ranked_jobs
        ]


    # =========================================================
    # POST REQUESTS
    # =========================================================

    if request.method == "POST":


        # =====================================================
        # CV UPLOAD
        # =====================================================
        #
        # "update_cv" is a hidden marker field on the CV form (both
        # the "no CV yet" and "replace CV" variants) so this branch
        # is reliably detected even when the user submits it with no
        # file chosen - without it, that submission fell all the way
        # through to "UPDATE JOB PREFERENCES" below and silently
        # wiped job_title/location/job_type/salary back to empty,
        # while still showing "Profile updated successfully!".

        if request.POST.get("update_cv"):

            if not request.FILES.get("cv"):

                messages.error(
                    request,
                    "Please choose a CV file to upload."
                )

                return redirect(
                    "dashboard_profile"
                )

            cv_file = request.FILES["cv"]


            text = extract_cv_text(
                cv_file
            )


            if not is_valid_cv(text):

                messages.error(
                    request,
                    "Invalid CV file."
                )

                return redirect(
                    "dashboard_profile"
                )


            data = parse_resume(
                text
            )


            save_cv_data(
                request.user,
                data
            )


            # save_cv_data() just wrote profile.skills / job_title to
            # the database using its OWN Profile fetch. The `profile`
            # object here was loaded earlier in this request, before
            # that happened - saving it as-is would overwrite those
            # fresh values with the stale ones still held in memory.
            # Reload before making the one further change (the file)
            # this branch is actually responsible for.
            profile.refresh_from_db()

            profile.cv = cv_file

            profile.save()


            messages.success(
                request,
                "CV uploaded successfully!"
            )


            return redirect(
                "dashboard_profile"
            )


        # =====================================================
        # UPDATE EMAIL
        # =====================================================

        if request.POST.get("update_email"):

            email = request.POST.get(
                "email",
                ""
            ).strip()


            if email:

                request.user.email = email

                request.user.save()


                messages.success(
                    request,
                    "Email updated successfully!"
                )


            return redirect(
                "dashboard_profile"
            )


        # =====================================================
        # UPDATE JOB PREFERENCES
        # =====================================================
        #
        # Job preferences moved to the Settings section - see
        # jobs/views_settings.py. Anything unrecognised that reaches
        # here just reloads the profile rather than being guessed at.

        return redirect(
            "dashboard_profile"
        )


    # =========================================================
    # RENDER USER DASHBOARD
    # =========================================================

    recommended_jobs = get_recommended_jobs(
        request.user,
        profile=profile,
        cv_data=cv_data,
        limit=12,
    )

    saved_job_list = [
        s.job for s in
        SavedJob.objects.filter(
            user=request.user,
            job__in=public_job_queryset(),
        ).select_related('job').order_by('-saved_at')
    ]

    return render(
        request,
        "dashboard/user_dashboard.html",
        {
            "trending_jobs": trending_jobs,

            "active_section": active_section,

            "active_trend_window": trend_window,

            "active_trend_category": trend_category,

            "trend_categories": trend_categories,

            "recommended_jobs": recommended_jobs,

            "saved_job_list": saved_job_list,

            "profile": profile,

            "cv_data": cv_data,

            "jobs": jobs,

            "search_query": query,

            "search_location": location,

            "search_type": job_type,

            "active_window": posted_window,

            "active_category": category,

            "categories": categories,

            "active_source": source,

            "sources": Job.SOURCE_CHOICES,

            "search_submitted": submitted,

            "saved_job_ids": get_saved_job_ids(request),
            "applied_job_ids": get_applied_job_ids(request),
        }
    )


# =========================================================
# ADMIN DASHBOARD
# =========================================================

@login_required
def admin_dashboard(request):

    try:

        profile = Profile.objects.get(
            user=request.user
        )

    except Profile.DoesNotExist:

        return redirect(
            "dashboard"
        )


    # ---------------------------------------------------------
    # ONLY ADMIN
    # ---------------------------------------------------------

    if profile.role != "admin":

        messages.error(
            request,
            "You do not have permission to access the Admin Panel."
        )

        return redirect(
            "dashboard"
        )


    # ---------------------------------------------------------
    # ONLY NORMAL USERS
    # ---------------------------------------------------------

    users = User.objects.filter(
        profile__role="user"
    ).order_by(
        "username"
    )


    return render(
        request,
        "dashboard/admin_dashboard.html",
        {
            "users": users,

            "pending_employer_jobs": _pending_employer_jobs(),

            "scraper_runs": last_run_by_source(),

            "active_section": resolve_section(request, ADMIN_SECTIONS),
        }
    )


def _pending_employer_jobs():
    return Job.objects.filter(
        posted_by__isnull=False,
        posted_by__profile__role="employer",
        source="workvista",
        is_approved=False,
    ).select_related("posted_by").order_by("-first_seen_at")


def _approval_staff_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not Profile.objects.filter(
            user=request.user,
            role__in=("admin", "superadmin"),
        ).exists():
            return HttpResponseForbidden(
                "You do not have permission to manage employer jobs."
            )
        return view(request, *args, **kwargs)

    return wrapper


def _approval_dashboard_url(user):
    if Profile.objects.filter(user=user, role="superadmin").exists():
        return f"{reverse('superadmin_dashboard')}?section=employers"
    return f"{reverse('admin_dashboard')}?section=employers"


@login_required
def manage_employers(request):
    if not Profile.objects.filter(
        user=request.user,
        role__in=("admin", "superadmin"),
    ).exists():
        return HttpResponseForbidden(
            "You do not have permission to manage employer jobs."
        )
    return redirect(_approval_dashboard_url(request.user))


@login_required
@_approval_staff_required
@require_POST
def allow_employer_job(request, job_id):
    approved_job = None
    with transaction.atomic():
        job = _pending_employer_jobs().select_for_update().filter(id=job_id).first()
        if job is None:
            messages.info(request, "This job has already been handled.")
        else:
            job.is_approved = True
            job.save(update_fields=["is_approved"])
            notification = Notification.objects.create(
                user=job.posted_by,
                kind="employer_job_approved",
                job=job,
                title="Your job was approved",
                body=(
                    f'"{job.title}" at {job.company or "your company"} '
                    "is now live."
                ),
            )
            from .alerts.notifications import queue_notification_emails

            queue_notification_emails([notification.pk])
            approved_job = job
            messages.success(request, "Job approved successfully.")

    if approved_job is not None:
        try:
            from .alerts.notifications import notify_job_matches

            notify_job_matches(approved_job)
        except Exception:
            logger.exception(
                "job alerts: matching approved job %s failed", approved_job.pk
            )

    return redirect(_approval_dashboard_url(request.user))


@login_required
@_approval_staff_required
@require_POST
def deny_employer_job(request, job_id):
    with transaction.atomic():
        job = _pending_employer_jobs().select_for_update().filter(id=job_id).first()
        if job is None:
            messages.info(request, "This job has already been handled.")
        else:
            notification = Notification.objects.create(
                user=job.posted_by,
                kind="employer_job_denied",
                job=None,
                title="Your job was not approved",
                body=(
                    f'"{job.title}" at {job.company or "your company"} '
                    "was removed by an administrator."
                ),
            )
            from .alerts.notifications import queue_notification_emails

            queue_notification_emails([notification.pk])
            job.delete()
            messages.success(request, "Job denied and removed successfully.")

    return redirect(_approval_dashboard_url(request.user))


# =========================================================
# ADMIN — DELETE USER
# =========================================================

@login_required
def admin_delete_user(request, user_id):

    try:

        profile = Profile.objects.get(
            user=request.user
        )

    except Profile.DoesNotExist:

        return redirect(
            "dashboard"
        )


    # ---------------------------------------------------------
    # ONLY ADMIN
    # ---------------------------------------------------------

    if profile.role != "admin":

        messages.error(
            request,
            "You do not have permission to delete users."
        )

        return redirect(
            "dashboard"
        )


    # ---------------------------------------------------------
    # ONLY POST
    # ---------------------------------------------------------

    if request.method != "POST":

        return redirect(
            "/dashboard/admin/?section=users"
        )


    # ---------------------------------------------------------
    # ONLY NORMAL USERS CAN BE DELETED
    # ---------------------------------------------------------

    try:

        user_to_delete = User.objects.get(
            id=user_id,
            profile__role="user"
        )

    except User.DoesNotExist:

        messages.error(
            request,
            "User not found."
        )

        return redirect(
            "/dashboard/admin/?section=users"
        )


    username = user_to_delete.username


    user_to_delete.delete()


    messages.success(
        request,
        f"User '{username}' has been deleted successfully."
    )


    return redirect(
        "/dashboard/admin/?section=users"
    )


# =========================================================
# SUPER ADMIN DASHBOARD
# =========================================================

@login_required
def superadmin_dashboard(request):

    try:

        profile = Profile.objects.get(
            user=request.user
        )

    except Profile.DoesNotExist:

        return redirect(
            "dashboard"
        )


    # ---------------------------------------------------------
    # ONLY SUPER ADMIN
    # ---------------------------------------------------------

    if profile.role != "superadmin":

        messages.error(
            request,
            "You do not have permission to access the Super Admin Panel."
        )

        return redirect(
            "dashboard"
        )


    # =========================================================
    # ADD SCRAPER WEBSITE
    # =========================================================

    if request.method == "POST":

        name = request.POST.get(
            "name",
            ""
        ).strip()


        url = request.POST.get(
            "url",
            ""
        ).strip()


        if name and url:

            ScraperWebsite.objects.create(
                name=name,
                url=url
            )


            messages.success(
                request,
                "Website added successfully!"
            )


            return redirect(
                "/dashboard/superadmin/?section=scraper"
            )


    # =========================================================
    # DASHBOARD DATA
    # =========================================================

    websites = ScraperWebsite.objects.all()


    # ---------------------------------------------------------
    # ADMINS
    # ---------------------------------------------------------

    admins = User.objects.filter(
        profile__role="admin"
    ).order_by(
        "username"
    )


    # ---------------------------------------------------------
    # NORMAL USERS
    # ---------------------------------------------------------

    users = User.objects.filter(
        profile__role="user"
    ).order_by(
        "username"
    )


    return render(
        request,
        "dashboard/superadmin_dashboard.html",
        {
            "websites": websites,

            "pending_employer_jobs": _pending_employer_jobs(),

            "admins": admins,

            "users": users,

            "scraper_runs": last_run_by_source(),

            "active_section": resolve_section(request, SUPERADMIN_SECTIONS),
        }
    )


def _staff_profile_response(request, role, template, active_section, form=None):
    if not Profile.objects.filter(user=request.user, role=role).exists():
        return HttpResponseForbidden(
            "You do not have permission to access this profile."
        )

    return render(
        request,
        template,
        {
            "active_section": active_section,
            "form": form,
        },
    )


def _update_staff_profile(request, role, template, profile_url):
    if not Profile.objects.filter(user=request.user, role=role).exists():
        return HttpResponseForbidden(
            "You do not have permission to update this profile."
        )

    if request.method == "POST":
        form = StaffProfileForm(request.POST, user=request.user)
        if form.is_valid():
            saved_user = None
            password_changed = bool(form.cleaned_data["new_password"])

            with transaction.atomic():
                user = User.objects.select_for_update().get(pk=request.user.pk)
                email = form.cleaned_data["email"]
                if User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
                    form.add_error("email", "This email is already in use.")
                else:
                    user.first_name = form.cleaned_data["name"]
                    user.email = email
                    update_fields = ["first_name", "email"]
                    if password_changed:
                        user.set_password(form.cleaned_data["new_password"])
                        update_fields.append("password")
                    user.save(update_fields=update_fields)
                    saved_user = user

            if saved_user is not None:
                if password_changed:
                    update_session_auth_hash(request, saved_user)
                messages.success(request, "Profile updated successfully.")
                return redirect(profile_url)
    else:
        form = StaffProfileForm(user=request.user)

    return _staff_profile_response(
        request,
        role,
        template,
        "profile_update",
        form,
    )


@login_required
@require_http_methods(["GET"])
def admin_profile(request):
    return _staff_profile_response(
        request,
        "admin",
        "dashboard/admin_dashboard.html",
        "profile",
    )


@login_required
@require_http_methods(["GET", "POST"])
def admin_update_profile(request):
    return _update_staff_profile(
        request,
        "admin",
        "dashboard/admin_dashboard.html",
        reverse("admin_profile"),
    )


@login_required
@require_http_methods(["GET"])
def superadmin_profile(request):
    return _staff_profile_response(
        request,
        "superadmin",
        "dashboard/superadmin_dashboard.html",
        "profile",
    )


@login_required
@require_http_methods(["GET", "POST"])
def superadmin_update_profile(request):
    return _update_staff_profile(
        request,
        "superadmin",
        "dashboard/superadmin_dashboard.html",
        reverse("superadmin_profile"),
    )


# =========================================================
# ADD ADMIN
# =========================================================

@login_required
def add_admin(request):

    # -----------------------------------------
    # CHECK CURRENT USER
    # -----------------------------------------

    try:

        current_profile = Profile.objects.get(
            user=request.user
        )

    except Profile.DoesNotExist:

        messages.error(
            request,
            "Your profile was not found."
        )

        return redirect(
            "dashboard"
        )


    # -----------------------------------------
    # ONLY SUPER ADMIN
    # -----------------------------------------

    if current_profile.role != "superadmin":

        messages.error(
            request,
            "Only the Super Admin can add admins."
        )

        return redirect(
            "dashboard"
        )


    # -----------------------------------------
    # ONLY POST
    # -----------------------------------------

    if request.method != "POST":

        return redirect(
            "/dashboard/superadmin/?section=admins"
        )


    # -----------------------------------------
    # GET FORM DATA
    # -----------------------------------------

    username = request.POST.get(
        "username",
        ""
    ).strip()


    email = request.POST.get(
        "email",
        ""
    ).strip()


    password = request.POST.get(
        "password",
        ""
    )


    # -----------------------------------------
    # REQUIRED FIELDS
    # -----------------------------------------

    if (
        not username
        or not email
        or not password
    ):

        messages.error(
            request,
            "Please fill in all fields."
        )

        return redirect(
            "/dashboard/superadmin/?section=admins"
        )


    try:
        validate_email(email)
    except ValidationError:

        messages.error(
            request,
            "Enter a valid email address."
        )

        return redirect(
            "/dashboard/superadmin/?section=admins"
        )


    # -----------------------------------------
    # PASSWORD LENGTH
    # -----------------------------------------

    if len(password) < 6:

        messages.error(
            request,
            "Password must contain at least 6 characters."
        )

        return redirect(
            "/dashboard/superadmin/?section=admins"
        )


    # -----------------------------------------
    # USERNAME CHECK
    # -----------------------------------------

    if User.objects.filter(
        username=username
    ).exists():

        messages.error(
            request,
            "This username already exists."
        )

        return redirect(
            "/dashboard/superadmin/?section=admins"
        )


    # -----------------------------------------
    # EMAIL CHECK
    # -----------------------------------------

    if User.objects.filter(
        email__iexact=email
    ).exists():

        messages.error(
            request,
            "This email is already registered."
        )

        return redirect(
            "/dashboard/superadmin/?section=admins"
        )


    # -----------------------------------------
    # CREATE ADMIN
    # -----------------------------------------

    try:

        with transaction.atomic():

            new_user = User.objects.create_user(
                username=username,
                email=email,
                first_name=username,
                password=password
            )


            new_user.is_staff = False

            new_user.is_superuser = False

            new_user.save()


            # ---------------------------------
            # CREATE / GET PROFILE
            # ---------------------------------

            admin_profile, created = (
                Profile.objects.get_or_create(
                    user=new_user
                )
            )


            admin_profile.role = "admin"

            admin_profile.save()


            # ---------------------------------
            # VERIFY ROLE
            # ---------------------------------

            admin_profile.refresh_from_db()


            if admin_profile.role != "admin":

                raise Exception(
                    "Admin profile role was not saved correctly."
                )


        messages.success(
            request,
            f"Admin '{username}' was created successfully!"
        )


    except Exception as e:

        messages.error(
            request,
            f"Could not create admin: {e}"
        )


    return redirect(
        "/dashboard/superadmin/?section=admins"
    )


# =========================================================
# REMOVE ADMIN
# =========================================================

@login_required
def remove_admin(request, user_id):

    # ---------------------------------------------------------
    # GET CURRENT PROFILE
    # ---------------------------------------------------------

    try:

        profile = Profile.objects.get(
            user=request.user
        )

    except Profile.DoesNotExist:

        return redirect(
            "dashboard"
        )


    # ---------------------------------------------------------
    # ONLY SUPER ADMIN
    # ---------------------------------------------------------

    if profile.role != "superadmin":

        messages.error(
            request,
            "You do not have permission to remove admins."
        )

        return redirect(
            "dashboard"
        )


    # ---------------------------------------------------------
    # ONLY POST
    # ---------------------------------------------------------

    if request.method != "POST":

        return redirect(
            "/dashboard/superadmin/?section=admins"
        )


    # ---------------------------------------------------------
    # FIND ADMIN
    # ---------------------------------------------------------

    try:

        admin_user = User.objects.get(
            id=user_id,
            profile__role="admin"
        )

    except User.DoesNotExist:

        messages.error(
            request,
            "Admin not found."
        )

        return redirect(
            "/dashboard/superadmin/?section=admins"
        )


    # ---------------------------------------------------------
    # SAFETY
    # ---------------------------------------------------------

    if admin_user.id == request.user.id:

        messages.error(
            request,
            "You cannot delete your own Super Admin account."
        )

        return redirect(
            "/dashboard/superadmin/?section=admins"
        )


    if admin_user.is_superuser:

        messages.error(
            request,
            "The Super Admin cannot be removed."
        )

        return redirect(
            "/dashboard/superadmin/?section=admins"
        )


    username = admin_user.username


    admin_user.delete()


    messages.success(
        request,
        f"Admin '{username}' has been removed successfully."
    )


    return redirect(
        "/dashboard/superadmin/?section=admins"
    )


# =========================================================
# DELETE WEBSITE
# =========================================================

@login_required
def delete_website(request, id):

    try:

        profile = Profile.objects.get(
            user=request.user
        )

    except Profile.DoesNotExist:

        return redirect(
            "dashboard"
        )


    # ---------------------------------------------------------
    # ONLY SUPER ADMIN
    # ---------------------------------------------------------

    if profile.role != "superadmin":

        messages.error(
            request,
            "You do not have permission to delete scraper websites."
        )

        return redirect(
            "dashboard"
        )


    if request.method != "POST":

        return redirect(
            "/dashboard/superadmin/?section=scraper"
        )


    ScraperWebsite.objects.filter(
        id=id
    ).delete()


    messages.success(
        request,
        "Website removed successfully."
    )


    return redirect(
        "/dashboard/superadmin/?section=scraper"
    )


# =========================================================
# RUN SCRAPER
# =========================================================

@login_required
def run_scraper(request, scraper_name):

    # ---------------------------------------------------------
    # GET CURRENT PROFILE
    # ---------------------------------------------------------

    try:

        profile = Profile.objects.get(
            user=request.user
        )

    except Profile.DoesNotExist:

        return redirect(
            "dashboard"
        )


    # ---------------------------------------------------------
    # ADMIN + SUPER ADMIN
    # ---------------------------------------------------------

    if profile.role not in [
        "admin",
        "superadmin"
    ]:

        messages.error(
            request,
            "You do not have permission to run scrapers."
        )

        return redirect(
            "dashboard"
        )


    # ---------------------------------------------------------
    # ONLY POST
    # ---------------------------------------------------------

    if request.method != "POST":

        if profile.role == "admin":

            return redirect(
                "/dashboard/admin/?section=scraper"
            )

        return redirect(
            "/dashboard/superadmin/?section=scraper"
        )


    # =========================================================
    # AVAILABLE SCRAPERS
    # =========================================================

    # Shared with the scheduled refresh so the Run buttons and the
    # scheduler can't end up knowing different sets of scrapers.
    scraper_commands = SCRAPER_COMMANDS


    command_name = scraper_commands.get(
        scraper_name
    )


    # ---------------------------------------------------------
    # INVALID SCRAPER
    # ---------------------------------------------------------

    if not command_name:

        messages.error(
            request,
            "Invalid scraper selected."
        )


        if profile.role == "admin":

            return redirect(
                "/dashboard/admin/?section=scraper"
            )


        return redirect(
            "/dashboard/superadmin/?section=scraper"
        )


    # =========================================================
    # RUN SCRAPER
    # =========================================================

    scraper_display_name = (
        scraper_name
        .replace("_", " ")
        .title()
    )


    try:
        summary = run_refresh(
            sources=[scraper_name],
            force=True,
        )
        if not summary["started"]:
            messages.warning(
                request,
                f"{scraper_display_name} was not started: {summary['reason']}."
            )
        else:
            result = summary["results"][scraper_name]
            if result["status"] == "success":
                messages.success(
                    request,
                    f"{scraper_display_name} completed: "
                    f"{result['new_jobs']} new."
                )
            elif result["status"] == "blocked":
                messages.warning(
                    request,
                    f"{scraper_display_name} blocked: {result['error']}"
                )
            else:
                messages.error(
                    request,
                    f"{scraper_display_name} failed: {result['error']}"
                )
    except Exception as error:
        messages.error(
            request,
            f"{scraper_display_name} scraper failed: {error}"
        )


    # =========================================================
    # RETURN TO CORRECT DASHBOARD
    # =========================================================

    if profile.role == "admin":

        return redirect(
            "/dashboard/admin/?section=scraper"
        )


    return redirect(
        "/dashboard/superadmin/?section=scraper"
    )


# =========================================================
# CV UPLOAD PAGE
# =========================================================

@job_seeker_required
def cv_upload(request):

    profile, created = Profile.objects.get_or_create(
        user=request.user,
        defaults={
            "role": "user"
        }
    )


    if request.method == "POST":

        cv_file = request.FILES.get(
            "cv"
        )


        if not cv_file:

            messages.error(
                request,
                "Please upload a CV."
            )

            return redirect(
                "cv_upload"
            )


        if cv_file.content_type != "application/pdf":

            messages.error(
                request,
                "Only PDF files are allowed."
            )

            return redirect(
                "cv_upload"
            )


        text = extract_cv_text(
            cv_file
        )


        if not is_valid_cv(text):

            messages.error(
                request,
                "Invalid CV file."
            )

            return redirect(
                "cv_upload"
            )


        data = parse_resume(
            text
        )


        save_cv_data(
            request.user,
            data
        )


        # See the identical fix + comment in user_dashboard() - this
        # profile object predates save_cv_data()'s own DB write and
        # would otherwise overwrite the skills/job_title it just set.
        profile.refresh_from_db()

        profile.cv = cv_file

        profile.save()


        messages.success(
            request,
            "CV uploaded and parsed successfully!"
        )


        return redirect(
            "preferences"
        )


    return render(
        request,
        "cv_upload.html"
    )


# =========================================================
# PREFERENCES
# =========================================================

@job_seeker_required
def preferences(request):

    profile, created = Profile.objects.get_or_create(
        user=request.user,
        defaults={
            "role": "user"
        }
    )


    if request.method == "POST":

        job_title = request.POST.get(
            "job_title",
            ""
        ).strip()


        # Same validation as the dashboard's own preferences form -
        # see the identical check + comment in user_dashboard().
        if not job_title:

            messages.error(
                request,
                "Preferred job title is required."
            )

            return render(
                request,
                "preferences.html",
                {
                    "profile": profile,
                    "salary_currencies": PROFILE_SALARY_CURRENCY_CHOICES,
                },
            )

        salary = request.POST.get("salary", "").strip()
        salary_currency = request.POST.get(
            "salary_currency", profile.salary_currency or "PKR"
        ).strip()
        if salary and not re.fullmatch(r"[0-9]+", salary):
            messages.error(request, "Salary must contain digits only.")
            return render(
                request,
                "preferences.html",
                {
                    "profile": profile,
                    "salary_currencies": PROFILE_SALARY_CURRENCY_CHOICES,
                },
            )
        if salary_currency not in dict(PROFILE_SALARY_CURRENCY_CHOICES):
            messages.error(request, "Choose a valid salary currency.")
            return render(
                request,
                "preferences.html",
                {
                    "profile": profile,
                    "salary_currencies": PROFILE_SALARY_CURRENCY_CHOICES,
                },
            )

        profile.job_title = job_title


        profile.location = request.POST.get(
            "location",
            ""
        ).strip()


        profile.salary = clean_salary(salary)
        profile.salary_currency = salary_currency


        profile.job_type = request.POST.getlist(
            "job_type"
        )


        profile.save()


        messages.success(
            request,
            "Job preferences saved successfully!"
        )


        return redirect(
            "user_dashboard"
        )


    return render(
        request,
        "preferences.html",
        {
            "profile": profile,
            "salary_currencies": PROFILE_SALARY_CURRENCY_CHOICES,
        },
    )


# =========================================================
# SEARCH JOBS
# =========================================================

def search_jobs(request):

    query = request.GET.get(
        "q",
        ""
    ).strip()


    location = request.GET.get(
        "location",
        ""
    ).strip()


    job_type = request.GET.get(
        "type",
        ""
    ).strip()


    posted_window = request.GET.get(
        "posted",
        ""
    ).strip()


    source = request.GET.get(
        "source",
        ""
    ).strip()


    # Did the visitor actually use the search form? Key presence, not
    # value - see SEARCH_PARAM_KEYS. A genuinely fresh visit (no search
    # keys at all) keeps showing the "Search for your next opportunity"
    # empty state; anything submitted returns results, even with every
    # filter left on "All ..." / "Any time", which now means "show me
    # everything" rather than "show me nothing".
    submitted = search_was_submitted(request)

    engaged = submitted

    # Same "key present vs. not" pattern as Trending's category
    # default (see infer_user_category() / TRENDING.md §6), but only
    # applied once the user has engaged some other way - e.g. clicked
    # a time-window pill with no title typed. Without this, a bare
    # time filter fell back to ranking ALL categories by the user's
    # profile skills/location/salary (rank_jobs() still runs those
    # even with an empty search_query), which reads as "search turned
    # into an undifferentiated trending-style feed" - not a search
    # result at all. Scoping to the inferred category when there's no
    # explicit title keeps results looking like a search, not
    # trending. An explicit "All categories" choice is still honored
    # as exactly that.
    if "category" in request.GET:
        category = request.GET.get("category", "").strip()
    elif engaged and request.user.is_authenticated:
        infer_profile = Profile.objects.filter(user=request.user).first()
        infer_cv_data = CVData.objects.filter(user=request.user).first()
        category = infer_user_category(infer_profile, infer_cv_data) or ""
    else:
        category = ""


    categories = available_categories()


    # =========================================================
    # START WITH EMPTY JOB QUERYSET
    # =========================================================

    jobs = Job.objects.none()


    # =========================================================
    # SEARCH JOB DATABASE
    # =========================================================

    if submitted:

        log_activity(
            request.user,
            "search",
            category=category or (categorize_job(query) if query else ""),
        )

        jobs = apply_search_filters(
            public_job_queryset(),
            query=query,
            location=location,
            job_type=job_type,
            posted_window=posted_window,
            category=category,
            source=source,
        )



        # =====================================================
        # PERSONALIZED RANKING FOR LOGGED-IN USERS
        # =====================================================

        if request.user.is_authenticated:

            profile, created = Profile.objects.get_or_create(

                user=request.user,

                defaults={
                    "role": "user"
                }

            )


            try:

                cv_data = CVData.objects.get(
                    user=request.user
                )

            except CVData.DoesNotExist:

                cv_data = None


            user_skills = get_user_skills(
                profile,
                cv_data
            )


            ranked_jobs = rank_jobs(

                jobs=jobs,

                user_skills=user_skills,

                search_query=query,

                user_location=(
                    profile.location
                    or location
                ),

                user_job_type=(
                    profile.job_type
                    or job_type
                ),

                user_salary=profile.salary,

            )


            # -------------------------------------------------
            # REMOVE INTERNAL SCORES
            # -------------------------------------------------

            jobs = [
                item["job"]
                for item in ranked_jobs
            ]


        # =====================================================
        # RELEVANCE RANKING FOR ANONYMOUS VISITORS
        # =====================================================
        #
        # Not logged in, so there's no skill/preference profile to
        # personalize against - but a title search should still come
        # back best-match-first (title relevance) rather than in
        # arbitrary database order, as general job boards do.

        elif query:

            jobs = sorted(
                jobs,
                key=lambda job: title_match_score(query, job),
                reverse=True,
            )


    # =========================================================
    # RENDER
    # =========================================================

    return render(
        request,
        "search_jobs.html",
        {
            "jobs": jobs,

            "search_query": query,

            "search_location": location,

            "search_type": job_type,

            "active_window": posted_window,

            "active_category": category,

            "categories": categories,

            "active_source": source,

            "sources": Job.SOURCE_CHOICES,

            "search_submitted": submitted,

            "saved_job_ids": get_saved_job_ids(request),
            "applied_job_ids": get_applied_job_ids(request),
        }
    )


# =========================================================
# POST A JOB
# =========================================================
#
# Unlike the other user-dashboard features, Post a Job is its own page
# rather than a tab section inside user_dashboard.html. A form with
# validation errors has to re-render with the submitted values intact,
# which the dashboard's redirect-after-POST sections can't do. It still
# extends base_dashboard.html, so the sidebar is on the left and the
# form opens on the right exactly like the tabs do.


# =========================================================
# SAVED JOBS
# =========================================================

@job_seeker_required
def saved_jobs(request):

    saved = SavedJob.objects.filter(
        user=request.user,
        job__in=public_job_queryset(),
    ).select_related('job').order_by('-saved_at')

    jobs = [s.job for s in saved]

    return render(
        request,
        "dashboard/saved_jobs.html",
        {
            "jobs": jobs,
            "saved_job_ids": {j.id for j in jobs},
            "applied_job_ids": get_applied_job_ids(request),
        }
    )


@job_seeker_required
def applied_jobs(request):
    applications = Application.objects.filter(
        user=request.user,
        job__in=public_job_queryset(),
    ).select_related('job').order_by('-applied_at')

    return render(
        request,
        "dashboard/applied_jobs.html",
        {"applications": applications}
    )


# =========================================================
# SAVE / UNSAVE JOB
# =========================================================

@job_seeker_required
def toggle_save_job(request, job_id):

    if request.method != "POST":
        return redirect("job_detail", job_id=job_id)

    job = get_object_or_404(public_job_queryset(), id=job_id)

    saved, created = SavedJob.objects.get_or_create(
        user=request.user,
        job=job,
    )

    if created:
        messages.success(request, "Job saved.")
    else:
        saved.delete()
        messages.success(request, "Job removed from saved jobs.")

    next_url = request.POST.get("next")

    if next_url and next_url.startswith("/"):
        return redirect(next_url)

    return redirect("job_detail", job_id=job_id)


# =========================================================
# LOGOUT
# =========================================================

def logout_view(request):

    logout(request)


    return redirect(
        "home"
    )


# =========================================================
# EDIT CV
# =========================================================

@job_seeker_required
def edit_cv_data(request):

    cv_data, created = CVData.objects.get_or_create(
        user=request.user
    )


    if request.method == "POST":

        # -----------------------------------------------------
        # KEEP JSON FIELDS AS LISTS
        # -----------------------------------------------------

        cv_data.skills = clean_json_list(
            request.POST.get(
                "skills"
            )
        )


        cv_data.education = clean_json_list(
            request.POST.get(
                "education"
            )
        )


        cv_data.experience = clean_json_list(
            request.POST.get(
                "experience"
            )
        )

        cv_data.certifications = clean_json_list(
            request.POST.get(
                "certifications"
            )
        )

        cv_data.honours = clean_json_list(
            request.POST.get(
                "honours"
            )
        )

        cv_data.training = clean_json_list(
            request.POST.get(
                "training"
            )
        )

        cv_data.languages = clean_json_list(
            request.POST.get(
                "languages"
            )
        )


        cv_data.save()


        # -----------------------------------------------------
        # UPDATE PROFILE SKILLS
        # -----------------------------------------------------

        profile, created = Profile.objects.get_or_create(

            user=request.user,

            defaults={
                "role": "user"
            }

        )


        profile.skills = cv_data.skills

        profile.save()


        messages.success(
            request,
            "CV updated successfully!"
        )


        return redirect(
            "user_dashboard"
        )


    return render(
        request,
        "dashboard/edit_cv.html",
        {
            "cv": cv_data
        }
    )

# =========================================================
# TRENDING JOBS
# =========================================================

def trending_jobs(request):
    # Default time window: past 24 hours
    if "window" in request.GET:
        window = request.GET.get("window", "").strip()
    else:
        window = "24h"

    # Get selected category or infer it for a logged-in user
    if "category" in request.GET:
        category = request.GET.get("category", "").strip()

    elif request.user.is_authenticated:
        user_profile = Profile.objects.filter(
            user=request.user
        ).first()

        user_cv_data = CVData.objects.filter(
            user=request.user
        ).first()

        category = infer_user_category(
            user_profile,
            user_cv_data,
        ) or ""

    else:
        category = ""

    # Start with publicly visible jobs
    jobs_qs = public_job_queryset()

    # Apply selected time window
    if window:
        jobs_qs = apply_time_window(
            jobs_qs,
            window,
        )

    # Categories for the existing dropdown
    categories = available_categories(jobs_qs)

    # Count jobs by category for the graph
    category_counts = list(
        jobs_qs
        .exclude(category__isnull=True)
        .exclude(category="")
        .values("category")
        .annotate(total=Count("id"))
        .order_by("-total", "category")
    )

    # Convert short category names to full display names
    category_name_map = {
            "administration": "Administration and Government",
            "other": "Other",
            "technology": "Technology",
            "sales": "Sales",
            "finance": "Fianance & Accounting",
            "healthcare": "Health Care",
            "web": "Web Development",
            "customer_service": "Customer Service",
            "marketing": "Marketing",
            "research": "Research",
            "hr": "HR",
            "ai": "AI & Machine Learning",
            "devops": "DevOps & Cloud",
            "education": "Education and Tutoring",
            "data": "Data & Analytics",
            "logistics": "Logistics",
            "mobile": "Mobile Development",
            "video": "Video & Motion",
            "design": "Design & UI/UX",
                      }

    category_counts = [
    {
        **item,
        "category": category_name_map.get(
            item["category"].strip().lower(),
            item["category"].replace("_", " ").title(),
        ),
    }
    for item in category_counts
          ]
    # Apply selected category to job cards, not the graph
    if category:
        jobs_qs = jobs_qs.filter(
            category=category
        )

    # Rank the filtered jobs
    jobs = compute_trending_jobs(
        jobs_qs,
        limit=50,
    )

    return render(
        request,
        "dashboard/trending_jobs.html",
        {
            "jobs": jobs,
            "active_window": window,
            "active_category": category,
            "categories": categories,
            "category_counts": category_counts,
            "saved_job_ids": get_saved_job_ids(request),
            "applied_job_ids": get_applied_job_ids(request),
        },
    )


# =========================================================
# SUPER ADMIN — DELETE USER
# =========================================================

@login_required
def delete_user(request, user_id):

    # ---------------------------------------------------------
    # GET CURRENT PROFILE
    # ---------------------------------------------------------

    try:

        profile = Profile.objects.get(
            user=request.user
        )

    except Profile.DoesNotExist:

        return redirect(
            "dashboard"
        )


    # ---------------------------------------------------------
    # ONLY SUPER ADMIN
    # ---------------------------------------------------------

    if profile.role != "superadmin":

        messages.error(
            request,
            "You do not have permission to delete users."
        )

        return redirect(
            "dashboard"
        )


    # ---------------------------------------------------------
    # ONLY POST
    # ---------------------------------------------------------

    if request.method != "POST":

        return redirect(
            "/dashboard/superadmin/?section=users"
        )


    # ---------------------------------------------------------
    # ONLY NORMAL USERS
    # ---------------------------------------------------------

    try:

        user_to_delete = User.objects.get(

            id=user_id,

            profile__role="user"

        )

    except User.DoesNotExist:

        messages.error(
            request,
            "User not found."
        )

        return redirect(
            "/dashboard/superadmin/?section=users"
        )


    # ---------------------------------------------------------
    # DELETE USER
    # ---------------------------------------------------------

    username = user_to_delete.username


    user_to_delete.delete()


    messages.success(
        request,
        f"User '{username}' has been deleted successfully."
    )


    return redirect(
        "/dashboard/superadmin/?section=users"
    )