"""Settings: what you're looking for, and how we tell you about it.

Job preferences used to sit on My Profile, between the account email
and the parsed CV. They are not identity - they are how the site
behaves for you - so they live here instead, next to the alerts switch
that acts on them.

Two separate POSTs on one page, each gated on its own marker field.
That separation is load-bearing: an unchecked switch submits nothing at
all, so if the preferences form and the switch shared a handler,
pressing "Save preferences" would silently unsubscribe anyone whose
switch happened to be off-screen.
"""

import re

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render

from .forms import EditProfileForm, PROFILE_SALARY_CURRENCY_CHOICES
from .models import Job
from .resume_parser import parse_resume
from .utils import extract_cv_text, is_valid_cv, save_cv_data
from .views import clean_salary
from .utils_settings import seeker_profile


@login_required
def edit_profile(request):
    profile = seeker_profile(request)

    if profile is None:
        return redirect("dashboard")

    if request.method == "POST":
        form = EditProfileForm(
            request.POST,
            request.FILES,
            instance=profile,
            user=request.user,
        )

        if form.is_valid():
            uploaded_cv = request.FILES.get("cv")
            parsed_cv_data = None
            password_changed = bool(form.cleaned_data["new_password"])

            if uploaded_cv:
                cv_text = extract_cv_text(uploaded_cv)

                if not is_valid_cv(cv_text):
                    form.add_error("cv", "Upload a readable CV containing resume information.")
                else:
                    parsed_cv_data = parse_resume(cv_text)
                    uploaded_cv.seek(0)

            if not form.errors:
                with transaction.atomic():
                    request.user.first_name = form.cleaned_data["full_name"]
                    request.user.email = form.cleaned_data["email"]
                    update_fields = ["first_name", "email"]
                    if password_changed:
                        request.user.set_password(form.cleaned_data["new_password"])
                        update_fields.append("password")
                    request.user.save(update_fields=update_fields)

                    if parsed_cv_data is not None:
                        save_cv_data(request.user, parsed_cv_data)

                    form.save()

                if password_changed:
                    update_session_auth_hash(request, request.user)
                messages.success(request, "Profile updated successfully.")
                return redirect("dashboard_profile")
    else:
        form = EditProfileForm(instance=profile, user=request.user)

    return render(
        request,
        "dashboard/edit_profile.html",
        {
            "active_section": "edit_profile",
            "form": form,
            "profile": profile,
            "salary_currencies": PROFILE_SALARY_CURRENCY_CHOICES,
        },
    )


@login_required
def dashboard_settings(request):

    profile = seeker_profile(request)

    if profile is None:
        return redirect("dashboard")

    if request.method == "POST":

        if request.POST.get("update_preferences"):
            return _save_preferences(request, profile)

        if request.POST.get("update_alerts"):
            return _save_alerts(request, profile)

        # Anything unrecognised just reloads. Guessing what an unknown
        # form meant is how the old profile view used to wipe
        # preferences when the CV form was submitted empty.
        return redirect("dashboard_settings")

    return render(
        request,
        "dashboard/preferences.html",
        {
            "active_section": "settings",
            "profile": profile,
            "job_types": Job.JOB_TYPE_CHOICES,
            "salary_currencies": PROFILE_SALARY_CURRENCY_CHOICES,
        },
    )


def _save_preferences(request, profile):
    """Title, location and job types. Never the alerts switch."""

    job_title = request.POST.get("job_title", "").strip(" ")

    # Required: it is the strongest signal both infer_user_category()
    # and the recommendation formula's preference score have to work
    # with, and the alert scorer's title term reads it directly.
    if not job_title:

        messages.error(request, "Add a preferred job title so we know what to match.")

        return redirect("dashboard_settings")

    if not re.fullmatch(r"[A-Za-z ,/-]+", job_title):
        messages.error(
            request,
            "Preferred job title: Only alphabets, commas, / and - are allowed.",
        )
        return redirect("dashboard_settings")

    location = request.POST.get("location", "").strip(" ")
    if location and not re.fullmatch(r"[A-Za-z ,]+", location):
        messages.error(request, "Location: Only alphabets and commas are allowed.")
        return redirect("dashboard_settings")

    profile.job_title = job_title

    profile.location = location

    # Zero, one or several - job_type_match_score() treats an empty
    # list as "no restriction" rather than "match nothing".
    profile.job_type = request.POST.getlist("job_type")

    salary = request.POST.get("salary", "").strip()
    if salary and not re.fullmatch(r"[0-9]+", salary):
        messages.error(request, "Salary must contain digits only.")
        return redirect("dashboard_settings")

    salary_currency = request.POST.get(
        "salary_currency", profile.salary_currency or "PKR"
    ).strip()
    if salary_currency not in dict(PROFILE_SALARY_CURRENCY_CHOICES):
        messages.error(request, "Choose a valid salary currency.")
        return redirect("dashboard_settings")

    profile.salary = clean_salary(salary)
    profile.salary_currency = salary_currency

    profile.save(
        update_fields=[
            "job_title", "location", "job_type", "salary", "salary_currency"
        ]
    )

    messages.success(request, "Preferences saved successfully!")

    return redirect("dashboard_settings")


def _save_alerts(request, profile):
    """The switch, and nothing else.

    Its own form and its own marker field, so presence/absence of the
    checkbox is only ever read when the switch was actually on screen.
    """

    profile.email_job_alerts = "email_job_alerts" in request.POST

    profile.save(update_fields=["email_job_alerts"])

    messages.success(
        request,
        "Job alert emails are on."
        if profile.email_job_alerts
        else "Job alert emails are off.",
    )

    return redirect("dashboard_settings")
