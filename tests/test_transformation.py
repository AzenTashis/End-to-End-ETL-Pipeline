"""Tests for cleaning, missing values, duplicates, validation, joins and derived columns."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from config.config import BRANCHES, UNKNOWN_CUSTOMER_ID
from src.transformation.clean_data import (
    clean_customers,
    clean_sales,
    clean_text,
    fill_missing_customer,
    normalize_category,
    normalize_discount,
    normalize_payment,
    normalize_region,
    parse_dates,
    parse_number,
)
from src.transformation.transform_data import (
    add_derived_columns,
    deduplicate_customers,
    integrate,
    remove_duplicate_sales,
    run_transformation,
)
from src.transformation.validate_data import validate_sales


def raw_sales(rows: list[dict]) -> pd.DataFrame:
    """Build a raw sales table (all text) with sensible defaults."""
    base = {"transaction_id": "T00001", "transaction_date": "05-03-2025", "customer_id": "C0001",
            "product_id": "1", "product_name": "Mascara", "category": "beauty", "quantity": "2",
            "unit_price": "100", "discount": "0.1", "region": "East", "payment_method": "UPI",
            "branch_id": "B1", "source_file": "sales_branch_1.csv"}
    frame = pd.DataFrame([{**base, **row} for row in rows])
    frame["source_row_number"] = range(2, len(frame) + 2)
    return frame


def cleaned(rows):
    return fill_missing_customer(clean_sales(raw_sales(rows), BRANCHES))


# -------------------------------------------------------- standardization ----

def test_clean_text_trims_and_collapses_spaces():
    result = clean_text(pd.Series(["  Red   Lipstick ", "", None, "ok"]))
    assert list(result) == ["Red Lipstick", None, None, "ok"]


@pytest.mark.parametrize("raw, expected", [
    ("ELECTRONICS ", "Electronics"), ("home-decoration", "Home Decoration"),
    ("HOME_DECORATION", "Home Decoration"), ("home decor", "Home Decoration"),
    ("smart phones", "Smartphones"), ("Perfumes", "Fragrances"), ("grocery", "Groceries"),
])
def test_category_standardization(raw, expected):
    assert normalize_category(raw) == expected


@pytest.mark.parametrize("raw, expected", [("east ", "East"), ("E", "East"), ("Northern", "North"),
                                           ("SOUTH", "South"), ("w", "West"), ("Mars", None)])
def test_region_normalization(raw, expected):
    assert normalize_region(raw) == expected


@pytest.mark.parametrize("raw, expected", [("upi", "UPI"), ("gpay", "UPI"), ("CC", "Credit Card"),
                                           ("cod", "Cash"), ("netbanking", "Net Banking"),
                                           (None, "Unknown"), ("barter", "Unknown")])
def test_payment_normalization(raw, expected):
    assert normalize_payment(raw) == expected


def test_parse_number_handles_currency_and_text():
    result = parse_number(pd.Series(["₹1,099.50", "250", "abc", None]))
    assert result.iloc[0] == 1099.5 and result.iloc[1] == 250
    assert np.isnan(result.iloc[2]) and np.isnan(result.iloc[3])


def test_discount_convention_is_decimal_fraction():
    result = normalize_discount(pd.Series(["10", "0.1", "", "150", "-5"]))
    assert list(result[:3]) == [0.10, 0.10, 0.0]     # percent, fraction, missing -> 0
    assert result.iloc[3] == 150                      # above 100: invalid, rejected later
    assert result.iloc[4] == -5


def test_each_branch_date_format_gives_same_day():
    b1 = parse_dates(pd.Series(["05-03-2025"]), BRANCHES["B1"]["date_format"])
    b2 = parse_dates(pd.Series(["2025-03-05"]), BRANCHES["B2"]["date_format"])
    b3 = parse_dates(pd.Series(["03/05/2025"]), BRANCHES["B3"]["date_format"])
    assert b1.iloc[0] == b2.iloc[0] == b3.iloc[0] == pd.Timestamp("2025-03-05")


def test_date_fallback_and_invalid_dates():
    result = parse_dates(pd.Series(["05 Mar 2025", "31-02-2025", "N/A"]), "%d-%m-%Y")
    assert result.iloc[0] == pd.Timestamp("2025-03-05")
    assert result.iloc[1:].isna().all()


# --------------------------------------------------------- missing values ----

def test_missing_customer_becomes_unknown_placeholder():
    df = cleaned([{"customer_id": ""}, {"customer_id": " c0042 ", "transaction_id": "T2"}])
    assert df["customer_id"].tolist() == [UNKNOWN_CUSTOMER_ID, "C0042"]
    assert df["customer_id_missing"].tolist() == [True, False]


def test_missing_region_uses_branch_home_region_and_payment_unknown():
    df = cleaned([{"region": "", "payment_method": ""}])
    assert df.loc[0, "region"] == "East"
    assert df.loc[0, "payment_method"] == "Unknown"


# ---------------------------------------------------------- duplicates ----

def test_exact_duplicates_removed_conflicts_rejected_cross_branch_kept():
    df = cleaned([
        {"transaction_id": "T1"},
        {"transaction_id": " t1 "},                       # exact duplicate after cleaning
        {"transaction_id": "T1", "quantity": "7"},        # same ID, different quantity
        {"transaction_id": "T1", "branch_id": "B2", "transaction_date": "2025-03-05"},  # other branch
    ])
    kept, exact, conflicts = remove_duplicate_sales(df)
    assert len(exact) == 1
    assert len(conflicts) == 1 and conflicts.iloc[0]["quantity"] == 7
    assert sorted(kept["branch_id"]) == ["B1", "B2"]   # both T1 sales are legitimate


# ---------------------------------------------------------- validation ----

def test_validation_rejects_bad_rows_with_reasons():
    df = cleaned([
        {"transaction_id": "OK"},
        {"transaction_id": "NEG", "quantity": "-2"},
        {"transaction_id": "ZERO", "unit_price": "0"},
        {"transaction_id": "TEXT", "unit_price": "abc"},
        {"transaction_id": "DATE", "transaction_date": "31-02-2025"},
        {"transaction_id": "FUT", "transaction_date": "01-01-2030"},
        {"transaction_id": "CUST", "customer_id": "CUST-??"},
        {"transaction_id": "DISC", "discount": "150"},
        {"transaction_id": "PROD", "product_id": "abc"},
        {"transaction_id": "MULTI", "quantity": "0", "unit_price": "-1"},
    ])
    valid, rejected, counts = validate_sales(df, today=date(2026, 11, 7))
    assert valid["transaction_id"].tolist() == ["OK"]
    reasons = dict(zip(rejected["transaction_id"], rejected["rejection_reason"]))
    assert "negative or zero quantity" in reasons["NEG"]
    assert "invalid unit price" in reasons["ZERO"] and "invalid unit price" in reasons["TEXT"]
    assert "invalid or unreadable transaction date" in reasons["DATE"]
    assert "future" in reasons["FUT"]
    assert "invalid customer id format" in reasons["CUST"]
    assert "discount" in reasons["DISC"]
    assert "product id" in reasons["PROD"]
    assert reasons["MULTI"].count(";") == 1          # two reasons recorded
    assert counts["negative or zero quantity"] == 2


# ----------------------------------------------------- integration (joins) ----

def _products():
    return pd.DataFrame({"product_id": [1, 2], "product_name": ["Essence Mascara", "Palette"],
                         "category": ["Beauty", "Beauty"], "unit_price": [850.0, 1700.0],
                         "description": ["a", "b"]})


def _customers():
    return pd.DataFrame({"customer_id": ["C0001"], "customer_name": ["Asha"], "email": [None],
                         "city": ["Patna"], "state": ["Bihar"], "registration_date": [pd.NaT]})


def test_left_join_keeps_unmatched_sales_and_creates_placeholders():
    df = cleaned([
        {"transaction_id": "A", "product_name": ""},                    # matched, name from API
        {"transaction_id": "B", "customer_id": "C0999"},               # unknown customer
        {"transaction_id": "C", "product_id": "9001", "product_name": "Smart Watch", "category": "electronics"},
        {"transaction_id": "D", "customer_id": ""},                    # no customer at all
    ])
    valid, _, _ = validate_sales(df, today=date(2026, 11, 7))
    sales, customer_dim, product_dim, stats = integrate(valid, _customers(), _products())

    assert len(sales) == 4                                     # nothing silently lost
    assert sales.set_index("transaction_id").loc["A", "product_name"] == "Essence Mascara"
    assert stats["unmatched_customer_records"] == 1
    assert stats["missing_customer_id_records"] == 1
    assert stats["unmatched_product_records"] == 1
    assert {"C0999", UNKNOWN_CUSTOMER_ID} <= set(customer_dim["customer_id"])
    placeholder = product_dim.set_index("product_id").loc[9001]
    assert placeholder["is_placeholder"] and placeholder["category"] == "Electronics"


# ------------------------------------------------------- derived columns ----

def test_derived_columns_math():
    df = pd.DataFrame({"quantity": [2, 3], "unit_price": [100.0, 33.33], "discount": [0.1, 0.0],
                       "transaction_date": pd.to_datetime(["2025-03-05", "2025-11-20"])})
    out = add_derived_columns(df)
    assert out["total_amount"].tolist() == [200.0, 99.99]
    assert out["discount_amount"].tolist() == [20.0, 0.0]
    assert out["final_amount"].tolist() == [180.0, 99.99]
    assert out["transaction_quarter"].tolist() == [1, 4]
    assert out["transaction_month"].tolist() == [3, 11]


# ------------------------------------------------------------- customers ----

def test_customer_cleaning_and_dedup_keeps_latest():
    raw = pd.DataFrame({
        "customer_id": ["C0001", "C0001", "C0001", "c0002"],
        "customer_name": ["asha rao", "asha rao", "Asha Rao", " RAVI  JHA "],
        "email": ["a@x.com", "a@x.com", "a@x.com", "ravi@"],
        "city": ["Patna", "Patna", "Gaya", "Delhi"],
        "state": ["Bihar"] * 3 + ["Delhi"],
        "registration_date": ["2022-01-05", "2022-01-05", "05/01/2022", "2021-01-01"],
        "source_row_number": [2, 3, 4, 5],
    })
    customers = clean_customers(raw)
    assert customers.loc[3, "customer_name"] == "Ravi Jha"
    assert customers.loc[3, "email"] is None and customers.loc[3, "email_was_invalid"]
    unique, exact, by_id = deduplicate_customers(customers)
    assert exact == 1 and by_id == 1
    assert unique.set_index("customer_id").loc["C0001", "city"] == "Gaya"   # last record wins


# ----------------------------------------------------- whole transform ----

def test_run_transformation_accounts_for_every_row(data_root):
    from scripts.generate_data import main as generate
    from src.extraction.extract_api import extract_products
    from src.extraction.extract_csv import extract_sales
    from src.extraction.extract_customers import extract_customers

    source = data_root / "data" / "source"
    generate(["--rows-per-branch", "300", "--customers", "60", "--offline", "--output", str(source)])
    raw = data_root / "raw"
    extract_sales(source, raw)
    extract_customers(source, raw)
    extract_products(raw)
    metrics = run_transformation(raw, data_root / "processed", data_root / "rejected", today=date(2026, 11, 7))

    # Every extracted row is either processed, rejected, or a removed exact duplicate.
    assert metrics["records_extracted"] == (metrics["records_processed"] + metrics["records_rejected"]
                                            + metrics["exact_duplicates_removed"])
    assert metrics["records_rejected"] > 0 and metrics["exact_duplicates_removed"] > 0
    clean = pd.read_csv(data_root / "processed" / "sales_clean.csv")
    assert (clean["quantity"] > 0).all() and (clean["unit_price"] > 0).all()
    assert clean["discount"].between(0, 0.9999).all()
    assert set(clean["region"]) <= {"East", "North", "South", "West"}
    assert (data_root / "rejected" / "rejected_sales.csv").exists()
