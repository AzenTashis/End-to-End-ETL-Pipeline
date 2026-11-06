"""
Transformation: duplicates, integration (joins), derived columns, and the
function that runs the whole transform stage.

Order of operations (and why)
-----------------------------
1. Clean       : fix text, dates, numbers first, so " T0001" and "T0001"
                 are recognised as the same value.
2. Deduplicate : remove exact copies; flag same-ID-different-content rows.
3. Validate    : reject rows that are unsafe to load, with a reason.
4. Integrate   : LEFT JOIN with customers and products.
                 LEFT JOIN means "keep every sale, attach customer/product
                 details if we find them". An INNER JOIN would silently drop
                 sales whose customer is unknown, and we would lose revenue.
5. Derive      : totals, discount amounts, year/month/quarter.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from config.config import BRANCHES, UNKNOWN_CUSTOMER_ID, get_settings
from src.monitoring.logger import get_logger
from src.transformation.clean_data import (
    clean_customers,
    clean_products,
    clean_sales,
    fill_missing_customer,
)
from src.transformation.validate_data import validate_customers, validate_sales

logger = get_logger(__name__)

# Columns that describe a sale. Two rows equal on all of these are exact duplicates.
SALE_VALUE_COLUMNS = [
    "branch_id", "transaction_id", "transaction_date", "customer_id", "product_id",
    "product_name", "category", "quantity", "unit_price", "discount", "region", "payment_method",
]
BUSINESS_KEY = ["branch_id", "transaction_id"]

SALES_OUTPUT_COLUMNS = [
    "branch_id", "transaction_id", "customer_id", "product_id", "transaction_date",
    "quantity", "unit_price", "discount", "total_amount", "discount_amount", "final_amount",
    "region", "payment_method", "transaction_year", "transaction_month", "transaction_quarter",
    "product_name", "category", "customer_matched", "product_matched", "source_file",
]
CUSTOMER_OUTPUT_COLUMNS = [
    "customer_id", "customer_name", "email", "city", "state", "registration_date", "is_placeholder",
]
PRODUCT_OUTPUT_COLUMNS = [
    "product_id", "product_name", "category", "unit_price", "description", "is_placeholder",
]


# ------------------------------------------------------------ duplicates ----

def remove_duplicate_sales(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (kept, exact_duplicates, conflicting_duplicates).

    * Exact duplicate: every business value is identical -> the same sale
      exported twice. Safe to drop.
    * Conflicting duplicate: same branch + transaction ID but different
      values (e.g. a different quantity). We cannot know which is correct,
      so we keep the FIRST row in the file and send the others to the
      rejected file for a human to check.
    * Same transaction ID in DIFFERENT branches is NOT a duplicate: each
      branch numbers its own sales. That is why the key is branch + ID.
    """
    ordered = df.sort_values(["branch_id", "source_row_number"])
    exact_mask = ordered.duplicated(subset=SALE_VALUE_COLUMNS, keep="first")
    exact = ordered[exact_mask]
    remaining = ordered[~exact_mask]

    has_id = remaining["transaction_id"].notna()
    conflict_mask = has_id & remaining.duplicated(subset=BUSINESS_KEY, keep="first")
    conflicts = remaining[conflict_mask].copy()
    conflicts["rejection_reason"] = "duplicate transaction id with conflicting values"
    kept = remaining[~conflict_mask]
    return kept.sort_index(), exact, conflicts


def deduplicate_customers(df: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    """Return (unique_customers, exact_duplicates, id_duplicates).

    If the same customer ID appears with different details, we keep the
    LAST row in the file, assuming it is the most recent update.
    """
    value_columns = ["customer_id", "customer_name", "email", "city", "state", "registration_date"]
    exact_mask = df.duplicated(subset=value_columns, keep="first")
    without_exact = df[~exact_mask]
    id_mask = without_exact.duplicated(subset=["customer_id"], keep="last")
    unique = without_exact[~id_mask]
    return unique.reset_index(drop=True), int(exact_mask.sum()), int(id_mask.sum())


# ----------------------------------------------------------- integration ----

def _most_common(series: pd.Series):
    values = series.dropna()
    return values.mode().iloc[0] if not values.empty else None


def integrate(sales: pd.DataFrame, customers: pd.DataFrame, products: pd.DataFrame
              ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Join sales with customers and products. Returns sales, customer dim, product dim, stats."""
    sales = sales.copy()
    known_customers = set(customers["customer_id"])
    known_products = set(products["product_id"].astype(int))

    sales["customer_matched"] = sales["customer_id"].isin(known_customers)
    sales["product_matched"] = sales["product_id"].astype(int).isin(known_products)

    # LEFT JOIN to products: bring in the official name and category.
    catalogue = products[["product_id", "product_name", "category"]].rename(
        columns={"product_name": "api_product_name", "category": "api_category"})
    sales["product_id"] = sales["product_id"].astype(int)
    catalogue["product_id"] = catalogue["product_id"].astype(int)
    sales = sales.merge(catalogue, on="product_id", how="left")

    # The API is the "master" for product details; the CSV is the backup.
    sales["product_name"] = sales["api_product_name"].where(sales["api_product_name"].notna(), sales["product_name"])
    sales["product_name"] = sales["product_name"].fillna("Unknown Product")
    sales["category"] = sales["api_category"].where(sales["api_category"].notna(), sales["category"])
    sales["category"] = sales["category"].fillna("Uncategorized")
    sales = sales.drop(columns=["api_product_name", "api_category"])

    # ---- customer dimension: real customers + placeholders so foreign keys hold ----
    unmatched_customer_ids = sorted(
        set(sales.loc[~sales["customer_matched"], "customer_id"]) - {UNKNOWN_CUSTOMER_ID})
    placeholders = pd.DataFrame({
        "customer_id": [UNKNOWN_CUSTOMER_ID] + unmatched_customer_ids,
        "customer_name": ["Unknown Customer"] * (1 + len(unmatched_customer_ids)),
        "is_placeholder": True,
    })
    real = customers.copy()
    real["customer_name"] = real["customer_name"].fillna("Unknown Customer")
    real["is_placeholder"] = False
    customer_dim = pd.concat([real, placeholders], ignore_index=True)

    # ---- product dimension: API products + placeholders for unknown IDs ----
    unmatched_products = sales[~sales["product_matched"]]
    product_placeholders = []
    for product_id, rows in unmatched_products.groupby("product_id"):
        product_placeholders.append({
            "product_id": int(product_id),
            "product_name": _most_common(rows["product_name"]) or "Unknown Product",
            "category": _most_common(rows["category"]) or "Uncategorized",
            "unit_price": np.nan,
            "description": "Not found in product API; details taken from branch sales files",
            "is_placeholder": True,
        })
    real_products = products.copy()
    real_products["is_placeholder"] = False
    product_dim = pd.concat([real_products, pd.DataFrame(product_placeholders)], ignore_index=True) \
        if product_placeholders else real_products

    stats = {
        "unmatched_customer_records": int((~sales["customer_matched"] & (sales["customer_id"] != UNKNOWN_CUSTOMER_ID)).sum()),
        "unmatched_customer_ids": unmatched_customer_ids,
        "missing_customer_id_records": int((sales["customer_id"] == UNKNOWN_CUSTOMER_ID).sum()),
        "unmatched_product_records": int((~sales["product_matched"]).sum()),
        "unmatched_product_ids": sorted(int(x) for x in unmatched_products["product_id"].unique()),
    }
    return sales, customer_dim, product_dim, stats


# --------------------------------------------------------- derived columns ----

def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """total = qty x price ; discount_amount = total x discount ; final = total - discount."""
    df = df.copy()
    df["total_amount"] = (df["quantity"] * df["unit_price"]).round(2)
    df["discount_amount"] = (df["total_amount"] * df["discount"]).round(2)
    df["final_amount"] = (df["total_amount"] - df["discount_amount"]).round(2)
    df["transaction_year"] = df["transaction_date"].dt.year.astype(int)
    df["transaction_month"] = df["transaction_date"].dt.month.astype(int)
    df["transaction_quarter"] = df["transaction_date"].dt.quarter.astype(int)
    return df


# ------------------------------------------------------------- reporting ----

def count_missing(raw: pd.DataFrame, columns: list[str]) -> dict:
    """Missing = empty cell or only spaces."""
    result = {}
    for column in columns:
        values = raw[column]
        blank = values.isna() | values.astype(str).str.strip().eq("")
        result[column] = int(blank.sum())
    return result


def _distinct(series: pd.Series) -> int:
    return int(series.dropna().astype(str).nunique())


# ------------------------------------------------------- full transform ----

def run_transformation(raw_dir: Path, processed_dir: Path, rejected_dir: Path,
                       today: date | None = None) -> dict:
    """Read raw files, transform them, write processed + rejected files, return metrics."""
    settings = get_settings()
    raw_sales = pd.read_csv(raw_dir / "sales_raw.csv", dtype=str)
    raw_customers = pd.read_csv(raw_dir / "customers_raw.csv", dtype=str)
    raw_products = pd.read_csv(raw_dir / "products_raw.csv", dtype=str)
    logger.info("Transforming %d sales, %d customers, %d products",
                len(raw_sales), len(raw_customers), len(raw_products))

    # ---- customers ----
    customers = clean_customers(raw_customers)
    customers_valid, customers_rejected, customer_reasons = validate_customers(customers)
    customers_unique, customer_exact_dups, customer_id_dups = deduplicate_customers(customers_valid)

    # ---- products ----
    products = clean_products(raw_products, settings.api_price_to_inr)

    # ---- sales ----
    sales = clean_sales(raw_sales, BRANCHES)
    sales = fill_missing_customer(sales)
    sales, exact_dups, conflicts = remove_duplicate_sales(sales)
    valid, rejected, reason_counts = validate_sales(sales, today)
    if not conflicts.empty:
        reason_counts["duplicate transaction id with conflicting values"] = int(len(conflicts))
    all_rejected = pd.concat([rejected, conflicts], ignore_index=True)

    if valid.empty:
        raise ValueError("No valid sales rows left after validation; refusing to continue")

    integrated, customer_dim, product_dim, join_stats = integrate(valid, customers_unique, products)
    final = add_derived_columns(integrated)

    # ---- write outputs ----
    processed_dir.mkdir(parents=True, exist_ok=True)
    rejected_dir.mkdir(parents=True, exist_ok=True)
    out = final[SALES_OUTPUT_COLUMNS].copy()
    out["transaction_date"] = out["transaction_date"].dt.strftime("%Y-%m-%d")
    out.to_csv(processed_dir / "sales_clean.csv", index=False)

    cust_out = customer_dim.reindex(columns=CUSTOMER_OUTPUT_COLUMNS)
    cust_out["registration_date"] = pd.to_datetime(cust_out["registration_date"]).dt.strftime("%Y-%m-%d")
    cust_out.to_csv(processed_dir / "customers_clean.csv", index=False)
    product_dim.reindex(columns=PRODUCT_OUTPUT_COLUMNS).to_csv(processed_dir / "products_clean.csv", index=False)

    rejected_columns = ["branch_id", "source_file", "source_row_number", "transaction_id",
                        "transaction_date_raw", "customer_id", "product_id", "product_name",
                        "quantity", "unit_price_raw", "discount", "region", "payment_method",
                        "rejection_reason"]
    all_rejected.reindex(columns=rejected_columns).to_csv(rejected_dir / "rejected_sales.csv", index=False)
    exact_dups.reindex(columns=["branch_id", "source_file", "source_row_number", "transaction_id"]) \
        .to_csv(rejected_dir / "duplicate_sales_removed.csv", index=False)
    customers_rejected.to_csv(rejected_dir / "rejected_customers.csv", index=False)

    # ---- metrics for the data quality report ----
    raw_columns = ["transaction_id", "transaction_date", "customer_id", "product_id", "product_name",
                   "category", "quantity", "unit_price", "discount", "region", "payment_method"]
    metrics = {
        "records_extracted": int(len(raw_sales)),
        "exact_duplicates_removed": int(len(exact_dups)),
        "conflicting_duplicates_rejected": int(len(conflicts)),
        "missing_values_in_raw_sales": count_missing(raw_sales, raw_columns),
        "records_rejected": int(len(all_rejected)),
        "rejection_reasons": dict(sorted(reason_counts.items(), key=lambda kv: -kv[1])),
        "records_processed": int(len(final)),
        **join_stats,
        "customers_extracted": int(len(raw_customers)),
        "customers_rejected": int(len(customers_rejected)),
        "customer_rejection_reasons": customer_reasons,
        "customer_exact_duplicates_removed": customer_exact_dups,
        "customer_id_duplicates_resolved": customer_id_dups,
        "invalid_emails_cleared": int(customers["email_was_invalid"].sum()),
        "customers_final": int(len(customers_unique)),
        "customer_placeholders_created": int(customer_dim["is_placeholder"].sum()),
        "products_extracted": int(len(raw_products)),
        "products_final": int(len(products)),
        "product_placeholders_created": int(product_dim["is_placeholder"].sum()),
        "raw_vs_clean": {
            "rows": [int(len(raw_sales)), int(len(final))],
            "distinct_category_spellings": [_distinct(raw_sales["category"]), _distinct(final["category"])],
            "distinct_region_spellings": [_distinct(raw_sales["region"]), _distinct(final["region"])],
            "distinct_payment_spellings": [_distinct(raw_sales["payment_method"]), _distinct(final["payment_method"])],
        },
        "total_final_revenue": round(float(final["final_amount"].sum()), 2),
    }
    (processed_dir / "transform_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    logger.info("Transform done: %d processed, %d rejected, %d exact duplicates removed",
                metrics["records_processed"], metrics["records_rejected"], metrics["exact_duplicates_removed"])
    return metrics
