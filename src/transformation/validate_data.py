"""
Validation rules: decide which rows are safe to load.

How it works
------------
Every rule is a small function that returns True for rows that BREAK the
rule. A row can break several rules; all reasons are recorded, for example:
    "negative or zero quantity; invalid unit price"

Rows that break at least one rule go to data/rejected/ with that reason.
Nothing is silently deleted, so someone can investigate later.
"""

from __future__ import annotations

from datetime import date
from typing import Callable

import pandas as pd

from config.config import UNKNOWN_CUSTOMER_ID
from src.transformation.clean_data import CUSTOMER_ID_PATTERN

Rule = tuple[str, Callable[[pd.DataFrame], pd.Series]]

# Business decision: we only accept sales after the company started trading.
EARLIEST_VALID_DATE = pd.Timestamp("2015-01-01")


def sales_rules(today: date) -> list[Rule]:
    today_ts = pd.Timestamp(today)
    return [
        ("missing transaction id",
         lambda d: d["transaction_id"].isna()),
        ("missing or invalid product id",
         lambda d: d["product_id"].isna()),
        ("invalid customer id format",
         lambda d: (d["customer_id"] != UNKNOWN_CUSTOMER_ID)
         & ~d["customer_id"].astype(str).str.match(CUSTOMER_ID_PATTERN)),
        ("invalid or unreadable transaction date",
         lambda d: d["transaction_date"].isna()),
        ("transaction date in the future",
         lambda d: d["transaction_date"].notna() & (d["transaction_date"] > today_ts)),
        ("transaction date too old",
         lambda d: d["transaction_date"].notna() & (d["transaction_date"] < EARLIEST_VALID_DATE)),
        ("missing or non-numeric quantity",
         lambda d: d["quantity"].isna()),
        ("negative or zero quantity",
         lambda d: d["quantity"].notna() & (d["quantity"] <= 0)),
        ("quantity is not a whole number",
         lambda d: d["quantity"].notna() & (d["quantity"] != d["quantity"].round())),
        ("invalid unit price (missing, text, zero or negative)",
         lambda d: d["unit_price"].isna() | (d["unit_price"] <= 0)),
        ("discount outside 0 to 100 percent",
         lambda d: (d["discount"] < 0) | (d["discount"] >= 1)),
    ]


def apply_rules(df: pd.DataFrame, rules: list[Rule]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Split df into (valid_rows, rejected_rows, reason_counts)."""
    reasons = pd.Series([[] for _ in range(len(df))], index=df.index, dtype="object")
    reason_counts: dict[str, int] = {}
    for reason, rule in rules:
        broken = rule(df).fillna(False).astype(bool)
        count = int(broken.sum())
        if count:
            reason_counts[reason] = count
            for index in df.index[broken]:
                reasons.at[index].append(reason)

    has_problem = reasons.map(bool)
    rejected = df[has_problem].copy()
    rejected["rejection_reason"] = reasons[has_problem].map("; ".join)
    valid = df[~has_problem].copy()
    return valid, rejected, reason_counts


def validate_sales(df: pd.DataFrame, today: date | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    valid, rejected, counts = apply_rules(df, sales_rules(today or date.today()))
    if not valid.empty:
        valid["quantity"] = valid["quantity"].astype(int)
    return valid, rejected, counts


def customer_rules() -> list[Rule]:
    return [
        ("missing customer id", lambda d: d["customer_id"].isna()),
        ("invalid customer id format",
         lambda d: d["customer_id"].notna() & ~d["customer_id"].astype(str).str.match(CUSTOMER_ID_PATTERN)),
    ]


def validate_customers(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    return apply_rules(df, customer_rules())
