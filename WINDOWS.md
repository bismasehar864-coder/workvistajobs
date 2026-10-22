# Running WorkVista on Windows

Full steps for a Windows machine with **Python 3.11** and **MySQL 8 +
MySQL Workbench**. The database is set up in Workbench; everything else
runs in **PowerShell** from inside the unzipped `workvista` folder.

## 0. Before you start

| Thing | Check | Notes |
|-------|-------|-------|
| Python 3.11 / 3.12 / 3.13 | `python --version` in PowerShell | 3.11.5 is fine |
| MySQL server running | Press `Win+R` → `services.msc` → **MySQL80** says *Running* | If not, right-click → **Start** |
| MySQL Workbench | Opens and shows **Local instance MySQL80** | You need the root password you set when installing MySQL |

Unzip `workvista.zip` somewhere simple, e.g. `C:\Users\<you>\Desktop\workvista`.

---

## Part A — Database (MySQL Workbench)

### A1. Connect

1. Open **MySQL Workbench**.
2. On the home screen click **Local instance MySQL80**.
3. Enter your **root** password (tick *Save password in vault* if you
   like). A query tab opens.

### A2. Create the database

1. Click the **SQL+** icon (top left) for a new query tab, if one isn't open.
2. Paste:

   ```sql
   CREATE DATABASE workvista_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```

3. Click the **⚡ lightning bolt** (Execute). The *Output* panel at the
   bottom shows a green tick.

`utf8mb4` matters — job descriptions contain emoji and non-Latin text.

### A3. Import the schema (tables)

1. Menu **Server → Data Import**.
2. Select **Import from Self-Contained File** and click **…** to browse to
   `workvista\mysql\01_schema.sql`.
3. **Default Target Schema**: choose `workvista_db`.
4. Click **Start Import** (bottom right). Wait for *Import completed*.

### A4. Import the jobs

Repeat A3 with `workvista\mysql\02_seed_jobs.sql`, target schema
`workvista_db` again.

**Order matters**: `01_schema.sql` first, then `02_seed_jobs.sql`.
Do **not** import `03_full_backup.sql` — it contains real user accounts.

### A5. Check it worked

1. In the left **Navigator → Schemas** panel, right-click → **Refresh All**.
2. Expand `workvista_db → Tables` — there should be **21 tables**.
3. In a query tab run:

   ```sql
   SELECT COUNT(*) FROM workvista_db.jobs_job;
   ```

   It should return a few hundred jobs.

You do **not** need `manage.py migrate` — the schema file already
carries Django's migration history.

---

## Part B — Configuration (`.env`)

Open `workvista\.env` in Notepad (it may be hidden: in File Explorer
turn on **View → Show → Hidden items**, or just run `notepad .env` in
PowerShell from the folder).

Make sure these lines match **this** machine:

```
WORKVISTA_DEBUG=True
WORKVISTA_DB_NAME=workvista_db
WORKVISTA_DB_USER=root
WORKVISTA_DB_PASSWORD=<your MySQL root password — the one Workbench asked for>
WORKVISTA_DB_HOST=localhost
WORKVISTA_DB_PORT=3306
```

- `WORKVISTA_SECRET_KEY` must have a value (it already does).
- `WORKVISTA_DB_SSL_CA` must be absent or empty locally.
- Email lines can stay as they are, or be left blank — blank means
  emails print to the terminal instead of being sent.

Save and close.

---

## Part C — Python (PowerShell)

Open **PowerShell** (Start → type *PowerShell*) and go to the folder:

```powershell
cd C:\Users\<you>\Desktop\workvista
```

### C1. Create the virtual environment

```powershell
python -m venv venv311
```

If an old `venv311` folder came along in the zip, delete it first:
`rmdir venv311 -Recurse -Force`.

### C2. Activate it

```powershell
venv311\Scripts\activate
```

The prompt now starts with `(venv311)`.

If you get *"running scripts is disabled on this system"*, run this
once, then activate again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### C3. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

The last line is required — CV parsing fails without the spaCy model,
and it is not in `requirements.txt`. The installs take a few minutes.

### C4. Check and run

```powershell
python manage.py check
python manage.py runserver
```

`check` should end with *System check identified no issues*. Then open
**<http://127.0.0.1:8000/>** in your browser.

`INIT FILE LOADED` printing at startup is harmless. Stop the server
with **Ctrl+C**.

---

## Part D — Admin account (optional)

With the venv active:

```powershell
python manage.py createsuperuser
```

Pick a username, email and password. That gives Django-admin access
(`/admin/`). To also get the WorkVista admin dashboard:

```powershell
python manage.py shell
```

```python
from django.contrib.auth.models import User
from jobs.models import Profile
u = User.objects.get(username="yourname")
Profile.objects.update_or_create(user=u, defaults={"role": "superadmin"})
exit()
```

Sign in at `/signin/` → you land on `/dashboard/superadmin/`.

---

## Every time after this

```powershell
cd C:\Users\<you>\Desktop\workvista
venv311\Scripts\activate
python manage.py runserver
```

MySQL must be running (it normally starts with Windows).

### Useful commands

| Command | Does |
|---------|------|
| `python manage.py refresh_jobs` | Scrape fresh jobs from all browser-free sources |
| `python manage.py test jobs` | Run the test suite |
| `python manage.py send_job_alerts --dry-run` | Show which alert emails would go out |

---

## Common errors

| Error | Fix |
|-------|-----|
| `WORKVISTA_DB_PASSWORD is not set` | `.env` missing, empty password, or not beside `manage.py` |
| `Access denied for user 'root'@'localhost'` | Wrong password in `.env` — use the one Workbench accepts |
| `Can't connect to MySQL server on 'localhost'` | MySQL80 service stopped — start it in `services.msc` |
| `Unknown database 'workvista_db'` | Part A2 not done |
| `Table 'workvista_db.jobs_job' doesn't exist` | Part A3 not done, or imported into the wrong schema |
| `Can't find model 'en_core_web_sm'` | Run `python -m spacy download en_core_web_sm` with the venv active |
| `'python' is not recognized` | Python not on PATH — reinstall with *Add python.exe to PATH* ticked, or use `py` instead of `python` |
| `No module named django` | Venv not active — run `venv311\Scripts\activate` |
| Port 8000 already in use | `python manage.py runserver 8080`, then open <http://127.0.0.1:8080/> |

---

## Later: loading the live database (Aiven) from Workbench

For deploying — see `guidebook/14-deploying.md` for the full Render +
Aiven steps.

1. In the Aiven console, open your MySQL service and note **Host**,
   **Port**, **User** (`avnadmin`), **Password**. Download the
   **CA certificate** as `ca.pem`.
2. In Workbench home, click **⊕** next to *MySQL Connections*:
   - **Connection Name**: `Aiven WorkVista`
   - **Hostname** / **Port** / **Username**: from Aiven
   - **Password → Store in Vault**: the Aiven password
   - **SSL** tab → **Use SSL**: `Require and Verify CA`; **SSL CA File**:
     browse to `ca.pem`
   - **Test Connection**, then **OK**.
3. Open that connection and repeat **A3** and **A4**, but with
   **Default Target Schema** = `defaultdb`.

Keep `ca.pem` out of any GitHub upload — it is in `.gitignore`.
