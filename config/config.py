"""
Central configuration for the ETL pipeline.

Why a config file?
    Every setting that might change between your laptop, Docker and a real
    server (folder paths, database password, API address) lives here, in ONE
    place. The rest of the code asks this module for values instead of
    hardcoding them.

Where do the values come from?
    1. Real environment variables (Docker Compose sets these for Airflow).
    2. A local `.env` file in the project root (for running on Windows).
    3. Safe defaults written below (never for passwords).

Passwords are NEVER written in this file. They must come from `.env`
(which is ignored by Git) or from the environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

# Folder that contains this project's code (the folder with README.md).
CODE_ROOT = Path(__file__).resolve().parents[1]


def load_env_file(path: Path) -> None:
    """Read KEY=VALUE lines from a .env file into os.environ.

    We do this by hand (instead of installing python-dotenv) because it is
    only a few lines. Existing environment variables always win, so Docker
    settings are never overwritten by the local .env file.
    """
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_env_file(CODE_ROOT / ".env")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


# --------------------------------------------------------------------------
# Business configuration: how each branch writes its file.
# This is "metadata about the sources". Adding a 4th branch means adding one
# entry here, not rewriting the cleaning code.
# --------------------------------------------------------------------------
BRANCHES: dict[str, dict] = {
    "B1": {
        "file_name": "sales_branch_1.csv",
        "city": "Patna",
        "default_region": "East",
        "date_format": "%d-%m-%Y",   # 05-03-2025  -> 5 March 2025
    },
    "B2": {
        "file_name": "sales_branch_2.csv",
        "city": "Delhi",
        "default_region": "North",
        "date_format": "%Y-%m-%d",   # 2025-03-05  -> 5 March 2025
    },
    "B3": {
        "file_name": "sales_branch_3.csv",
        "city": "Bengaluru",
        "default_region": "South",
        "date_format": "%m/%d/%Y",   # 03/05/2025  -> 5 March 2025
    },
}

CUSTOMERS_FILE_NAME = "customers.csv"

SALES_REQUIRED_COLUMNS = [
    "transaction_id", "transaction_date", "customer_id", "product_id",
    "product_name", "category", "quantity", "unit_price", "discount",
    "region", "payment_method",
]

CUSTOMER_REQUIRED_COLUMNS = [
    "customer_id", "customer_name", "email", "city", "state", "registration_date",
]

# Placeholder customer used when a sale has no customer ID at all.
UNKNOWN_CUSTOMER_ID = "UNKNOWN"


@dataclass(frozen=True)
class Settings:
    """All runtime settings, bundled together so they are easy to pass around."""

    project_root: Path
    source_dir: Path        # where branches "drop" their files (landing zone)
    raw_dir: Path           # untouched copies made by the extraction step
    processed_dir: Path     # cleaned, validated output
    rejected_dir: Path      # rows we refused, with a reason column
    reference_dir: Path     # saved API snapshot (offline fallback)
    reports_dir: Path       # data quality reports and step status files
    logs_dir: Path          # application log file (pipeline.log)
    sql_dir: Path

    api_base_url: str
    api_timeout_seconds: float
    api_max_retries: int
    api_page_size: int
    api_use_snapshot_fallback: bool
    api_price_to_inr: float  # DummyJSON prices are in USD; we report in INR

    log_level: str

    @property
    def products_snapshot_path(self) -> Path:
        return self.reference_dir / "products_snapshot.json"

    @property
    def database_url(self) -> str:
        """Build the SQLAlchemy connection URL for the sales database.

        Format: postgresql+psycopg2://USER:PASSWORD@HOST:PORT/DATABASE
        If DATABASE_URL is set (tests use SQLite this way), it is used as is.
        """
        explicit = os.getenv("DATABASE_URL")
        if explicit:
            return explicit
        user = os.getenv("SALES_DB_USER")
        password = os.getenv("SALES_DB_PASSWORD")
        if not user or not password:
            raise RuntimeError(
                "Database credentials are missing. Copy .env.example to .env and "
                "fill in SALES_DB_USER and SALES_DB_PASSWORD."
            )
        host = os.getenv("SALES_DB_HOST", "localhost")
        port = os.getenv("SALES_DB_PORT", "5432")
        name = os.getenv("SALES_DB_NAME", "sales_dw")
        # quote_plus protects passwords that contain @, :, / and similar characters.
        return f"postgresql+psycopg2://{user}:{quote_plus(password)}@{host}:{port}/{name}"


def get_settings() -> Settings:
    """Return fresh settings. Read every time, so tests can change env vars."""
    root = Path(os.getenv("ETL_DATA_ROOT", str(CODE_ROOT))).resolve()
    data = root / "data"
    return Settings(
        project_root=root,
        source_dir=Path(os.getenv("ETL_SOURCE_DIR", str(data / "source"))),
        raw_dir=data / "raw",
        processed_dir=data / "processed",
        rejected_dir=data / "rejected",
        reference_dir=Path(os.getenv("ETL_REFERENCE_DIR", str(data / "reference"))),
        reports_dir=root / "reports",
        logs_dir=root / "logs",
        sql_dir=CODE_ROOT / "sql",
        api_base_url=os.getenv("API_BASE_URL", "https://dummyjson.com"),
        api_timeout_seconds=float(os.getenv("API_TIMEOUT_SECONDS", "10")),
        api_max_retries=int(os.getenv("API_MAX_RETRIES", "3")),
        api_page_size=int(os.getenv("API_PAGE_SIZE", "50")),
        api_use_snapshot_fallback=_env_bool("API_USE_SNAPSHOT_FALLBACK", True),
        api_price_to_inr=float(os.getenv("API_PRICE_TO_INR", "85")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
