# jobs/recommender/categorize.py
#
# Assigns each scraped job a category by keyword-matching its title
# (and skills, as a fallback) - there's no manual tagging or
# per-source category field to trust, since each of the four scraper
# sites structures/labels postings differently. Keyword matching
# against the title is the one signal that's reliably present and
# consistent across every source.
#
# Order matters: title_words are checked against each category in
# the order below, first match wins, so more specific categories
# (e.g. "customer_service") are listed before broad catch-alls.

from .matcher import normalize_text

CATEGORY_KEYWORDS = (
    ('customer_service', (
        'customer service', 'customer support', 'call center',
        'call centre', 'support agent', 'support specialist',
    )),
    ('hr', (
        'hr ', ' hr', 'human resource', 'recruiter', 'recruitment',
        'talent acquisition', 'people operations',
    )),
    ('marketing', (
        'marketing', 'seo', 'social media', 'content writ',
        'copywrit', 'brand ', 'growth marketer',
    )),
    ('sales', (
        'sales', 'business development', 'account executive',
        'telemarketing', 'bdm',
    )),
    ('finance', (
        'accountant', 'accounting', 'finance', 'bookkeep', 'audit',
        'financial analyst', 'payroll',
    )),
    # Before design: "Motion Graphics Designer" and "AI Video Editor"
    # are video roles, and would otherwise be caught by design's
    # 'graphic'/'designer' terms or by the ai block further down.
    ('video', (
        'video editor', 'video edit', 'videographer', 'video producer',
        'motion graphic', 'animator', 'film edit', 'reels editor',
    )),
    ('design', (
        'graphic designer', 'ui/ux', 'ux designer', 'ui designer',
        'illustrator', 'visual designer', 'product designer',
    )),
    ('education', (
        'teacher', 'tutor', 'instructor', 'professor', 'lecturer',
        'trainer',
    )),
    ('healthcare', (
        'nurse', 'doctor', 'physician', 'medical', 'healthcare',
        'health care', 'caregiver', 'pharmacist', 'clinician',
        'dentist', 'therapist', 'patient', 'laboratory', 'clinic',
        'pharma',
        # Specialties. Public-sector health advertisements (PPSC,
        # njp.gov.pk) name the specialty rather than saying "medical" -
        # "Senior Registrar Neonatology" matched nothing at all before
        # these. 'registrar' on its own is deliberately absent: a
        # university registrar is an administrative post.
        'neonatolog', 'gynae', 'obst.', 'obstetric', 'cardiolog',
        'radiolog', 'anesth', 'anaesth', 'surgeon', 'surgery',
        'pediatric', 'paediatric', 'psychiatr', 'oncolog', 'orthopa',
        'dermatolog', 'patholog', 'neurolog', 'ophthalm', 'urolog',
        'nephrolog', 'gastroenterolog', 'midwife', 'physiotherap',
    )),
    ('logistics', (
        'logistics', 'supply chain', 'warehouse', 'driver',
        'dispatcher', 'fleet ',
    )),
    # ---------------------------------------------------------
    # Software fields, narrowest first.
    #
    # These five sit between the non-tech categories above and the
    # general 'technology' bucket below, so a role with a specific
    # field lands there ("Android Developer" -> mobile, "Data Analyst"
    # -> data) while anything generic ("Software Engineer") still falls
    # through to 'technology'. Order within the block matters too:
    # ai before the rest so "Deep Learning Researcher" isn't filed as
    # research, and mobile before web so "React Native Developer"
    # isn't caught by web's 'react'.
    # ---------------------------------------------------------
    ('ai', (
        'machine learning', 'deep learning', 'artificial intelligence',
        'computer vision', 'natural language', 'nlp ', 'llm ',
        'generative ai', 'prompt engineer', 'mlops', 'tensorflow',
        'pytorch', 'ai ',
    )),
    ('mobile', (
        'android', 'ios developer', 'ios engineer', 'ios app',
        'flutter', 'react native', 'kotlin multiplatform',
        'compose multiplatform', 'kmm', 'kmp', 'cmp ', 'swiftui',
        'swift developer', 'cross platform', 'cross-platform',
        'mobile app', 'mobile developer', 'xamarin', 'ionic',
    )),
    ('web', (
        'web developer', 'frontend', 'front end', 'front-end',
        'backend', 'back end', 'back-end', 'full stack', 'full-stack',
        'django', 'laravel', 'angular', 'vue', 'node.js', 'nodejs',
        'php ', 'wordpress', 'shopify', 'react',
    )),
    ('data', (
        # "data " alone used to also catch "Data Entry Operator" (a
        # clerical role, not tech) - kept specific instead.
        'data analyst', 'data scientist', 'data engineer',
        'data science', 'business intelligence', 'power bi',
        'tableau', 'etl ', 'data warehouse',
    )),
    ('devops', (
        'devops', 'site reliability', 'sre ', 'kubernetes', 'docker',
        'terraform', 'cloud engineer', 'cloud architect', 'aws ',
        'azure', 'platform engineer', 'cloud',
    )),
    ('writing', (
        'assignment writ', 'academic writ', 'technical writ',
        'thesis', 'dissertation', 'ghostwrit', 'proofread',
    )),
    ('research', (
        'research', 'scientist ', 'r&d',
    )),
    ('technology', (
        'developer', 'engineer', 'software', 'programmer',
        'database',
        'python', 'java', 'javascript',
        'it ', 'qa ', 'sysadmin',
        'network admin', 'database admin',
        # Degree titles, not job titles - so CV education entries
        # (e.g. "BS Computer Science") classify sensibly too. See
        # infer_user_category() below.
        'computer science', 'software engineering',
        'information technology', 'computer engineering',
        'information systems',
    )),
    # Last of all. These terms ('manager', 'officer', 'assistant') are
    # broad enough to swallow half the site if they ran any earlier -
    # "Marketing Manager" has to stay in marketing - so administration
    # only picks up what nothing more specific claimed. Public-sector
    # listings (njp.gov.pk, PPSC) are mostly these.
    ('administration', (
        'assistant', 'clerk', 'officer', 'manager', 'director',
        'coordinator', 'secretary', 'administrator', 'administrative',
        'data entry', 'receptionist', 'supervisor', 'inspector',
        'superintendent', 'deputy', 'stenographer', 'steno',
        'office boy', 'naib qasid',
    )),
)

# A handful of common degree titles for categories other than
# technology, used by infer_user_category() below - not exhaustive,
# just enough that a CV's education entry has a reasonable chance of
# landing somewhere better than "other".
DEGREE_CATEGORY_KEYWORDS = (
    ('healthcare', ('nursing', 'medicine', 'pharmacy', 'mbbs', 'dentistry')),
    ('finance', ('business administration', 'commerce', 'accounting', 'finance')),
    ('education', ('education', 'teaching')),
    ('design', ('graphic design', 'visual design', 'fine arts')),
)


def categorize_job(title, skills=None):
    text = normalize_text(title)

    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return category

    if skills:
        skills_text = normalize_text(' '.join(str(s) for s in skills))

        for category, keywords in CATEGORY_KEYWORDS:
            if any(keyword in skills_text for keyword in keywords):
                return category

    return 'other'


def _degree_category(degree_text):
    text = normalize_text(degree_text)

    if not text:
        return None

    # Try the same technology-heavy keyword set jobs use first (a CS
    # degree should land in "technology" the same way a "Software
    # Engineer" job title does), then the smaller degree-specific list
    # for fields technology's keywords don't cover.
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return category

    for category, keywords in DEGREE_CATEGORY_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return category

    return None


def infer_user_category(profile=None, cv_data=None):
    """
    A best-guess category for this user, used to default the Trending
    Jobs category filter to something relevant instead of "All
    categories" - e.g. a CS graduate opens Trending and sees
    Technology pre-selected rather than an undifferentiated mix.

    Tries the strongest signal first and falls through: an explicit
    preferred title beats a CV degree, since it's a direct statement
    of intent rather than an inference. Returns None (meaning: don't
    default the filter, leave it on "All categories") if nothing
    gives a confident answer.
    """

    if profile and profile.job_title:
        category = categorize_job(profile.job_title)
        if category != 'other':
            return category

    if cv_data and cv_data.experience:
        for exp in cv_data.experience:
            if isinstance(exp, dict) and exp.get('title'):
                category = categorize_job(exp['title'])
                if category != 'other':
                    return category

    skills = []
    if profile and profile.skills:
        skills += list(profile.skills)
    if cv_data and cv_data.skills:
        skills += list(cv_data.skills)

    if skills:
        category = categorize_job('', skills=skills)
        if category != 'other':
            return category

    if cv_data and cv_data.education:
        for edu in cv_data.education:
            degree = edu.get('degree') if isinstance(edu, dict) else edu
            category = _degree_category(degree)
            if category:
                return category

    return None


def available_categories(queryset=None):
    """
    (value, label, count) for every category that actually has at
    least one job right now, ordered by how many jobs are in it -
    for populating a category filter dropdown without showing empty
    options.
    """

    from django.db.models import Count
    from jobs.models import Job, public_job_queryset

    if queryset is None:
        queryset = public_job_queryset()

    labels = dict(Job.CATEGORY_CHOICES)

    counts = (
        queryset
        .values('category')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    return [
        (row['category'], labels.get(row['category'], row['category']), row['count'])
        for row in counts
    ]
