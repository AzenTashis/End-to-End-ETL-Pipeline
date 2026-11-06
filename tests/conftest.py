"""
Shared test setup (pytest loads this file automatically).

Fixtures are reusable "ingredients" for tests:
* data_root : a fresh temporary project folder, so tests never touch your real data/
* engine    : a database for loading tests. By default a temporary SQLite file
              (no PostgreSQL needed). To test against PostgreSQL instead, create an
              EMPTY database (e.g. sales_dw_test) and set TEST_DATABASE_URL, e.g.
              postgresql+psycopg2://etl_user:password@localhost:5432/sales_dw_test
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SALES_HEADER = ["transaction_id", "transaction_date", "customer_id", "product_id", "product_name",
                "category", "quantity", "unit_price", "discount", "region", "payment_method"]


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    """Point the pipeline at an empty temporary folder and an unreachable API."""
    monkeypatch.setenv("ETL_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("ETL_REFERENCE_DIR", str(ROOT / "data" / "reference"))
    monkeypatch.delenv("ETL_SOURCE_DIR", raising=False)
    monkeypatch.setenv("API_BASE_URL", "http://127.0.0.1:9")   # nothing listens here: fails fast
    monkeypatch.setenv("API_MAX_RETRIES", "0")
    monkeypatch.setenv("API_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("API_USE_SNAPSHOT_FALLBACK", "true")
    (tmp_path / "data" / "source").mkdir(parents=True)
    return tmp_path


def write_branch_files(source_dir: Path, rows_by_file: dict[str, list[list[str]]] | None = None) -> None:
    """Create the three branch files (one valid row each unless rows are given)."""
    defaults = {
        "sales_branch_1.csv": [["T00001", "05-03-2025", "C0001", "1", "Mascara", "beauty", "2", "100", "0.1", "east", "upi"]],
        "sales_branch_2.csv": [["T00001", "2025-03-05", "C0002", "2", "Palette", "BEAUTY", "1", "200", "10", "North", "cash"]],
        "sales_branch_3.csv": [["T00001", "03/05/2025", "C0003", "3", "Powder", "Beauty ", "3", "50", "0", "S", "CC"]],
    }
    rows_by_file = rows_by_file or defaults
    for name, rows in rows_by_file.items():
        pd.DataFrame(rows, columns=SALES_HEADER).to_csv(source_dir / name, index=False)


def write_customers_file(source_dir: Path) -> None:
    pd.DataFrame(
        [["C0001", "asha rao", "asha@example.com", "patna", "Bihar", "2022-01-05"],
         ["C0002", "Ravi Jha", "ravi@", "Delhi", "Delhi", "05/01/2022"],
         ["C0003", "Meena Iyer", "", "Chennai", "Tamil Nadu", "2021-07-09"]],
        columns=["customer_id", "customer_name", "email", "city", "state", "registration_date"],
    ).to_csv(source_dir / "customers.csv", index=False)


@pytest.fixture
def source_files(data_root):
    source = data_root / "data" / "source"
    write_branch_files(source)
    write_customers_file(source)
    return source


@pytest.fixture
def engine(tmp_path, monkeypatch):
    pytest.importorskip("sqlalchemy")
    from sqlalchemy import text

    from src.loading.database import create_tables, get_engine

    url = os.getenv("TEST_DATABASE_URL") or f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    eng = get_engine(url)
    if eng.dialect.name == "postgresql":
        with eng.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS sales_transactions, customers, products, etl_logs CASCADE"))
    create_tables(eng)
    yield eng
    eng.dispose()
