"""The employer side of WorkVista.

Employers do not browse, search or save jobs - they run a company and
post openings. Their dashboard is a separate shell from the job
seeker's for exactly that reason: the sections they must not see are
not in their template at all, so there is nothing to hide conditionally
and no way for one to leak in.

One view per section, rather than the single sectioned view the job
seeker's dashboard uses. That dashboard is one view because its five
sections share heavy context - the profile, the parsed CV, the
trending queryset. These sections share almost nothing and three of
them own a form POST of their own.
"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from .forms import (
    CompanyBranchForm,
    CompanyForm,
    PostJobForm,
)
from .models import CompanyBranch, Job
from .roles import employer_required


def _company(request):
    """The signed-in employer's company.

    employer_required has already established that this user is an
    employer, and signup_employer creates the company in the same
    transaction as the account, so this cannot be missing.
    """

    return request.user.company


@employer_required
def employer_dashboard(request):
    """The bare /dashboard/employer/ - opens the company profile."""

    return redirect(
        "employer_company"
    )


# =========================================================
# COMPANY PROFILE
# =========================================================

@employer_required
def employer_company(request):

    company = _company(request)

    if request.method == "POST":

        form = CompanyForm(
            request.POST,
            instance=company
        )

        if form.is_valid():

            form.save()

            messages.success(
                request,
                "Your company details have been saved."
            )

            return redirect(
                "employer_company"
            )

    else:

        form = CompanyForm(
            instance=company
        )

    return render(
        request,
        "dashboard/employer_company.html",
        {
            "active_section": "company",
            "company": company,
            "form": form,
        }
    )


# =========================================================
# MY POSTINGS
# =========================================================

@employer_required
def employer_postings(request):
    """Everything this employer has posted, with its edit and delete
    controls. Split out of the post form so that page stays one job."""

    return render(
        request,
        "dashboard/employer_postings.html",
        {
            "active_section": "postings",
            "my_jobs": _my_posted_jobs(request.user),
        }
    )


def _own_branch(request, branch_id):
    """A branch belonging to the signed-in employer, or 404.

    Ownership is part of the lookup rather than a check afterwards, so
    another employer's branch is indistinguishable from one that does
    not exist - the same rule _get_own_posting() follows for jobs.
    """

    return get_object_or_404(
        CompanyBranch,
        id=branch_id,
        company=request.user.company,
    )


# =========================================================
# BRANCHES
# =========================================================

@employer_required
def employer_branches(request):

    company = _company(request)

    if request.method == "POST":

        form = CompanyBranchForm(
            request.POST,
            company=company
        )

        if form.is_valid():

            form.save()

            messages.success(
                request,
                f'"{form.instance.name}" has been added.'
            )

            return redirect(
                "employer_branches"
            )

    else:

        form = CompanyBranchForm(
            company=company
        )

    return render(
        request,
        "dashboard/employer_branches.html",
        {
            "active_section": "branches",
            "company": company,
            "branches": company.branches.all(),
            "form": form,
        }
    )


@employer_required
def employer_branch_edit(request, branch_id):

    branch = _own_branch(
        request,
        branch_id
    )

    if request.method == "POST":

        form = CompanyBranchForm(
            request.POST,
            instance=branch,
            company=request.user.company
        )

        if form.is_valid():

            form.save()

            messages.success(
                request,
                f'"{branch.name}" has been updated.'
            )

        else:

            messages.error(
                request,
                form.errors.as_text()
            )

    return redirect(
        "employer_branches"
    )


@employer_required
def employer_branch_delete(request, branch_id):

    branch = _own_branch(
        request,
        branch_id
    )

    if request.method == "POST":

        name = branch.name

        # Jobs posted from here survive - Job.branch is SET_NULL, so
        # they fall back to the head office rather than vanishing with
        # the office that closed.
        branch.delete()

        messages.success(
            request,
            f'"{name}" has been removed. Jobs posted from it are still live.'
        )

    return redirect(
        "employer_branches"
    )


# =========================================================
# POST A JOB
# =========================================================


def _my_posted_jobs(user):

    return Job.objects.filter(
        posted_by=user,
        source="workvista",
    ).order_by("-first_seen_at")


def _get_own_posting(user, job_id):
    """Fetch a WorkVista posting owned by `user`, or raise Http404.

    Ownership is part of the lookup rather than a separate check, so
    someone else's posting - and any scraped job, which has no owner
    at all - is indistinguishable from one that doesn't exist.
    """

    return get_object_or_404(
        Job,
        id=job_id,
        posted_by=user,
        source="workvista",
    )


def _post_job_context(form, company=None, **extra):

    context = {
        "form": form,

        # Rendered locked on the form: the employer posts under their
        # own company, and cannot type another one.
        "company": company,

        "branches": form.branches,

        # The employer sidebar marks whichever section the server says
        # is open, and the post form is one of its four sections.
        "active_section": "post",

    }

    context.update(extra)

    return context


@employer_required
def post_job(request):

    if request.method == "POST":

        form = PostJobForm(request.POST, company=request.user.company)

        if form.is_valid():

            job = form.save(commit=False)

            # Stamped here, never accepted from the form - see
            # PostJobForm's docstring.
            job.source = "workvista"

            job.posted_by = request.user

            job.is_approved = False

            form.save()

            messages.success(
                request,
                "Your job has been submitted and is waiting for admin approval."
            )

            return redirect(
                "post_job"
            )

    else:

        form = PostJobForm(
            company=request.user.company,
        )

    return render(
        request,
        "dashboard/post_job.html",
        _post_job_context(
            form,
            company=request.user.company,
        )
    )


# =========================================================
# EDIT A POSTED JOB
# =========================================================

@employer_required
def edit_posted_job(request, job_id):

    job = _get_own_posting(
        request.user,
        job_id
    )

    if request.method == "POST":

        form = PostJobForm(
            request.POST,
            instance=job,
            company=request.user.company
        )

        if form.is_valid():

            form.save()

            messages.success(
                request,
                f'"{job.title}" has been updated.'
            )

            return redirect(
                "post_job"
            )

    else:

        form = PostJobForm(
            instance=job,
            company=request.user.company
        )

    return render(
        request,
        "dashboard/post_job.html",
        _post_job_context(
            form,
            company=request.user.company,
            editing_job=job,
        )
    )


# =========================================================
# DELETE A POSTED JOB
# =========================================================

@employer_required
def delete_posted_job(request, job_id):

    job = _get_own_posting(
        request.user,
        job_id
    )

    if request.method == "POST":

        title = job.title

        job.delete()

        messages.success(
            request,
            f'"{title}" has been deleted.'
        )

    return redirect(
        "post_job"
    )
