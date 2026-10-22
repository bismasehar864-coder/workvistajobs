import fitz  # PyMuPDF

from .models import Profile, CVData


# =====================================
# PDF TEXT EXTRACTION
# =====================================
def extract_cv_text(file):
    """
    Extract text from uploaded PDF.
    """

    try:
        doc = fitz.open(stream=file.read(), filetype="pdf")

        text = ""

        for page in doc:
            text += page.get_text()

        doc.close()

        return text

    except Exception as e:
        print("PDF Extraction Error:", e)
        return ""


# =====================================
# VALIDATE CV
# =====================================
def is_valid_cv(text):

    if not text:
        return False

    text = text.lower()

    keywords = [
        "experience",
        "education",
        "skills",
        "project",
        "summary",
        "objective",
        "university",
        "college",
        "internship",
        "employment",
        "qualification",
        "certification",
    ]

    score = sum(word in text for word in keywords)

    return score >= 2


# =====================================
# SAVE EXTRACTED DATA
# =====================================
def save_cv_data(user, data):

    cv, created = CVData.objects.get_or_create(user=user)

    cv.name = data.get("name", "")
    cv.email = data.get("email", "")
    cv.phone = data.get("phone", "")

    cv.skills = data.get("skills", [])
    cv.education = data.get("education", [])
    cv.experience = data.get("experience", [])
    # certifications was previously extracted by the parser but never
    # actually persisted here - fixed as part of adding the three
    # fields below.
    cv.certifications = data.get("certifications", [])
    cv.honours = data.get("honours", [])
    cv.training = data.get("training", [])
    cv.languages = data.get("languages", [])

    cv.save()

    profile = Profile.objects.get(user=user)

    profile.skills = data.get("skills", [])

    if (
        not profile.job_title
        and data.get("experience")
    ):
        first_job = data["experience"][0]

        if isinstance(first_job, dict):
            profile.job_title = first_job.get("title", "")

    profile.save()