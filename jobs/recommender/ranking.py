# jobs/recommender/ranking.py

from .scoring import calculate_match_score


def rank_jobs(
    jobs,
    user_skills,
    search_query="",
    user_location="",
    user_job_type="",
    user_salary=None,
):
    ranked_jobs = []

    for job in jobs:

        score = calculate_match_score(
            job=job,
            user_skills=user_skills,
            search_query=search_query,
            user_location=user_location,
            user_job_type=user_job_type,
            user_salary=user_salary,
        )

        ranked_jobs.append({
            "job": job,
            "score": score,
        })

    ranked_jobs.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    return ranked_jobs