# jobs/recommender/scoring.py

from .matcher import (
    skill_match_score,
    title_match_score,
    location_match_score,
    job_type_match_score,
    salary_match_score,
)


def calculate_match_score(
    job,
    user_skills,
    search_query="",
    user_location="",
    user_job_type="",
    user_salary=None,
):
    job_skills = set(job.skills or [])

    skill_score = skill_match_score(
        user_skills,
        job_skills
    )

    title_score = title_match_score(
        search_query,
        job
    )

    location_score = location_match_score(
        user_location,
        job.location
    )

    job_type_score = job_type_match_score(
        user_job_type,
        getattr(job, "job_type", "")
    )

    salary_score = salary_match_score(
        user_salary,
        job.salary
    )

    final_score = (
        skill_score * 0.40 +
        title_score * 0.30 +
        location_score * 0.15 +
        job_type_score * 0.10 +
        salary_score * 0.05
    )

    return round(final_score, 2)