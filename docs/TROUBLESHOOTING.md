# Troubleshooting

Find the message you see, then apply the fix. If it is not here, copy the **full** error (the last 20 lines) and ask.

## Python and packages

| Message | Cause | Fix |
|---|---|---|
| `python is not recognized` | Python not on PATH | Reinstall Python and tick "Add python.exe to PATH", reopen PowerShell |
| `running scripts is disabled on this system` | PowerShell policy | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `ModuleNotFoundError: No module named 'pandas'` (or sqlalchemy...) | venv not active | `.\.venv\Scripts\Activate.ps1` then `pip install -r requirements.txt` |
| `ModuleNotFoundError: No module named 'src'` or `'config'` | Command run from the wrong folder | `cd` into the project root (where README.md is) and use `python -m src.pipeline` |
| `pip` tries to compile pandas/numpy and fails | Very new Python without ready-made wheels | Use Python 3.12 |

## Database

| Message | Cause | Fix |
|---|---|---|
| `Database credentials are missing` | No `.env` file | `copy .env.example .env` and fill in passwords |
| `connection refused` / `could not connect to server` on localhost:5432 | PostgreSQL container not running | `docker compose up -d postgres`, wait for `healthy` |
| `password authentication failed for user` | `.env` password differs from the one used when the volume was first created | Either use the original password, or reset: `docker compose down -v` then `docker compose up -d postgres` (**deletes all database data**) |
| `database "sales_dw" does not exist` | The init script only runs on an empty volume | `docker compose exec postgres psql -U etl_user -d airflow -c "CREATE DATABASE sales_dw;"` |
| `port is already allocated` / `bind: address already in use` for 5432 | A PostgreSQL installed directly on Windows uses 5432 | In `.env` set `POSTGRES_HOST_PORT=5433` and `SALES_DB_PORT=5433`, then `docker compose up -d` |
| `Load failed and was rolled back: ... violates foreign key constraint` | A sale refers to a customer/product not in the dimension tables | Should not happen with the pipeline; if you edited processed files by hand, re-run the full pipeline |

## Docker / WSL2

| Message | Cause | Fix |
|---|---|---|
| `WSL 2 requires an update to its kernel component` | Old WSL | `wsl --update` (Admin), restart |
| `Virtualization support not detected` / `0x80370102` | Virtualization disabled in BIOS | Restart into BIOS/UEFI (often F2, F10 or Del), enable Intel VT-x / AMD SVM, save |
| `error during connect: ... docker_engine` / `Cannot connect to the Docker daemon` | Docker Desktop not running | Start Docker Desktop, wait for "Engine running" |
| Computer becomes very slow | WSL using too much RAM | Create `.wslconfig` with `memory=4GB` (see WINDOWS_SETUP step 5), `wsl --shutdown` |
| `airflow-init` exits with code 1 | Usually a database password problem or missing `.env` values | `docker compose logs airflow-init`, check `.env`, then `docker compose down -v` and `docker compose up -d --build` |

## Airflow

| Symptom | Cause | Fix |
|---|---|---|
| http://localhost:8080 does not open | API server still starting (1 to 2 minutes) | `docker compose ps` until `healthy`; `docker compose logs airflow-apiserver` |
| Login fails | Wrong user/password | Use `AIRFLOW_ADMIN_USER` / `AIRFLOW_ADMIN_PASSWORD` from `.env`. If you changed them after the first start: `docker compose exec airflow-apiserver airflow users reset-password -u admin -p <new>` |
| Startup error mentioning `FabAuthManager` / `airflow.providers.fab` | FAB provider missing in the image | In `docker-compose.yml` delete the `AIRFLOW__CORE__AUTH_MANAGER` line and add `AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_ALL_ADMINS: "true"` (local use only: no login) |
| DAG not in the list | Import error, or the dag-processor is not running | `docker compose exec airflow-scheduler airflow dags list-import-errors` |
| `Invalid auth token` / `Signature verification failed` in task logs | Different JWT secrets between containers | Make sure `AIRFLOW_JWT_SECRET` is set in `.env`, then `docker compose up -d --force-recreate` |
| Tasks stay "queued" | Scheduler unhealthy | `docker compose logs airflow-scheduler`; `docker compose restart airflow-scheduler` |
| `check_data_sources` fails with `Missing source file` | File missing in `data/source/` | Run `python scripts\generate_data.py` on Windows (the folder is shared with Docker) |
| `extract_product_data` logs "Using saved snapshot" | Container has no internet / API down | Expected fallback. To use the mock API: run `python scripts\mock_api.py` on Windows and set `API_BASE_URL_DOCKER=http://host.docker.internal:8000` in `.env`, then `docker compose up -d` |
| `PermissionError` writing to `/opt/etl/data` or `logs` | Folder permissions inside the container | `docker compose run --rm --user 0 airflow-init bash -c "chmod -R 777 /opt/etl/data /opt/etl/reports /opt/etl/logs"` |
| `log_pipeline_execution` is red although load was green | An earlier step failed or was skipped; this task deliberately fails the run | Open its log: the message lists which step failed and why |

## Tests

| Symptom | Fix |
|---|---|
| `1 skipped ... could not import 'airflow'` | Normal on Windows. Run the DAG test inside Docker: `docker compose exec airflow-scheduler airflow dags list-import-errors` |
| Many tests fail with `No module named` | Activate the venv and install requirements |
| A test fails after you changed a rule | Read the assertion: it shows the expected and actual value. Either the rule or the test needs updating, on purpose |
