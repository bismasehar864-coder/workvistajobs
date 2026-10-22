import copy
import re
from datetime import date

from django import forms
from django.forms import formset_factory
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import Company, CompanyBranch, Job, Profile


# =========================
# SIGN IN FORM
# =========================
class SigninForm(forms.Form):
    email = forms.EmailField(
        error_messages={"required": "Please enter your email"},
        widget=forms.EmailInput(attrs={
            "placeholder": "Email",
            "class": "input-field"
        })
    )

    password = forms.CharField(
        error_messages={"required": "Please enter your password"},
        widget=forms.PasswordInput(attrs={
            "placeholder": "Password",
            "class": "input-field"
        })
    )

    def clean(self):
        cleaned_data = super().clean()

        email = cleaned_data.get("email")
        password = cleaned_data.get("password")

        if email and password:
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                raise forms.ValidationError("No account found with this email")

            auth_user = authenticate(username=user.username, password=password)

            if auth_user is None:
                raise forms.ValidationError("Incorrect password")

            self.user = auth_user

        return cleaned_data


PROFILE_SALARY_CURRENCY_CHOICES = (
    ("PKR", "PKR"),
    ("USD", "USD"),
    ("EUR", "EUR"),
    ("GBP", "GBP"),
    ("AED", "AED"),
    ("SAR", "SAR"),
    ("QAR", "QAR"),
    ("CAD", "CAD"),
    ("AUD", "AUD"),
    ("INR", "INR"),
)


class EditProfileForm(forms.ModelForm):
    full_name = forms.CharField(
        max_length=150,
        label="Full name",
        strip=False,
        widget=forms.TextInput(attrs={"class": "input-field"}),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": "input-field"}),
    )
    skills = forms.CharField(
        required=False,
        strip=False,
        widget=forms.Textarea(
            attrs={
                "class": "input-field skills-textarea",
                "rows": 3,
                "spellcheck": "false",
            }
        ),
    )
    job_type = forms.MultipleChoiceField(
        choices=Job.JOB_TYPE_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    cv = forms.FileField(
        required=False,
        widget=forms.FileInput(attrs={"accept": "application/pdf"}),
    )
    job_title = forms.CharField(
        required=False,
        max_length=100,
        strip=False,
        widget=forms.TextInput(attrs={"class": "input-field"}),
    )
    location = forms.CharField(
        required=False,
        max_length=100,
        strip=False,
        widget=forms.TextInput(attrs={"class": "input-field"}),
    )
    new_password = forms.CharField(
        required=False,
        strip=False,
        label="New password",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    confirm_password = forms.CharField(
        required=False,
        strip=False,
        label="Confirm password",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = Profile
        fields = [
            "cv", "skills", "job_title", "location", "salary", "salary_currency",
            "job_type",
        ]
        widgets = {
            "job_title": forms.TextInput(attrs={"class": "input-field"}),
            "location": forms.TextInput(attrs={"class": "input-field"}),
            "salary": forms.NumberInput(attrs={"class": "input-field", "min": 0}),
        }

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

        if not self.is_bound:
            self.initial["full_name"] = user.first_name
            self.initial["email"] = user.email
            self.initial["skills"] = ", ".join(self.instance.skills or [])

        self.fields["salary_currency"] = forms.ChoiceField(
            choices=PROFILE_SALARY_CURRENCY_CHOICES,
            required=False,
            initial=self.instance.salary_currency or "PKR",
        )

    def clean_email(self):
        email = self.cleaned_data["email"]

        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise ValidationError("An account with this email already exists.")

        return email

    def clean_salary_currency(self):
        return self.cleaned_data.get("salary_currency") or (
            self.instance.salary_currency or "PKR"
        )

    def clean_full_name(self):
        full_name = self.cleaned_data["full_name"].strip(" ")
        if not full_name:
            raise ValidationError("This field is required.")
        if not re.fullmatch(r"[A-Za-z ]+", full_name):
            raise ValidationError("Only alphabets are allowed.")
        return full_name

    def clean_job_title(self):
        job_title = (self.cleaned_data.get("job_title") or "").strip(" ")
        if job_title and not re.fullmatch(r"[A-Za-z ]+", job_title):
            raise ValidationError("Only alphabets are allowed.")
        return job_title

    def clean_location(self):
        location = (self.cleaned_data.get("location") or "").strip(" ")
        if location and not re.fullmatch(r"[A-Za-z ,]+", location):
            raise ValidationError("Only alphabets and commas are allowed.")
        return location

    def clean_skills(self):
        skills = self.cleaned_data["skills"].strip()
        return [skill.strip() for skill in re.split(r"[,\n]", skills) if skill.strip()]

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password", "")
        confirm_password = cleaned_data.get("confirm_password", "")

        if new_password != confirm_password:
            if new_password or confirm_password:
                self.add_error("confirm_password", "The passwords do not match.")
            return cleaned_data

        if new_password:
            user = copy.copy(self.user)
            user.first_name = cleaned_data.get("full_name", user.first_name)
            user.email = cleaned_data.get("email", user.email)
            try:
                validate_password(new_password, user=user)
            except ValidationError as error:
                self.add_error("new_password", error)

        return cleaned_data


class StaffProfileForm(forms.Form):
    name = forms.CharField(
        max_length=User._meta.get_field("first_name").max_length,
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )
    email = forms.EmailField(
        max_length=User._meta.get_field("email").max_length,
        error_messages={"invalid": "Enter a valid email address."},
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )
    new_password = forms.CharField(
        required=False,
        strip=False,
        label="New password",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    confirm_password = forms.CharField(
        required=False,
        strip=False,
        label="Confirm password",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.update({
                "name": user.first_name,
                "email": user.email,
            })

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise ValidationError("This field is required.")
        if not re.fullmatch(r"[A-Za-z ]+", name):
            raise ValidationError("Name can only contain letters.")
        return name

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise ValidationError("This email is already in use.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password", "")
        confirm_password = cleaned_data.get("confirm_password", "")

        if new_password != confirm_password:
            if new_password or confirm_password:
                self.add_error(
                    "confirm_password",
                    "The passwords do not match.",
                )
            return cleaned_data

        if new_password:
            user = copy.copy(self.user)
            user.first_name = cleaned_data.get("name", user.first_name)
            user.email = cleaned_data.get("email", user.email)
            try:
                validate_password(new_password, user=user)
            except ValidationError as error:
                self.add_error("new_password", error)

        return cleaned_data


class SignUpForm(forms.Form):
    fullname = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            "placeholder": "Full Name",
            "class": "input-field"
        })
    )

    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "placeholder": "Email",
            "class": "input-field"
        })
    )

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "placeholder": "Password",
            "class": "input-field"
        })
    )

    # ---------------- FULL NAME VALIDATION ----------------
    def clean_fullname(self):
        fullname = self.cleaned_data.get("fullname")

        if any(char.isdigit() for char in fullname):
            raise ValidationError("Name cannot contain numbers")

        return fullname

    # ---------------- EMAIL VALIDATION ----------------
    def clean_email(self):
        email = self.cleaned_data.get("email")

        # already exists check
        if User.objects.filter(email=email).exists():
            raise ValidationError("Email already exists")

        # cannot be only numbers (extra rule you wanted)
        if email.replace("@", "").replace(".", "").isdigit():
            raise ValidationError("Email cannot be only numbers")

        return email

    # ---------------- PASSWORD VALIDATION ----------------
    def clean_password(self):
        password = self.cleaned_data.get("password")

        # at least one special character
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            raise ValidationError("Password must contain at least one special character")

        # optional stronger rule (recommended)
        if len(password) < 6:
            raise ValidationError("Password must be at least 6 characters long")

        return password

# =========================
# BRANCH OFFICES
# =========================
class BranchForm(forms.Form):
    """One branch office row on the employer signup form.

    Both fields are optional at the field level so an untouched row can
    be skipped entirely - branches are optional. A row with one field
    filled is a mistake rather than a skip, so clean() names the missing
    half instead of quietly dropping what was typed.
    """

    name = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "e.g. Karachi office",
            "class": "input-field",
        })
    )

    location = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "e.g. Karachi, Pakistan",
            "class": "input-field",
        })
    )

    @property
    def is_blank(self):
        return not (
            self.cleaned_data.get("name") or self.cleaned_data.get("location")
        )

    def clean(self):
        cleaned_data = super().clean()

        name = cleaned_data.get("name")
        location = cleaned_data.get("location")

        if name and not location:
            self.add_error("location", "Give this branch a location.")

        if location and not name:
            self.add_error("name", "Give this branch a name.")

        return cleaned_data


BranchFormSet = formset_factory(
    BranchForm,
    extra=1,
    can_delete=False,
)


# =========================
# COMPANY DETAILS
# =========================
#
# The company fields appear twice - on employer signup, and on the
# company profile section of the employer dashboard. They are declared
# once here so the two can't drift apart.

FOUNDED_YEAR_FLOOR = 1800


def clean_founded_year(year):
    """Shared validation. Range-checked here rather than on the model so
    that a row already saved can never become unsaveable as time passes."""

    if year is None:
        return year

    if year < FOUNDED_YEAR_FLOOR or year > date.today().year:
        raise ValidationError(
            f"Enter a year between {FOUNDED_YEAR_FLOOR} and {date.today().year}."
        )

    return year


COMPANY_WIDGETS = {
    "name": forms.TextInput(attrs={
        "placeholder": "e.g. Galixo",
        "class": "input-field",
    }),
    "location": forms.TextInput(attrs={
        "placeholder": "e.g. Lahore, Pakistan",
        "class": "input-field",
    }),
    "website": forms.URLInput(attrs={
        "placeholder": "https://yourcompany.com",
        "class": "input-field",
    }),
    "founded_year": forms.NumberInput(attrs={
        "placeholder": "e.g. 2019",
        "class": "input-field",
        "inputmode": "numeric",
    }),
    "description": forms.Textarea(attrs={
        "placeholder": "What does your company do?",
        "class": "input-field",
        "rows": 5,
    }),
}

COMPANY_LABELS = {
    "name": "Company name",
    "location": "Head office location",
    "website": "Website",
    "founded_year": "Founded in",
    "description": "About the company",
}


class CompanyForm(forms.ModelForm):
    """Editing the company on the employer dashboard.

    `owner` is excluded - it is set once at signup and never offered.
    """

    name = forms.CharField(
        widget=COMPANY_WIDGETS["name"],
    )
    location = forms.CharField(
        widget=COMPANY_WIDGETS["location"],
    )
    website = forms.URLField(
        required=False,
        max_length=500,
        widget=COMPANY_WIDGETS["website"],
    )
    founded_year = forms.CharField(
        required=False,
        strip=False,
        widget=forms.TextInput(attrs={
            "placeholder": "e.g. 2019",
            "class": "input-field",
            "inputmode": "numeric",
        }),
    )
    description = forms.CharField(
        required=False,
        widget=COMPANY_WIDGETS["description"],
    )

    class Meta:
        model = Company

        fields = ["name", "location", "website", "founded_year", "description"]

        widgets = COMPANY_WIDGETS

        labels = COMPANY_LABELS

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if (
            not 2 <= len(name) <= 100
            or not re.fullmatch(r"[A-Za-z0-9 .&_'-]+", name)
            or not re.search(r"[A-Za-z]", name)
        ):
            raise ValidationError(
                "Use 2-100 characters with at least one letter; letters, numbers, "
                "spaces, periods, &, hyphens, underscores, and apostrophes are allowed."
            )
        return name

    def clean_location(self):
        location = self.cleaned_data["location"].strip()
        if not 2 <= len(location) <= 100 or not re.fullmatch(
            r"[A-Za-z ,.-]+", location
        ):
            raise ValidationError(
                "Head office location must be 2-100 characters with letters, "
                "spaces, commas, periods, and hyphens only."
            )
        return location

    def clean_website(self):
        website = self.data.get(self.add_prefix("website"), "").strip()
        if website and not re.fullmatch(
            r"https?://(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+"
            r"[A-Za-z]{2,}(?::\d+)?(?:[/?#][^\s]*)?",
            website,
            re.IGNORECASE,
        ):
            raise ValidationError(
                "Enter a valid website URL starting with http:// or https:// "
                "and using a domain with a TLD."
            )
        return website

    def clean_founded_year(self):
        year = self.cleaned_data.get("founded_year", "").strip()
        if not year:
            return None
        if not re.fullmatch(r"\d{4}", year):
            raise ValidationError("Enter exactly four digits for the founded year.")
        return clean_founded_year(int(year))

    def clean_description(self):
        description = self.cleaned_data.get("description", "").strip()
        if len(description) > 1000:
            raise ValidationError("About the company must be 1000 characters or fewer.")
        if description and not re.search(r"[A-Za-z]", description):
            raise ValidationError("About the company must contain at least one letter.")
        return description


class CompanyBranchForm(forms.ModelForm):
    """One branch office on the employer dashboard.

    Distinct from BranchForm, which is the plain Form used inside the
    signup formset: there the company does not exist yet, so there is
    no instance to bind to and no uniqueness to check against.
    """

    class Meta:
        model = CompanyBranch

        fields = ["name", "location"]

        widgets = {
            "name": forms.TextInput(attrs={
                "placeholder": "e.g. Karachi office",
                "class": "input-field",
            }),
            "location": forms.TextInput(attrs={
                "placeholder": "e.g. Karachi, Pakistan",
                "class": "input-field",
            }),
        }

        labels = {
            "name": "Branch name",
            "location": "Branch location",
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Bound to the instance so validate_unique() can check
        # (company, name) - without it the duplicate would only be
        # caught by the database, as an IntegrityError.
        self.company = company

        if company is not None:
            self.instance.company = company

    def validate_unique(self):
        """Check (company, name), which Django would otherwise skip.

        `company` is not a form field - it is set in __init__ from the
        signed-in employer - and Django excludes non-field attributes
        from a ModelForm's unique checks. Without putting it back, a
        duplicate branch name would only be caught by the database, as
        an IntegrityError rather than a message on the form.
        """

        exclude = self._get_validation_exclusions()

        exclude = set(exclude) - {"company"}

        try:
            self.instance.validate_unique(exclude=exclude)
        except ValidationError as error:
            self._update_errors(error)


# =========================
# EMPLOYER SIGN UP FORM
# =========================
class EmployerSignUpForm(SignUpForm):
    """Account and company in one submission.

    Subclasses SignUpForm so the full-name, email and password rules are
    inherited rather than restated - an employer's password is held to
    exactly the same standard as a job seeker's.
    """

    company_name = forms.CharField(
        max_length=255,
        widget=COMPANY_WIDGETS["name"]
    )

    company_location = forms.CharField(
        max_length=255,
        widget=COMPANY_WIDGETS["location"]
    )

    website = forms.URLField(
        max_length=500,
        required=False,
        widget=COMPANY_WIDGETS["website"]
    )

    founded_year = forms.IntegerField(
        required=False,
        widget=COMPANY_WIDGETS["founded_year"]
    )

    description = forms.CharField(
        required=False,
        widget=COMPANY_WIDGETS["description"]
    )

    def clean_founded_year(self):
        return clean_founded_year(self.cleaned_data.get("founded_year"))


# =========================
# POST A JOB FORM
# =========================
class PostJobForm(forms.ModelForm):
    """An employer posting a job through WorkVista itself.

    `source`, `posted_by`, `company` and `location` are deliberately NOT
    form fields. The first two are stamped by the views; the last two
    are stamped in save() from the employer's own company and whichever
    branch they picked. An employer therefore cannot post under another
    company's name, or place an opening somewhere they have no office,
    by editing the HTML.
    """

    salary_min = forms.IntegerField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "salary-number",
            "inputmode": "numeric",
            "placeholder": "Min",
            "aria-label": "Minimum salary",
        })
    )

    salary_max = forms.IntegerField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "salary-number",
            "inputmode": "numeric",
            "placeholder": "Max",
            "aria-label": "Maximum salary",
        })
    )

    salary_currency = forms.ChoiceField(
        choices=[(currency, currency) for currency in Job.SALARY_CURRENCIES],
        initial="PKR",
        widget=forms.Select(attrs={
            "class": "salary-select",
            "aria-label": "Salary currency",
        }),
    )

    title = forms.CharField(
        strip=False,
        widget=forms.TextInput(attrs={
            "placeholder": "e.g. Senior Django Developer",
            "class": "input-field",
        }),
    )
    description = forms.CharField(
        strip=False,
        widget=forms.Textarea(attrs={
            "placeholder": "Describe the role, responsibilities and requirements.",
            "class": "input-field",
            "rows": 8,
        }),
    )

    class Meta:
        model = Job

        fields = [
            "title",
            "description",
            "category",
            "job_type",
            "salary_min",
            "salary_max",
            "salary_currency",
            "job_link",
        ]

        widgets = {
            "title": forms.TextInput(attrs={
                "placeholder": "e.g. Senior Django Developer",
                "class": "input-field",
            }),
            "description": forms.Textarea(attrs={
                "placeholder": "Describe the role, responsibilities and requirements.",
                "class": "input-field",
                "rows": 8,
            }),
            "category": forms.Select(attrs={"class": "input-field"}),
            "job_link": forms.URLInput(attrs={
                "placeholder": "https://yourcompany.com/careers/apply",
                "class": "input-field",
            }),
        }

        labels = {
            "title": "Job title",
            "description": "Job description",
            "category": "Job field category",
            "job_type": "Job type",
            "job_link": "Apply link",
        }

    def __init__(self, *args, company=None, **kwargs):
        instance = kwargs.get("instance")

        super().__init__(*args, **kwargs)

        self.company = company

        if not self.is_bound:
            if instance and instance.salary:
                salary_parts = instance.salary.split()
                currency = salary_parts[0] if salary_parts else ""
                if currency in dict(self.fields["salary_currency"].choices):
                    self.fields["salary_currency"].initial = currency

        # job_type is a plain CharField on Job because scrapers write
        # whatever text the source gave them. Posting through
        # WorkVista is the one place we control it, so constrain it to
        # the same constant list the search dropdowns offer.
        self.fields["job_type"] = forms.ChoiceField(
            choices=Job.JOB_TYPE_CHOICES,
            label="Job type",
            widget=forms.Select(attrs={"class": "input-field"}),
        )

        # Which office this opening is at. The empty choice is the head
        # office, so a company with no branches submits a valid form
        # without any special case - and an id belonging to someone
        # else's company simply isn't in the list.
        self.branches = list(company.branches.all()) if company else []

        head_office = (
            f"Head office \u2014 {company.location}" if company else "Head office"
        )

        self.fields["branch"] = forms.ChoiceField(
            choices=(
                [("", head_office)]
                + [(str(b.id), f"{b.name} \u2014 {b.location}") for b in self.branches]
            ),
            required=False,
            label="Office",
            widget=forms.Select(attrs={"class": "input-field"}),
        )

        if self.instance and self.instance.branch_id:
            self.fields["branch"].initial = str(self.instance.branch_id)

        for name in ("title", "description", "job_link"):
            self.fields[name].required = True

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if (
            not 3 <= len(title) <= 100
            or not re.fullmatch(r"[A-Za-z /&.,-]+", title)
            or not re.search(r"[A-Za-z]", title)
        ):
            raise ValidationError(
                "Job title must be 3-100 characters, contain letters, and use "
                "letters, spaces, hyphens, slashes, &, periods, or commas only."
            )
        return title

    def clean_description(self):
        description = self.cleaned_data["description"].strip()
        if len(description) < 20:
            raise ValidationError("Job description must be at least 20 characters.")
        if len(description) > 3000:
            raise ValidationError("Job description must be 3000 characters or fewer.")
        if not any(character.isalpha() for character in description):
            raise ValidationError("Job description must contain at least one letter.")
        return description

    def clean_branch(self):
        """Re-fetch scoped to this company, so a branch id belonging to
        another employer fails rather than silently relocating a job."""

        raw = self.cleaned_data.get("branch")

        if not raw:
            return None

        for branch in self.branches:
            if str(branch.id) == str(raw):
                return branch

        raise ValidationError("Choose one of your own offices.")

    def clean(self):
        cleaned_data = super().clean()

        salary_min = cleaned_data.get("salary_min")
        salary_max = cleaned_data.get("salary_max")

        if (
            salary_min is not None
            and salary_max is not None
            and salary_min > salary_max
        ):
            self.add_error(
                "salary_max",
                "Minimum salary cannot be greater than maximum salary."
            )

        return cleaned_data

    def save(self, commit=True):
        job = super().save(commit=False)

        branch = self.cleaned_data.get("branch")

        # Stamped, not submitted. Job.company and Job.location stay free
        # text because most of the jobs in the database are scraped and
        # have no Company behind them at all - every job card, search
        # filter and the recommender read these two fields, and they
        # must go on working on one code path for every job.
        if self.company:
            job.company = self.company.name
            job.location = branch.location if branch else self.company.location

        job.branch = branch

        amounts = [
            f"{amount:,}"
            for amount in (job.salary_min, job.salary_max)
            if amount is not None
        ]
        job.salary = (
            f"{self.cleaned_data['salary_currency']} "
            f"{' - '.join(amounts)} /month"
            if amounts
            else self.cleaned_data["salary_currency"]
        )

        if commit:
            job.save()

        return job
