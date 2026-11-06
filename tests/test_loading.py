"""Tests for loading into the database: inserts, keys, idempotency, rollback, logs."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("sqlalchemy")  # loading tests need SQLAlchemy (pip install -r requirements.txt)

from src.loading.load_data import build_upsert_sql, dataframe_to_records  # noqa: E402

# ------------------------------------------------ pure functions (no DB) ----


def test_upsert_sql_updates_non_key_columns_only():
    sql = build_upsert_sql("products", ["product_id", "product_name", "category"], ["product_id"])
    assert sql.startswith("INSERT INTO products (product_id, product_name, category)")
    assert "ON CONFLICT (product_id) DO UPDATE SET" in sql
    assert "product_name = EXCLUDED.product_name" in sql
    assert "product_id = EXCLUDED" not in sql


def test_records_convert_numpy_and_missing_values():
    df = pd.DataFrame({"product_id": np.array([1], dtype="int64"), "unit_price": [np.nan],
                       "is_placeholder": np.array([True]), "registration_date": ["2025-03-05"]})
    record = dataframe_to_records(df, ["product_id", "unit_price", "is_placeholder", "registration_date"])[0]
    assert record["product_id"] == 1 and type(record["product_id"]) is int
    assert record["unit_price"] is None
    assert record["is_placeholder"] is True
    assert str(record["registration_date"]) == "2025-03-05"


# ------------------------------------------------------- database tests ----

def sample_tables():
    customers = pd.DataFrame({
        "customer_id": ["C0001", "UNKNOWN"], "customer_name": ["Asha", "Unknown Customer"],
        "email": ["a@x.com", None], "city": ["Patna", None], "state": ["Bihar", None],
        "registration_date": ["2022-01-05", None], "is_placeholder": [False, True]})
    products = pd.DataFrame({
        "product_id": [1, 2], "product_name": ["Mascara", "Palette"], "category": ["Beauty", "Beauty"],
        "unit_price": [849.15, None], "description": ["x", None], "is_placeholder": [False, True]})
    sales = pd.DataFrame({
        "branch_id": ["B1", "B2"], "transaction_id": ["T00001", "T00001"],   # same ID, two branches
        "customer_id": ["C0001", "UNKNOWN"], "product_id": [1, 2],
        "transaction_date": ["2025-03-05", "2025-03-06"], "quantity": [2, 1],
        "unit_price": [100.0, 200.0], "discount": [0.1, 0.0], "total_amount": [200.0, 200.0],
        "discount_amount": [20.0, 0.0], "final_amount": [180.0, 200.0], "region": ["East", "North"],
        "payment_method": ["UPI", "Cash"], "transaction_year": [2025, 2025], "transaction_month": [3, 3],
        "transaction_quarter": [1, 1], "source_file": ["a.csv", "b.csv"]})
    return customers, products, sales


def count(engine, table):
    from sqlalchemy import text
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()


def test_load_inserts_all_tables(engine):
    from src.loading.load_data import load_all
    result = load_all(engine, *sample_tables())
    assert result["sales_new_rows"] == 2
    assert count(engine, "customers") == 2 and count(engine, "products") == 2
    assert count(engine, "sales_transactions") == 2


def test_load_is_idempotent(engine):
    """Running the same load twice must not duplicate anything."""
    from src.loading.load_data import load_all
    load_all(engine, *sample_tables())
    second = load_all(engine, *sample_tables())
    assert second["sales_new_rows"] == 0
    assert second["sales_rows_updated"] == 2
    assert count(engine, "sales_transactions") == 2


def test_upsert_updates_changed_values(engine):
    from sqlalchemy import text

    from src.loading.load_data import load_all
    customers, products, sales = sample_tables()
    load_all(engine, customers, products, sales)
    sales.loc[0, "quantity"] = 5
    load_all(engine, customers, products, sales)
    with engine.connect() as conn:
        qty = conn.execute(text("SELECT quantity FROM sales_transactions WHERE branch_id='B1'")).scalar()
    assert qty == 5


def test_failed_load_rolls_back_everything(engine):
    """A sale pointing to a product that does not exist breaks the foreign key.
    The customers and products written earlier in the same transaction must vanish too."""
    from src.exceptions import DatabaseError
    from src.loading.load_data import load_all
    customers, products, sales = sample_tables()
    sales.loc[1, "product_id"] = 999
    with pytest.raises(DatabaseError, match="rolled back"):
        load_all(engine, customers, products, sales)
    assert count(engine, "customers") == 0
    assert count(engine, "products") == 0
    assert count(engine, "sales_transactions") == 0


def test_etl_log_is_written_once_per_run(engine):
    from sqlalchemy import text

    from src.loading.load_data import write_etl_log
    record = {"execution_id": "run-1", "records_extracted": 10, "records_transformed": 8,
              "records_loaded": 8, "records_rejected": 2, "execution_status": "FAILED",
              "error_message": "boom", "run_source": "cli"}
    write_etl_log(engine, record)
    write_etl_log(engine, {**record, "execution_status": "SUCCESS", "error_message": None})
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT execution_status FROM etl_logs")).fetchall()
    assert [tuple(row) for row in rows] == [("SUCCESS",)]
