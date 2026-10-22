"""Does this job suit this person?

Deliberately NOT the same scorer as jobs/recommender/recommend.py. That
one ranks a list, blending in trending and browsing history so a
brand-new user still gets something to look at. This one answers a
yes/no question about a single job, using only what the user explicitly
told us, because the cost of a wrong answer here is an unwanted email
rather than a slightly odd row on a page.
"""

import re

from jobs.recommender.matcher import (
    normalize_text,
    title_match_score,
    location_match_score,
    job_type_match_score,
    salary_match_score,
)


SKILL_POINTS = 100
TITLE_POINTS = 25
LOCATION_POINTS = 10
JOB_TYPE_POINTS = 5
SALARY_POINTS = 5

# A job located "Remote" scores 0 against "Lahore" on plain string
# matching, and remote roles are the ones people most want told about.
REMOTE_MARKERS = ("remote", "work from home", "work-from-home", "anywhere")

# "R" and "C" are real languages, and they also match a word boundary
# in nearly every job description ever written. Two real skills are not
# worth the false-positive rate.
MIN_SKILL_LENGTH = 2

SKILL_ALIASES = {
    "react": ("react", "reactjs", "react.js"),
    "javascript": ("javascript", "js", "ecmascript"),
    "typescript": ("typescript", "ts"),
    "nodejs": ("nodejs", "node.js", "node js"),
    "postgresql": ("postgresql", "postgres"),
    "mongodb": ("mongodb", "mongo"),
    "vue": ("vue", "vuejs", "vue.js"),
    "nextjs": ("nextjs", "next.js"),
}
SKILL_ALIAS_LOOKUP = {
    alias: canonical
    for canonical, aliases in SKILL_ALIASES.items()
    for alias in aliases
}


def normalize_skill(skill):
    """Normalize common spellings without changing recommender matching."""

    normalized = normalize_text(skill)
    return SKILL_ALIAS_LOOKUP.get(normalized, normalized)


def _normalized_skills(skills):
    if isinstance(skills, str):
        skills = [skills]
    elif not isinstance(skills, (list, tuple, set)):
        return set()

    return {
        normalized
        for skill in skills
        if isinstance(skill, str)
        and (normalized := normalize_skill(skill))
        and len(normalized) >= MIN_SKILL_LENGTH
    }


def user_skills_for_matching(profile, cv_data=None):
    """Combine saved profile and parsed-CV skills, safely handling blanks."""

    profile_skills = _normalized_skills(
        getattr(profile, "skills", None) if profile is not None else None
    )
    cv_skills = _normalized_skills(
        getattr(cv_data, "skills", None) if cv_data is not None else None
    )
    return profile_skills | cv_skills


def _haystack(job):
    """Everything about a job that a skill might be named in.

    Job.skills is populated on 27 of 216 rows, and those hold broad
    scraped labels - "Back end", "Cloud" - rather than technologies. It
    matches zero jobs for "python", "django", "react" or "excel". The
    title and description are where the skills actually are.
    """

    parts = [
        normalize_text(job.title),
        normalize_text(job.description),
    ]

    if job.skills:
        parts.extend(normalize_text(skill) for skill in job.skills)

    return " ".join(parts)


def _skill_patterns(skill):
    canonical = normalize_skill(skill)
    aliases = SKILL_ALIASES.get(canonical, (canonical,))
    return tuple(
        re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)")
        for alias in aliases
        if alias
    )


def _matched_skills(user_skills, job):
    haystack = _haystack(job)
    return {
        normalize_skill(skill)
        for skill in user_skills
        if any(pattern.search(haystack) for pattern in _skill_patterns(skill))
    }


def skill_score(user_skills, job):
    """What fraction of the USER's skills this job mentions, 0-100.

    The user's, not the job's: "this job wants 3 of the 5 things I can
    do" is the question a job seeker is actually asking. Scoring the
    job's coverage instead would punish a thorough job description for
    being thorough.
    """

    wanted = _normalized_skills(user_skills)

    if not wanted:
        return 0

    found = len(_matched_skills(wanted, job))

    return (found / len(wanted)) * 100


def location_score(user_location, job_location):
    """The existing location match, plus: remote suits everybody."""

    if not user_location:
        return 0

    if any(marker in normalize_text(job_location) for marker in REMOTE_MARKERS):
        return 100

    return location_match_score(user_location, job_location)


def job_match_details(user_skills, profile, job):
    """Return a priority-weighted score and the matching preference labels."""

    if profile is None:
        return 0, ()

    matched_skills = _matched_skills(user_skills, job)
    if not matched_skills:
        return 0, ()

    title = (
        title_match_score(profile.job_title, job)
        if profile.job_title
        else None
    )

    location = (
        location_score(profile.location, job.location)
        if profile.location
        else None
    )

    job_type = (
        job_type_match_score(profile.job_type, job.job_type)
        if profile.job_type
        else 0
    )
    salary = (
        salary_match_score(profile.salary, job.salary)
        if profile.salary is not None
        else 0
    )
    score = (
        len(matched_skills) * SKILL_POINTS
        + (TITLE_POINTS if title else 0)
        + (LOCATION_POINTS if location else 0)
        + (JOB_TYPE_POINTS if job_type else 0)
        + (SALARY_POINTS if salary else 0)
    )

    matched_fields = ["Skills"]
    if title:
        matched_fields.append("Title")
    if location:
        matched_fields.append("Location")
    if job_type:
        matched_fields.append("Job type")
    if salary:
        matched_fields.append("Salary")

    return score, tuple(matched_fields)


def alert_score(user_skills, profile, job):
    """Compatibility wrapper returning only the weighted match score."""

    return job_match_details(user_skills, profile, job)[0]
