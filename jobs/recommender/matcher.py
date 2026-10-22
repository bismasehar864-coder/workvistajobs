# jobs/recommender/matcher.py

import re


def normalize_text(value):
    if not value:
        return ""

    return re.sub(r"\s+", " ", str(value).lower()).strip()


def normalize_skill(skill):
    return normalize_text(skill)


def get_user_skills(profile, cv_data=None):
    skills = set()

    if profile and profile.skills:
        skills.update(
            normalize_skill(skill)
            for skill in profile.skills
        )

    if cv_data and cv_data.skills:
        skills.update(
            normalize_skill(skill)
            for skill in cv_data.skills
        )

    return skills


def get_job_skills(job):
    skills = set()

    if job.skills:
        skills.update(
            normalize_skill(skill)
            for skill in job.skills
        )

    return skills


def skill_match_score(user_skills, job_skills):
    if not job_skills:
        return 0

    matched = user_skills.intersection(job_skills)

    return (len(matched) / len(job_skills)) * 100


def title_match_score(search_query, job):
    if not search_query:
        return 0

    query = normalize_text(search_query)
    title = normalize_text(job.title)

    if query == title:
        return 100

    if query in title:
        return 100

    query_words = set(query.split())
    title_words = set(title.split())

    if not query_words:
        return 0

    matched = query_words.intersection(title_words)

    return (len(matched) / len(query_words)) * 100


def location_match_score(user_location, job_location):
    if not user_location or not job_location:
        return 0

    user_location = normalize_text(user_location)
    job_location = normalize_text(job_location)

    if user_location in job_location:
        return 100

    if job_location in user_location:
        return 100

    return 0


def job_type_match_score(user_job_type, job_job_type):
    """user_job_type may be a single string (legacy / search filter
    forms) or a list of strings (Profile.job_type - a user can prefer
    more than one job type). Scores 100 if the job's type matches any
    of them."""

    if not user_job_type or not job_job_type:
        return 0

    job_type_norm = normalize_text(job_job_type)

    if isinstance(user_job_type, (list, tuple, set)):
        preferred = {normalize_text(t) for t in user_job_type if t}
    else:
        preferred = {normalize_text(user_job_type)}

    return 100 if job_type_norm in preferred else 0


def salary_match_score(user_salary, job_salary):
    """
    Basic salary matching.
    Can be improved later when salary values are normalized.
    """

    if not user_salary or not job_salary:
        return 0

    salary_text = normalize_text(job_salary)

    if str(user_salary) in salary_text:
        return 100

    return 0