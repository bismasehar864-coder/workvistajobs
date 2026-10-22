import requests
from bs4 import BeautifulSoup

from django.core.management.base import BaseCommand

from jobs.models import Job
from jobs.recommender.categorize import categorize_job


# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = "https://www.python.org"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


# ============================================================
# SCRAPER
# ============================================================

def scrape_python_jobs():

    data = []

    print()
    print("=" * 70)
    print("PYTHON.ORG JOB SCRAPER")
    print("=" * 70)

    # Scrape first 2 pages
    for page in range(1, 3):

        print()
        print("Scraping Page:", page)

        if page == 1:
            url = f"{BASE_URL}/jobs/"
        else:
            url = f"{BASE_URL}/jobs/?page={page}"

        try:

            response = requests.get(
                url,
                headers=HEADERS,
                timeout=15
            )

            response.raise_for_status()

        except requests.RequestException as e:

            print(
                "Request Error:",
                e
            )

            continue

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        # ----------------------------------------------------
        # FIND JOB LIST
        # ----------------------------------------------------

        job_list = soup.find(
            "ol",
            class_="list-recent-jobs"
        )

        if job_list is None:

            print("No job list found.")

            continue

        jobs = job_list.find_all(
            "li"
        )

        print(
            "Jobs Found:",
            len(jobs)
        )

        # ----------------------------------------------------
        # PROCESS JOBS
        # ----------------------------------------------------

        for job in jobs:

            # TITLE
            try:

                title_element = job.find(
                    "a"
                )

                title = title_element.get_text(
                    strip=True
                )

            except:

                title = ""

            # LINK
            try:

                link = (
                    BASE_URL
                    +
                    title_element["href"]
                )

            except:

                link = ""

            # COMPANY
            try:

                company_element = job.find(
                    "span",
                    class_="listing-company-name"
                )

                company = company_element.get_text(
                    " ",
                    strip=True
                )

            except:

                company = ""

            # LOCATION
            try:

                location_element = job.find(
                    "span",
                    class_="listing-location"
                )

                location = location_element.get_text(
                    " ",
                    strip=True
                )

            except:

                location = ""

            # POSTED
            try:

                posted_element = job.find(
                    "time"
                )

                posted = posted_element.get_text(
                    strip=True
                )

            except:

                posted = ""

            # SKILLS / JOB TYPE
            try:

                skill_element = job.find(
                    "span",
                    class_="listing-job-type"
                )

                skill_links = skill_element.find_all(
                    "a"
                )

                skills = [
                    skill.get_text(
                        strip=True
                    )
                    for skill in skill_links
                ]

            except:

                skills = []

            # ------------------------------------------------
            # DISPLAY
            # ------------------------------------------------

            print()
            print("Title   :", title)
            print("Company :", company)
            print("Location:", location)
            print("Posted  :", posted)
            print("Skills  :", skills)
            print("Link    :", link)

            # ------------------------------------------------
            # SAVE DATA
            # ------------------------------------------------

            if title and link:

                data.append(
                    {
                        "title": title,
                        "company": company,
                        "location": location,
                        "posted": posted,
                        "skills": skills,
                        "job_link": link
                    }
                )

    # ========================================================
    # SAVE TO MYSQL
    # ========================================================

    print()
    print("=" * 70)
    print("SAVING PYTHON.ORG JOBS TO MYSQL")
    print("=" * 70)

    saved_count = 0

    for job in data:

        Job.objects.update_or_create(

            job_link=job["job_link"],

            defaults={

                "title": job["title"],

                "company": job["company"],

                "location": job["location"],

                "salary": "",

                "experience": "",

                "education": "",

                "skills": job["skills"],

                "posted": job["posted"],

                "source": "python_org",

                "description": "",

                "category": categorize_job(job["title"], job["skills"]),
            }
        )

        saved_count += 1

        print(
            "✓ Saved:",
            job["title"]
        )

    # ========================================================
    # COMPLETE
    # ========================================================

    print()
    print("=" * 70)
    print("PYTHON.ORG SCRAPING COMPLETE")
    print("=" * 70)

    print(
        "Jobs Found:",
        len(data)
    )

    print(
        "Jobs Saved/Updated:",
        saved_count
    )

    print("=" * 70)


# ============================================================
# DJANGO MANAGEMENT COMMAND
# ============================================================

class Command(BaseCommand):

    help = "Scrape jobs from Python.org"

    def handle(
        self,
        *args,
        **options
    ):

        self.stdout.write(
            self.style.SUCCESS(
                "Starting Python.org scraper..."
            )
        )

        try:

            scrape_python_jobs()

        except KeyboardInterrupt:

            self.stdout.write(
                self.style.WARNING(
                    "Scraper stopped by user."
                )
            )

        except Exception as e:

            self.stdout.write(
                self.style.ERROR(
                    f"Scraper failed: {e}"
                )
            )

            raise

        else:

            self.stdout.write(
                self.style.SUCCESS(
                    "Python.org scraping completed successfully!"
                )
            )
