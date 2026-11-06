# Windows setup guide (step by step)

Follow the steps in order. Each step ends with a **check**. Do not move on until the check passes. If something fails, look in [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

All commands are typed in **PowerShell** (Start menu → type "PowerShell"). Steps marked *(Admin)* need "Run as administrator".

---

## Step 1. Check your computer

```powershell
systeminfo | findstr /B /C:"OS Name" /C:"OS Version" /C:"Total Physical Memory"
```

You need Windows 10 (version 22H2) or Windows 11, 64-bit. RAM: 8 GB works, 16 GB is comfortable. Free disk space: about 15 GB.

**Check:** the output shows your Windows version and memory.

## Step 2. Install Python 3.12

1. Download Python 3.12 (64-bit) from https://www.python.org/downloads/windows/
2. In the installer, tick **"Add python.exe to PATH"**, then "Install Now".
3. Close and reopen PowerShell.

```powershell
python --version
```

**Check:** `Python 3.12.x`. (3.11 and 3.13 also work. Airflow itself runs inside Docker with its own Python, so your Windows Python version does not affect Airflow.)

## Step 3. Install Git and VS Code

* Git: https://git-scm.com/download/win (default options are fine).
* VS Code: https://code.visualstudio.com/ then install the **Python** extension.

```powershell
git --version
```

**Check:** `git version 2.x`.

## Step 4. Install WSL2 *(Admin)*

WSL2 is a real Linux system inside Windows. Docker Desktop uses it to run Linux containers (PostgreSQL and Airflow are Linux programs).

```powershell
wsl --install
```

Restart the computer when asked. After restart an Ubuntu window may open and ask for a username and password: create any (this is only for Linux).

```powershell
wsl --status
wsl -l -v
```

**Check:** "Default Version: 2". If you see an error about virtualization, enable **Virtualization (Intel VT-x / AMD-V / SVM)** in your BIOS (see TROUBLESHOOTING).

## Step 5. Install Docker Desktop

1. Download from https://www.docker.com/products/docker-desktop/ and install.
2. Keep **"Use WSL 2 instead of Hyper-V"** ticked.
3. Start Docker Desktop and wait until the bottom left shows **"Engine running"**.
4. Settings → General: tick "Use the WSL 2 based engine".

```powershell
docker --version
docker compose version
docker run --rm hello-world
```

**Check:** the last command prints "Hello from Docker!".

Optional, for 8 GB laptops: limit WSL's memory so Windows stays responsive. Create the file `C:\Users\<you>\.wslconfig` containing:

```
[wsl2]
memory=4GB
processors=2
```

then run `wsl --shutdown` and restart Docker Desktop.

## Step 6. Put the project in a folder without spaces

Paths with spaces (like `D:\New folder`) cause trouble in some tools. Use for example:

```powershell
mkdir D:\projects
# copy or move the etl-sales-pipeline folder into D:\projects
cd D:\projects\etl-sales-pipeline
```

**Check:** `dir` shows `README.md`, `docker-compose.yml`, `src`, `dags` ...

## Step 7. Create the Python virtual environment

A virtual environment is a private box of Python libraries just for this project, so it never conflicts with other projects.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell says "running scripts is disabled", run this once and try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Your prompt now starts with `(.venv)`. Install the libraries:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**Check:**

```powershell
python -c "import pandas, sqlalchemy, psycopg2, requests, matplotlib; print('all good')"
```

Remember: every new PowerShell window needs `.\.venv\Scripts\Activate.ps1` again.

## Step 8. Create your .env file

```powershell
copy .env.example .env
notepad .env
```

Change at least `POSTGRES_PASSWORD`, `SALES_DB_PASSWORD` (use the **same** value for both), `AIRFLOW_ADMIN_PASSWORD`, `AIRFLOW_JWT_SECRET` and `AIRFLOW_API_SECRET_KEY`. Generate random secrets with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Check:** `.env` exists and `git status` (once you use Git) does **not** list it.

## Step 9. Start PostgreSQL

```powershell
docker compose up -d postgres
docker compose ps
```

**Check:** the `postgres` service shows `healthy` (wait about 20 seconds). Then:

```powershell
docker compose exec postgres psql -U etl_user -d sales_dw -c "SELECT 1;"
```

prints a table with `1`. (Use your POSTGRES_USER if you changed it.)

## Step 10. Run the tests

```powershell
pytest
```

**Check:** about `66 passed, 1 skipped`. The skipped one needs Airflow, which only exists inside Docker.

## Step 11. Run the pipeline without Airflow

```powershell
python -m src.pipeline
```

**Check:** the last lines say `"execution_status": "SUCCESS"`. Run it a second time: the log line says `0 new`, which proves idempotency.

```powershell
python -m analytics.run_queries
python -m analytics.dashboard
```

**Check:** charts appear in `analytics\output\`.

## Step 12. Start Airflow

```powershell
docker compose up -d --build
docker compose ps
```

The first build downloads about 1.5 GB and takes several minutes.

**Check:** `airflow-apiserver`, `airflow-scheduler`, `airflow-dag-processor` and `postgres` are `healthy`; `airflow-init` shows `Exited (0)`.

Open http://localhost:8080, log in, switch on `sales_data_etl_pipeline`, click **Trigger**. All 8 tasks should turn green within a couple of minutes.

## Step 13. Connect a database viewer (optional)

pgAdmin (https://www.pgadmin.org/) or the VS Code "PostgreSQL" extension:

| Field | Value |
|---|---|
| Host | localhost |
| Port | 5432 (or POSTGRES_HOST_PORT) |
| Database | sales_dw |
| User / Password | from `.env` |

## Step 14. Put it on GitHub

```powershell
git init
git add .
git status            # make sure .env is NOT in the list
git commit -m "End-to-end sales ETL pipeline"
git branch -M main
git remote add origin https://github.com/<your-username>/etl-sales-pipeline.git
git push -u origin main
```

Create the empty repository on github.com first (no README, since the project already has one).
