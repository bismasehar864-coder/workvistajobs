import re
import spacy

from spacy.matcher import PhraseMatcher

# ============================
# Load spaCy
# ============================

nlp = spacy.load("en_core_web_sm")

# ============================
# SKILLS DATABASE
# ============================

SKILLS_DB = [

    # Programming
    "python","java","c","c++","c#","javascript","typescript",
    "php","ruby","go","kotlin","swift","r","matlab",

    # Web
    "html","css","bootstrap","tailwind","django","flask",
    "fastapi","react","angular","vue","node.js","express",

    # Database
    "mysql","postgresql","sqlite","mongodb","oracle","sql","firebase",

    # Cloud
    "aws","azure","google cloud","docker","kubernetes",

    # AI
    "machine learning","deep learning","artificial intelligence",
    "data science","nlp","computer vision",

    # BI
    "excel","power bi","tableau","powerpoint","word",

    # Design
    "photoshop","illustrator","figma","canva","adobe xd",

    # Business
    "accounting","finance","marketing","sales","hr",
    "management","customer service","bookkeeping",

    # Engineering
    "autocad","solidworks","civil 3d","ansys",

    # Healthcare
    "patient care","medical coding","clinical research",

    # Soft skills
    "communication","teamwork","leadership",
    "problem solving","critical thinking",
    "time management","adaptability"
]

SKILL_ALIASES = {

    # Programming
    "js": "javascript",
    "java script": "javascript",
    "javascript programming": "javascript",

    "ts": "typescript",
    "type script": "typescript",

    "py": "python",
    "python programming": "python",

    "c plus plus": "c++",
    "cpp": "c++",

    "c sharp": "c#",
    "csharp": "c#",

    # Databases
    "postgres": "postgresql",
    "postgres sql": "postgresql",
    "postgre sql": "postgresql",

    "mongo": "mongodb",
    "mongo db": "mongodb",

    # Microsoft
    "ms excel": "excel",
    "microsoft excel": "excel",

    "ms word": "word",
    "microsoft word": "word",

    "ms powerpoint": "powerpoint",
    "microsoft powerpoint": "powerpoint",

    # Web
    "node": "node.js",
    "nodejs": "node.js",

    # Cloud
    "amazon web services": "aws",
    "google cloud platform": "google cloud",

    # AI
    "ai": "artificial intelligence",
    "ml": "machine learning",
    "dl": "deep learning",

    # Design
    "adobe photoshop": "photoshop",
    "adobe illustrator": "illustrator",
    "adobe xd": "adobe xd",

    # Soft skills
    "problem-solving": "problem solving",
    "critical-thinking": "critical thinking",
    "time-management": "time management",
}

matcher = PhraseMatcher(nlp.vocab, attr="LOWER")

patterns = [nlp.make_doc(skill) for skill in SKILLS_DB]

matcher.add("SKILLS", patterns)

# ============================
# SECTION HEADINGS
# ============================

SECTION_HEADINGS = {

    "skills":[
        "skills",
        "technical skills",
        "core skills",
        "competencies",
        # Europass groups everything under one "Personal skills"
        # heading, then breaks it into sub-headings (communication,
        # organisational, job-related, digital) - each of those reads
        # as its own heading line in the extracted PDF text, so they
        # need to route into "skills" too, not get swallowed by
        # whatever section came before them.
        "personal skills",
        "job-related skills",
        "job related skills",
        "communication skills",
        "organisational / managerial skills",
        "organisational skills",
        "digital competence",
        "digital skills",
        "it skills",
    ],

    "experience":[
        "experience",
        "work experience",
        "employment",
        "employment history",
        "professional experience",
        "internship"
    ],

    "education": [
        "education",
        "academic background",
        "academic qualification",
        "academic qualifications",
        "qualification",
        "qualifications",
        "educational background",
        "education & training",
        "education and training",
        "academic record",
        "academics"
    ],

    "projects":[
        "projects",
        "academic projects",
        "personal projects"
    ],

    "certifications":[
        "certifications",
        "licenses",
        "courses"
    ],

    "honours":[
        "honours and awards",
        "honours & awards",
        "awards and honours",
        "awards & honours",
        "honours",
        "awards",
        "achievements",
    ],

    "training":[
        "training",
        "training courses",
        "training and courses",
        "courses attended",
    ],

    "languages":[
        "languages",
        "language skills",
        "mother tongue",
        "mother tongue(s)",
        "other language(s)",
        "other languages",
    ],

}




# ============================
# SPLIT INTO SECTIONS
# ============================

def _looks_like_heading(clean, word_count):
    """Heuristic guard for the substring fallback below: a heading
    line is short and doesn't read like a sentence or bullet point -
    without this, a body line that happens to mention "training" in
    passing would get misread as a new section start."""

    if word_count > 8:
        return False

    if clean.endswith(('.', ',', ';')):
        return False

    if clean.lstrip().startswith(('-', '*', '•', '–', '—')):
        return False

    return True


def split_sections(text):

    sections = {}

    # A CV section can be "active" under more than one key at once -
    # a combined heading like "Certifications, Training & Honours"
    # (seen on real CVs as a single line covering all three) routes
    # every line until the next heading into all three buckets, since
    # there's no reliable way to tell which bullet belongs to which
    # of the three from formatting alone.
    current = ["header"]

    sections[current[0]] = []

    for line in text.splitlines():

        clean = line.strip()

        if not clean:
            continue

        # Many CVs write section headers as "Skills:" or "SKILLS -"
        # rather than a bare "Skills" - strip trailing punctuation so
        # those still match a heading exactly instead of falling
        # through into whatever section came before them.
        lower = clean.lower().rstrip(":-–— ").strip()
        word_count = len(lower.split())

        # Exact matches always win outright, and *only* exact matches
        # get considered when there are any: a line like "Education
        # and Training" is an exact heading for "education" already,
        # and must not ALSO activate "training" just because the word
        # "training" is a substring of it - that would leak the whole
        # education section into training too. The substring fallback
        # below only kicks in when nothing matched exactly - genuinely
        # combined headings like "Certifications, Training & Honours"
        # that don't exactly match any single category.
        matched = [
            section
            for section, headings in SECTION_HEADINGS.items()
            if lower in headings
        ]

        if not matched and _looks_like_heading(clean, word_count):

            matched = [
                section
                for section, headings in SECTION_HEADINGS.items()
                if any(h in lower for h in headings)
            ]

        if matched:

            current = matched

            # setdefault, not reset: a Europass CV has several
            # different heading lines that all map to the same
            # section (e.g. "Job-related skills" and "Digital
            # competence" both mean "skills") - resetting here
            # would silently throw away everything collected under
            # an earlier heading for that same section.
            for section in current:
                sections.setdefault(section, [])

            continue

        for section in current:
            sections.setdefault(section, []).append(clean)

    for key in sections:

        sections[key] = "\n".join(sections[key])

    return sections

# ============================
# SKILLS
# ============================

def extract_skills(text):

    doc = nlp(text)

    matches = matcher(doc)

    skills = set()

    for _, start, end in matches:
        skills.add(doc[start:end].text.title())

    return sorted(skills)


# ============================
# EDUCATION
# ============================

DEGREE_KEYWORDS = [

    # School
    "matric",
    "matriculation",
    "ssc",
    "secondary school certificate",

    # Intermediate
    "intermediate",
    "hssc",
    "higher secondary",
    "fsc",
    "f.sc",
    "ics",
    "i.cs",
    "fa",
    "f.a",
    "icom",
    "i.com",

    # Diploma
    "diploma",
    "associate degree",
    "adp",

    # Bachelor
    "bs",
    "b.s",
    "bsc",
    "b.sc",
    "ba",
    "b.a",
    "bba",
    "b.b.a",
    "bcom",
    "b.com",
    "be",
    "b.e",
    "btech",
    "b.tech",
    "bcs",
    "llb",

    # Master
    "ms",
    "m.s",
    "msc",
    "m.sc",
    "ma",
    "m.a",
    "mba",
    "m.b.a",
    "mcom",
    "m.com",
    "mphil",
    "m.phil",
    "mcs",

    # Doctorate
    "phd",
    "ph.d",
    "doctorate"
]


UNIVERSITY_KEYWORDS = [

    "university",
    "college",
    "institute",
    "school",
    "polytechnic",
    "academy",
    "faculty",
    "campus"

]


YEAR_REGEX = re.compile(r"(19|20)\d{2}")


def extract_education(section):

    if not section:
        return []

    education = []
    current = None

    lines = [
        line.strip()
        for line in section.splitlines()
        if line.strip()
    ]

    for line in lines:

        lower = line.lower()

        # -------------------------
        # New Degree Found
        # -------------------------
        if any(keyword in lower for keyword in DEGREE_KEYWORDS):

            if current:
                education.append(current)

            current = {
                "degree": line,
                "institution": "",
                "year": ""
            }

            continue

        if current is None:
            continue

        # -------------------------
        # Institution
        # -------------------------
        if any(keyword in lower for keyword in UNIVERSITY_KEYWORDS):

            if not current["institution"]:
                current["institution"] = line

            continue

        # -------------------------
        # Year
        # -------------------------
        match = re.search(r"(19|20)\d{2}", line)

        if match:

            if not current["year"]:
                current["year"] = match.group()

    if current:
        education.append(current)

    return education


# ============================
# EXPERIENCE
# ============================

TITLE_WORDS = [

    "engineer",
    "software engineer",
    "developer",
    "web developer",
    "backend developer",
    "frontend developer",
    "full stack developer",
    "data analyst",
    "business analyst",
    "analyst",
    "manager",
    "assistant manager",
    "project manager",
    "intern",
    "consultant",
    "designer",
    "graphic designer",
    "ui designer",
    "ux designer",
    "teacher",
    "lecturer",
    "professor",
    "accountant",
    "administrator",
    "executive",
    "sales executive",
    "marketing executive",
    "hr executive",
    "officer",
    "supervisor",
    "coordinator",
    "research assistant",
    "research associate",
    "doctor",
    "nurse"

]


def extract_experience(section):

    if not section:
        return []

    experience = []

    current = None

    YEAR_PATTERN = re.compile(
        r"((19|20)\d{2}|present|current|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
        re.I
    )

    COMPANY_WORDS = [
        "ltd",
        "limited",
        "company",
        "corporation",
        "technologies",
        "solutions",
        "systems",
        "software",
        "private",
        "pvt",
        "inc",
        "llc"
    ]

    for line in section.splitlines():

        line = line.strip()

        if not line:
            continue

        lower = line.lower()

        # -------------------------
        # Duration
        # -------------------------

        if YEAR_PATTERN.search(lower):

            if current is None:

                current = {
                    "company": "",
                    "title": "",
                    "duration": "",
                    "description": []
                }

            current["duration"] = line
            continue

        # -------------------------
        # Job Title
        # -------------------------

        if any(title in lower for title in TITLE_WORDS):

            if current is None:

                current = {
                    "company": "",
                    "title": "",
                    "duration": "",
                    "description": []
                }

            current["title"] = line
            continue

        # -------------------------
        # Company
        # -------------------------

        if any(word in lower for word in COMPANY_WORDS):

            if current is None:

                current = {
                    "company": "",
                    "title": "",
                    "duration": "",
                    "description": []
                }

            if current["company"]:

                experience.append(current)

                current = {
                    "company": "",
                    "title": "",
                    "duration": "",
                    "description": []
                }

            current["company"] = line
            continue

        # -------------------------
        # Bullet points
        # -------------------------

        if current is None:

            continue

        current["description"].append(line)

    if current:

        experience.append(current)

    return experience

# ============================
# PROJECTS
# ============================

def extract_projects(section):

    if not section:
        return []

    projects = []

    for line in section.splitlines():

        line = line.strip()

        if len(line) > 3:

            projects.append(line)

    return projects


# ============================
# CERTIFICATIONS
# ============================

def extract_certifications(section):

    if not section:
        return []

    certs = []

    for line in section.splitlines():

        line = line.strip()

        if len(line) > 3:

            certs.append(line)

    return certs

# ============================
# HONOURS / AWARDS
# ============================

def extract_honours(section):

    if not section:
        return []

    honours = []

    for line in section.splitlines():

        line = line.strip()

        if len(line) > 3:

            honours.append(line)

    return honours


# ============================
# TRAINING
# ============================

def extract_training(section):

    if not section:
        return []

    training = []

    for line in section.splitlines():

        line = line.strip()

        if len(line) > 3:

            training.append(line)

    return training


# ============================
# LANGUAGES
# ============================

def extract_languages(section):

    if not section:
        return []

    languages = []

    for line in section.splitlines():

        line = line.strip()

        if len(line) > 1:

            languages.append(line)

    return languages


# ============================
# CONTACT INFO (name / email / phone)
# ============================

EMAIL_REGEX = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# Loosely matches local and international formats without being so
# broad it grabs a random string of digits from elsewhere on the page.
PHONE_REGEX = re.compile(
    r"(\+?\d{1,3}[\s.-]?)?(\(?\d{2,4}\)?[\s.-]?){2,4}\d{3,4}"
)


def extract_contact_info(text, header_section=""):

    email_match = EMAIL_REGEX.search(text)
    email = email_match.group() if email_match else ""

    phone = ""

    for line in header_section.splitlines() or text.splitlines()[:15]:

        match = PHONE_REGEX.search(line)

        if match and len(re.sub(r"\D", "", match.group())) >= 7:

            phone = match.group().strip()
            break

    name = ""

    for line in header_section.splitlines():

        clean = line.strip()

        # A name line: short, alphabetic (plus spaces/periods), no
        # digits or @ - the first line like that at the top of the CV
        # is almost always the candidate's name, on both a normal CV
        # and a Europass one (which leads with it before "Personal
        # information").
        if (
            clean
            and len(clean.split()) <= 5
            and not EMAIL_REGEX.search(clean)
            and not any(ch.isdigit() for ch in clean)
            and re.match(r"^[A-Za-z][A-Za-z.'\s-]+$", clean)
        ):
            name = clean
            break

    return name, email, phone


# ============================
# MAIN PARSER
# ============================

def parse_resume(text):
    """
    Parse resume text into structured data. Works on both a
    conventional CV layout and a Europass CV (which spreads what a
    normal CV calls "skills" across several sub-headings, and adds
    its own Honours/Training/Languages sections) - see
    SECTION_HEADINGS for the heading variants each field recognizes.
    """

    if not text:
        return {
            "name": "",
            "email": "",
            "phone": "",
            "skills": [],
            "education": [],
            "experience": [],
            "certifications": [],
            "honours": [],
            "training": [],
            "languages": [],
        }

    sections = split_sections(text)

    name, email, phone = extract_contact_info(
        text, sections.get("header", "")
    )

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "skills": extract_skills(
            sections.get("skills", "") or text
        ),
        "education": extract_education(
            sections.get("education", "")
        ),
        "experience": extract_experience(
            sections.get("experience", "")
        ),
        "certifications": extract_certifications(
            sections.get("certifications", "")
        ),
        "honours": extract_honours(
            sections.get("honours", "")
        ),
        "training": extract_training(
            sections.get("training", "")
        ),
        "languages": extract_languages(
            sections.get("languages", "")
        ),
    }