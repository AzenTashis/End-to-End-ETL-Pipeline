"""
Extract product information from a REST API.

Key ideas
---------
* REST API: a web address that returns data instead of a web page.
  Example request:  GET https://dummyjson.com/products?limit=50&skip=0
* JSON response: text that looks like a Python dict:
      {"products": [{"id": 1, "title": "...", "price": 9.99}], "total": 194,
       "skip": 0, "limit": 50}
* Pagination: the API sends products in pages. We keep asking for the next
  page (skip = 0, 50, 100, ...) until we have `total` products.
* Timeout: if the server does not answer within N seconds we stop waiting,
  instead of letting the pipeline hang forever.
* Retries: temporary errors (HTTP 429/5xx) are retried automatically with a
  growing pause (1s, 2s, 4s ...). This is called exponential backoff.
* Fallback: if the API is still unreachable, we use the last saved snapshot
  so the pipeline keeps working, and we log a clear warning.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.config import get_settings
from src.exceptions import APIExtractionError
from src.monitoring.logger import get_logger

logger = get_logger(__name__)

REQUIRED_PRODUCT_FIELDS = ("id", "title", "category", "price")
MAX_PAGES = 1000  # safety net so a buggy API can never cause an endless loop


def build_session(max_retries: int) -> requests.Session:
    """Create an HTTP session that retries temporary failures automatically."""
    retry = Retry(
        total=max_retries,
        connect=max_retries,
        read=max_retries,
        backoff_factor=1,                       # waits 1s, 2s, 4s ...
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,                  # we check status ourselves
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"Accept": "application/json", "User-Agent": "etl-sales-pipeline/1.0"})
    return session


def _validate_page(payload: Any) -> None:
    """Make sure the JSON has the shape we expect before we trust it."""
    if not isinstance(payload, dict):
        raise APIExtractionError("API response is not a JSON object")
    if "products" not in payload or not isinstance(payload["products"], list):
        raise APIExtractionError("API response has no 'products' list")
    if "total" not in payload:
        raise APIExtractionError("API response has no 'total' field")


def validate_products(products: list[dict]) -> None:
    """Every product must have id, title, category and price."""
    if not products:
        raise APIExtractionError("API returned zero products")
    for index, product in enumerate(products):
        missing = [field for field in REQUIRED_PRODUCT_FIELDS if field not in product]
        if missing:
            raise APIExtractionError(f"Product at position {index} is missing fields: {missing}")


def fetch_all_products(
    base_url: str,
    page_size: int = 50,
    timeout: float = 10,
    max_retries: int = 3,
    session: requests.Session | None = None,
) -> list[dict]:
    """Download every product from the API, page by page."""
    session = session or build_session(max_retries)
    url = f"{base_url.rstrip('/')}/products"
    products: list[dict] = []
    skip = 0

    for _ in range(MAX_PAGES):
        params = {"limit": page_size, "skip": skip,
                  "select": "id,title,description,category,price"}
        try:
            response = session.get(url, params=params, timeout=timeout)
        except requests.exceptions.Timeout as exc:
            raise APIExtractionError(f"API timed out after {timeout}s: {url}") from exc
        except requests.exceptions.ConnectionError as exc:
            raise APIExtractionError(f"Could not connect to API: {url} ({exc})") from exc
        except requests.exceptions.RequestException as exc:
            raise APIExtractionError(f"API request failed: {exc}") from exc

        if response.status_code != 200:
            raise APIExtractionError(
                f"API returned HTTP {response.status_code} for {response.url}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise APIExtractionError("API response is not valid JSON") from exc

        _validate_page(payload)
        page = payload["products"]
        products.extend(page)
        skip += len(page)
        logger.info("Fetched %d products (running total %d of %s)", len(page), skip, payload["total"])
        if not page or skip >= int(payload["total"]):
            break
    else:
        raise APIExtractionError("API pagination did not finish (too many pages)")

    validate_products(products)
    return products


def load_snapshot(path: Path) -> list[dict]:
    """Read the saved product snapshot (offline fallback)."""
    if not path.exists():
        raise APIExtractionError(f"No product snapshot found at {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise APIExtractionError(f"Product snapshot is not valid JSON: {path}") from exc
    products = payload.get("products", payload) if isinstance(payload, dict) else payload
    validate_products(products)
    return products


def save_snapshot(products: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {"products": products, "total": len(products), "skip": 0, "limit": len(products)}
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")


def products_to_dataframe(products: list[dict]) -> pd.DataFrame:
    """Flatten the JSON list into a table with the columns we need."""
    frame = pd.DataFrame(products)
    for column in ("id", "title", "category", "price", "description"):
        if column not in frame.columns:
            frame[column] = None
    return frame[["id", "title", "category", "price", "description"]]


def get_products(allow_fallback: bool | None = None) -> tuple[list[dict], str]:
    """Return (products, source) where source is 'api' or 'snapshot'."""
    settings = get_settings()
    if allow_fallback is None:
        allow_fallback = settings.api_use_snapshot_fallback
    try:
        products = fetch_all_products(
            settings.api_base_url,
            page_size=settings.api_page_size,
            timeout=settings.api_timeout_seconds,
            max_retries=settings.api_max_retries,
        )
        return products, "api"
    except APIExtractionError as exc:
        if not allow_fallback:
            raise
        logger.warning("Product API unavailable (%s). Using saved snapshot instead.", exc)
        return load_snapshot(settings.products_snapshot_path), "snapshot"


def extract_products(output_dir: Path) -> dict:
    """Extraction step: save raw products as JSON (exact copy) and CSV (flat)."""
    products, source = get_products()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "products_raw.json").write_text(json.dumps(products, indent=2), encoding="utf-8")
    frame = products_to_dataframe(products)
    frame.to_csv(output_dir / "products_raw.csv", index=False)
    logger.info("Saved %d products from %s to %s", len(frame), source, output_dir)
    return {"products_extracted": len(frame), "product_source": source}
