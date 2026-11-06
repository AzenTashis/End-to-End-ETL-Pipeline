"""
Check that every data source is reachable BEFORE we start extracting.

Why a separate check?
    It is better to fail in 2 seconds with "sales_branch_3.csv is missing"
    than to fail 10 minutes later in the middle of a load. In Airflow this is
    the first task, so a missing file is obvious in the UI.

Rules
-----
* A missing, empty or wrongly shaped CSV file is an ERROR (the run stops,
  and Airflow will retry later, maybe the file arrives late).
* An unreachable API is only a WARNING if a saved snapshot exists, because
  the product step can fall back to it.
"""

from __future__ import annotations

import requests

from config.config import (
    BRANCHES,
    CUSTOMER_REQUIRED_COLUMNS,
    CUSTOMERS_FILE_NAME,
    SALES_REQUIRED_COLUMNS,
    get_settings,
)
from src.exceptions import APIExtractionError, SourceFileError
from src.monitoring.logger import get_logger

logger = get_logger(__name__)


def _check_csv_header(path, required_columns) -> None:
    if not path.exists():
        raise SourceFileError(f"Missing source file: {path}")
    if path.stat().st_size == 0:
        raise SourceFileError(f"Source file is empty: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            header = handle.readline()
    except UnicodeDecodeError as exc:
        raise SourceFileError(f"Source file is not readable UTF-8 text: {path}") from exc
    columns = [column.strip().lower() for column in header.strip().split(",")]
    missing = [column for column in required_columns if column not in columns]
    if missing:
        raise SourceFileError(f"{path.name} is missing columns {missing}")


def check_api(base_url: str, timeout: float) -> tuple[bool, str]:
    """Ask the API for one product. Returns (ok, message)."""
    url = f"{base_url.rstrip('/')}/products"
    try:
        response = requests.get(url, params={"limit": 1}, timeout=timeout)
        if response.status_code != 200:
            return False, f"HTTP {response.status_code}"
        payload = response.json()
        if "products" not in payload:
            return False, "response has no 'products' key"
        return True, "ok"
    except (requests.exceptions.RequestException, ValueError) as exc:
        return False, str(exc)


def check_data_sources() -> dict:
    settings = get_settings()
    checked_files = []
    for branch in BRANCHES.values():
        path = settings.source_dir / branch["file_name"]
        _check_csv_header(path, SALES_REQUIRED_COLUMNS)
        checked_files.append(path.name)
    _check_csv_header(settings.source_dir / CUSTOMERS_FILE_NAME, CUSTOMER_REQUIRED_COLUMNS)
    checked_files.append(CUSTOMERS_FILE_NAME)
    logger.info("All %d source files are present and readable", len(checked_files))

    api_ok, api_message = check_api(settings.api_base_url, settings.api_timeout_seconds)
    snapshot_exists = settings.products_snapshot_path.exists()
    if api_ok:
        logger.info("Product API is reachable at %s", settings.api_base_url)
    elif snapshot_exists and settings.api_use_snapshot_fallback:
        logger.warning("Product API is NOT reachable (%s). The saved snapshot will be used.", api_message)
    else:
        raise APIExtractionError(
            f"Product API is not reachable ({api_message}) and no snapshot fallback is available"
        )

    return {
        "files_checked": checked_files,
        "api_reachable": api_ok,
        "api_message": api_message,
        "snapshot_available": snapshot_exists,
    }
