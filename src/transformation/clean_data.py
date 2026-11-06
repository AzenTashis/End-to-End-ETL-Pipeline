"""
Cleaning and standardization: turning messy text into consistent values.

Each function does ONE small job, so it is easy to test and to explain.

Conventions decided here (documented in README):
* Text: trimmed, inner spaces collapsed ("  Red   Lipstick " -> "Red Lipstick").
* Categories: Title Case canonical names ("ELECTRONICS " -> "Electronics").
* Regions: one of East, North, South, West.
* Payment methods: UPI, Credit Card, Debit Card, Cash, Net Banking, Wallet, Unknown.
* Dates: real date values. Each branch has its own expected format.
* Discount: a DECIMAL FRACTION between 0 and 1. 0.10 means 10 percent.
  Branch 2 writes "10" for 10 percent, so values above 1 (up to 100) are
  divided by 100. Missing discount means "no discount" (0).
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from config.config import UNKNOWN_CUSTOMER_ID

# ---------------------------------------------------------------- text ----

def is_missing(value) -> bool:
    """True for None, NaN, pd.NA and similar 'empty' markers."""
    if value is None:
        return True
    if isinstance(value, str):
        return False
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def clean_text(series: pd.Series) -> pd.Series:
    """Trim spaces and collapse repeated inner spaces. Blank becomes missing (None)."""
    values = []
    for value in series:
        if is_missing(value):
            values.append(None)
            continue
        text = re.sub(r"\s+", " ", str(value)).strip()
        values.append(text if text and text.lower() not in ("nan", "none") else None)
    return pd.Series(values, index=series.index, dtype="object")


def apply_text(series: pd.Series, func) -> pd.Series:
    """Apply func to every non-missing value; missing stays None. Keeps dtype 'object'."""
    return pd.Series([None if is_missing(v) else func(v) for v in series],
                     index=series.index, dtype="object")


def title_case(value: str | None) -> str | None:
    if is_missing(value):
        return None
    return " ".join(word.capitalize() for word in value.split(" "))


# ---------------------------------------------------------- categories ----

# Synonyms are written in "normalized" form: lower case, spaces only.
CATEGORY_SYNONYMS = {
    "smart phones": "smartphones",
    "mobile phones": "smartphones",
    "phones": "smartphones",
    "grocery": "groceries",
    "perfume": "fragrances",
    "perfumes": "fragrances",
    "makeup": "beauty",
    "make up": "beauty",
    "cosmetics": "beauty",
    "furnitures": "furniture",
    "home decor": "home decoration",
    "laptop": "laptops",
    "notebooks": "laptops",
    "kitchen": "kitchen accessories",
}


def normalize_category(value) -> str | None:
    """'HOME_DECORATION', 'home decor', 'home-decoration' -> 'Home Decoration'."""
    if is_missing(value):
        return None
    text = re.sub(r"[-_]+", " ", str(value)).lower()
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    text = CATEGORY_SYNONYMS.get(text, text)
    return title_case(text)


# -------------------------------------------------------------- region ----

REGION_MAP = {
    "east": "East", "e": "East", "eastern": "East",
    "north": "North", "n": "North", "northern": "North",
    "south": "South", "s": "South", "southern": "South",
    "west": "West", "w": "West", "western": "West",
}


def normalize_region(value) -> str | None:
    if is_missing(value):
        return None
    return REGION_MAP.get(str(value).strip().lower())


# ------------------------------------------------------------- payment ----

PAYMENT_MAP = {
    "upi": "UPI", "u.p.i": "UPI", "gpay": "UPI", "google pay": "UPI", "phonepe": "UPI",
    "credit card": "Credit Card", "creditcard": "Credit Card", "cc": "Credit Card",
    "debit card": "Debit Card", "debitcard": "Debit Card", "dc": "Debit Card",
    "cash": "Cash", "cod": "Cash", "cash on delivery": "Cash",
    "net banking": "Net Banking", "netbanking": "Net Banking", "net-banking": "Net Banking",
    "wallet": "Wallet", "paytm": "Wallet", "paytm wallet": "Wallet",
}


def normalize_payment(value) -> str:
    """Unknown or missing payment methods become 'Unknown' (non-critical field)."""
    if is_missing(value):
        return "Unknown"
    key = re.sub(r"\s+", " ", str(value)).strip().lower()
    return PAYMENT_MAP.get(key, "Unknown")


# --------------------------------------------------------------- dates ----

# Unambiguous formats we also accept, whatever the branch.
FALLBACK_DATE_FORMATS = ["%d %b %Y", "%d-%b-%Y", "%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y"]


def parse_dates(series: pd.Series, primary_format: str) -> pd.Series:
    """Parse text dates. Try the branch's own format first, then safe fallbacks.

    Anything that still cannot be read becomes NaT ("not a time"), which the
    validation step will reject. We never guess between DD/MM and MM/DD.
    """
    text = clean_text(series)
    result = pd.to_datetime(text, format=primary_format, errors="coerce")
    for fmt in FALLBACK_DATE_FORMATS:
        if fmt == primary_format:
            continue
        still_missing = result.isna() & text.notna()
        if not still_missing.any():
            break
        result = result.where(~still_missing, pd.to_datetime(text, format=fmt, errors="coerce"))
    return result


# ------------------------------------------------------------- numbers ----

def parse_number(series: pd.Series) -> pd.Series:
    """'₹1,099.50' -> 1099.5 ; 'abc' -> NaN (invalid, rejected later)."""
    text = clean_text(series)
    text = apply_text(text, lambda v: re.sub(r"(₹|rs\.?|inr|,|\s)", "", v, flags=re.IGNORECASE))
    return pd.to_numeric(text, errors="coerce").astype("float64")


def normalize_discount(series: pd.Series) -> pd.Series:
    """Return discounts as fractions. Missing -> 0. 10 -> 0.10. Invalid stays out of range."""
    numbers = parse_number(series).fillna(0.0)
    as_fraction = numbers.where(~((numbers > 1) & (numbers <= 100)), numbers / 100)
    return as_fraction.round(4)


# ----------------------------------------------------------- identifiers ----

CUSTOMER_ID_PATTERN = re.compile(r"^C\d{4,}$")


def normalize_customer_id(value) -> str | None:
    """' c0042 ' -> 'C0042'. Malformed IDs are kept as typed (validation rejects them)."""
    if is_missing(value):
        return None
    text = str(value).strip().upper()
    return text or None


def normalize_product_id(series: pd.Series) -> pd.Series:
    """'17' -> 17. Non-whole or non-numeric IDs become missing."""
    numbers = parse_number(series)
    whole = numbers.where(numbers.notna() & (numbers == numbers.round()) & (numbers > 0))
    return whole.astype("Int64")


# ---------------------------------------------------- full table cleaning ----

def clean_sales(raw: pd.DataFrame, branches: dict) -> pd.DataFrame:
    """Apply every cleaning rule to the combined raw sales table.

    Input columns are all text. Output columns have proper types.
    The raw text of the date and price is kept (columns *_raw) so a rejected
    row still shows what the branch actually sent.
    """
    df = pd.DataFrame(index=raw.index)
    df["branch_id"] = raw["branch_id"]
    df["source_file"] = raw["source_file"]
    df["source_row_number"] = raw["source_row_number"].astype(int)

    df["transaction_id"] = apply_text(clean_text(raw["transaction_id"]), str.upper)
    df["customer_id"] = apply_text(clean_text(raw["customer_id"]), normalize_customer_id)
    df["product_id"] = normalize_product_id(raw["product_id"])
    df["product_name"] = apply_text(clean_text(raw["product_name"]), title_case)
    df["category"] = apply_text(clean_text(raw["category"]), normalize_category)

    # Dates: each branch has its own format.
    df["transaction_date_raw"] = raw["transaction_date"]
    parsed = pd.Series(pd.NaT, index=raw.index, dtype="datetime64[ns]")
    for branch_id, branch in branches.items():
        mask = raw["branch_id"] == branch_id
        if mask.any():
            parsed.loc[mask] = parse_dates(raw.loc[mask, "transaction_date"], branch["date_format"])
    df["transaction_date"] = parsed

    df["quantity"] = parse_number(raw["quantity"])
    df["unit_price_raw"] = raw["unit_price"]
    df["unit_price"] = parse_number(raw["unit_price"]).round(2)
    df["discount"] = normalize_discount(raw["discount"])

    # Region: if missing or unreadable, use the branch's home region (non-critical).
    regions = apply_text(clean_text(raw["region"]), normalize_region)
    default_regions = raw["branch_id"].map({key: value["default_region"] for key, value in branches.items()})
    df["region"] = regions.where(regions.notna(), default_regions)

    df["payment_method"] = [normalize_payment(v) for v in clean_text(raw["payment_method"])]
    return df


def fill_missing_customer(df: pd.DataFrame) -> pd.DataFrame:
    """A sale with no customer ID still happened, so we keep its revenue and
    assign it to the placeholder customer 'UNKNOWN'."""
    df = df.copy()
    df["customer_id_missing"] = df["customer_id"].isna()
    df["customer_id"] = df["customer_id"].where(df["customer_id"].notna(), UNKNOWN_CUSTOMER_ID)
    return df


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean_customers(raw: pd.DataFrame) -> pd.DataFrame:
    """Clean the customer file. Duplicates are handled in transform_data."""
    df = pd.DataFrame(index=raw.index)
    df["source_row_number"] = raw["source_row_number"].astype(int)
    df["customer_id"] = apply_text(clean_text(raw["customer_id"]), normalize_customer_id)
    df["customer_name"] = apply_text(clean_text(raw["customer_name"]), title_case)
    emails = apply_text(clean_text(raw["email"]), str.lower)
    df["email"] = apply_text(emails, lambda v: v if EMAIL_PATTERN.match(v) else None)
    df["email_was_invalid"] = emails.notna() & df["email"].isna()
    df["city"] = apply_text(clean_text(raw["city"]), title_case)
    df["state"] = apply_text(clean_text(raw["state"]), title_case)
    dates = parse_dates(raw["registration_date"], "%Y-%m-%d")
    retry = pd.to_datetime(clean_text(raw["registration_date"]), format="%d/%m/%Y", errors="coerce")
    df["registration_date"] = dates.where(dates.notna(), retry)
    return df


def clean_products(raw: pd.DataFrame, price_to_inr: float) -> pd.DataFrame:
    """Clean the API product table and convert prices from USD to INR."""
    df = pd.DataFrame(index=raw.index)
    df["product_id"] = normalize_product_id(raw["id"].astype(str))
    df["product_name"] = clean_text(raw["title"].astype("object"))
    df["category"] = apply_text(raw["category"], normalize_category)
    prices = parse_number(raw["price"].astype(str))
    df["unit_price"] = (prices * price_to_inr).round(2)
    df.loc[df["unit_price"] <= 0, "unit_price"] = np.nan
    df["description"] = clean_text(raw["description"].astype("object"))
    df = df[df["product_id"].notna()]
    return df.drop_duplicates(subset=["product_id"], keep="first").reset_index(drop=True)
