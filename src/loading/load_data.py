"""
Load the cleaned data into PostgreSQL, safely and repeatably.

Key ideas
---------
* Upsert ("update or insert"):
      INSERT INTO customers (...) VALUES (...)
      ON CONFLICT (customer_id) DO UPDATE SET customer_name = EXCLUDED.customer_name, ...
  If the primary key already exists, the row is UPDATED instead of added
  again. This is what makes the pipeline IDEMPOTENT: run it 5 times, every
  sale is still stored exactly once.
  (EXCLUDED means "the new values we just tried to insert".)

* One transaction for all three tables: customers, products and sales are
  written inside a single `engine.begin()` block. If inserting sales fails
  half way, the customers and products written moments earlier are rolled
  back too. The database is never left half updated.

* Order matters: customers and products first, then sales, because a sale's
  foreign keys must point at rows that already exist.

* Batches: rows are sent 1,000 at a time, which is much faster than one
  INSERT per row and keeps memory use small for big files.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from src.exceptions import DatabaseError
from src.loading.database import create_tables, table_counts
from src.monitoring.logger import get_logger

logger = get_logger(__name__)

BATCH_SIZE = 1000

TABLES = {
    "customers": {
        "key": ["customer_id"],
        "columns": ["customer_id", "customer_name", "email", "city", "state",
                    "registration_date", "is_placeholder"],
    },
    "products": {
        "key": ["product_id"],
        "columns": ["product_id", "product_name", "category", "unit_price", "description", "is_placeholder"],
    },
    "sales_transactions": {
        "key": ["branch_id", "transaction_id"],
        "columns": ["branch_id", "transaction_id", "customer_id", "product_id", "transaction_date",
                    "quantity", "unit_price", "discount", "total_amount", "discount_amount",
                    "final_amount", "region", "payment_method", "transaction_year",
                    "transaction_month", "transaction_quarter", "source_file"],
    },
}
DATE_COLUMNS = {"registration_date", "transaction_date"}


def build_upsert_sql(table: str, columns: list[str], key: list[str]) -> str:
    """Create an INSERT ... ON CONFLICT DO UPDATE statement with :named parameters.

    Works in PostgreSQL and in SQLite (used by the tests).
    """
    column_list = ", ".join(columns)
    placeholders = ", ".join(f":{column}" for column in columns)
    updates = [f"{column} = EXCLUDED.{column}" for column in columns if column not in key]
    updates.append("updated_at = CURRENT_TIMESTAMP")
    return (
        f"INSERT INTO {table} ({column_list}) VALUES ({placeholders}) "
        f"ON CONFLICT ({', '.join(key)}) DO UPDATE SET {', '.join(updates)}"
    )


def _python_value(value, column: str, dates_as_text: bool):
    """Convert Pandas/NumPy values into plain Python values the database driver understands."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is pd.NaT or (not isinstance(value, (str, bytes)) and pd.isna(value)):
        return None
    if column in DATE_COLUMNS:
        parsed = pd.Timestamp(value).date()
        return parsed.isoformat() if dates_as_text else parsed
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value
    return value


def dataframe_to_records(df: pd.DataFrame, columns: list[str], dates_as_text: bool = False) -> list[dict]:
    subset = df.reindex(columns=columns)
    return [
        {column: _python_value(value, column, dates_as_text) for column, value in zip(columns, row)}
        for row in subset.itertuples(index=False, name=None)
    ]


def upsert(conn: Connection, table: str, df: pd.DataFrame, dates_as_text: bool = False) -> int:
    spec = TABLES[table]
    sql = text(build_upsert_sql(table, spec["columns"], spec["key"]))
    records = dataframe_to_records(df, spec["columns"], dates_as_text)
    for start in range(0, len(records), BATCH_SIZE):
        conn.execute(sql, records[start:start + BATCH_SIZE])
    return len(records)


def read_processed(processed_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the transform output with the right data types."""
    customers = pd.read_csv(processed_dir / "customers_clean.csv", dtype={"customer_id": str})
    products = pd.read_csv(processed_dir / "products_clean.csv")
    sales = pd.read_csv(processed_dir / "sales_clean.csv",
                        dtype={"customer_id": str, "transaction_id": str, "branch_id": str})
    for frame, column in ((customers, "is_placeholder"), (products, "is_placeholder")):
        frame[column] = frame[column].astype(str).str.lower().eq("true")
    products["product_id"] = products["product_id"].astype(int)
    sales["product_id"] = sales["product_id"].astype(int)
    return customers, products, sales


def load_all(engine: Engine, customers: pd.DataFrame, products: pd.DataFrame, sales: pd.DataFrame) -> dict:
    """Create tables if needed, then upsert all three tables in ONE transaction."""
    create_tables(engine)
    dates_as_text = engine.dialect.name == "sqlite"
    try:
        with engine.begin() as conn:
            before = int(conn.execute(text("SELECT COUNT(*) FROM sales_transactions")).scalar())
            customers_n = upsert(conn, "customers", customers, dates_as_text)
            products_n = upsert(conn, "products", products, dates_as_text)
            sales_n = upsert(conn, "sales_transactions", sales, dates_as_text)
            after = int(conn.execute(text("SELECT COUNT(*) FROM sales_transactions")).scalar())
    except SQLAlchemyError as exc:
        # Nothing was saved: engine.begin() already rolled everything back.
        raise DatabaseError(f"Load failed and was rolled back: {getattr(exc, 'orig', exc)}") from exc

    result = {
        "customers_upserted": customers_n,
        "products_upserted": products_n,
        "sales_rows_upserted": sales_n,
        "sales_new_rows": after - before,
        "sales_rows_updated": sales_n - (after - before),
        "table_counts": table_counts(engine),
    }
    logger.info("Load committed: %d sales rows (%d new, %d updated)",
                sales_n, result["sales_new_rows"], result["sales_rows_updated"])
    return result


def load_processed_files(engine: Engine, processed_dir: Path) -> dict:
    customers, products, sales = read_processed(processed_dir)
    return load_all(engine, customers, products, sales)


def write_etl_log(engine: Engine, record: dict) -> None:
    """Insert or update one row in etl_logs (one row per run ID)."""
    columns = ["execution_id", "records_extracted", "records_transformed", "records_loaded",
               "records_rejected", "execution_status", "error_message", "run_source"]
    sql = build_upsert_sql("etl_logs", columns, ["execution_id"]).replace(
        "updated_at = CURRENT_TIMESTAMP", "execution_timestamp = CURRENT_TIMESTAMP")
    create_tables(engine)
    with engine.begin() as conn:
        conn.execute(text(sql), {column: record.get(column) for column in columns})
    logger.info("etl_logs updated for run %s: %s", record.get("execution_id"), record.get("execution_status"))
