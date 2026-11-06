"""
Generate a realistic (and deliberately messy) sales dataset for Meridian Retail.

Run from the project root:
    python scripts/generate_data.py                       # default size
    python scripts/generate_data.py --rows-per-branch 50000 --customers 5000
    python scripts/generate_data.py --offline             # never call the API

What gets created in data/source/:
    sales_branch_1.csv   Branch 1, East (Patna)       dates DD-MM-YYYY, discount 0.10
    sales_branch_2.csv   Branch 2, North (Delhi)      dates YYYY-MM-DD, discount 10 (percent)
    sales_branch_3.csv   Branch 3, South (Bengaluru)  dates MM/DD/YYYY, discount 0.10
    customers.csv        all customers (with duplicates and gaps)

Data quality problems are injected ON PURPOSE so the cleaning code has real
work to do: missing IDs, duplicates, bad dates, negative quantities, invalid
prices, messy categories, extra spaces, different date formats.

The random seed makes the output identical every time (reproducible).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.config import BRANCHES, CUSTOMERS_FILE_NAME, get_settings  # noqa: E402
from src.exceptions import APIExtractionError  # noqa: E402
from src.extraction.extract_api import fetch_all_products, load_snapshot, save_snapshot  # noqa: E402

FIRST_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Krishna", "Ishaan", "Rohan",
    "Ananya", "Diya", "Priya", "Aadhya", "Saanvi", "Isha", "Kavya", "Meera", "Riya", "Sneha",
    "Rahul", "Amit", "Neha", "Pooja", "Suresh", "Kiran", "Deepak", "Anjali", "Manish", "Shreya",
]
LAST_NAMES = [
    "Sharma", "Verma", "Kumar", "Singh", "Gupta", "Mishra", "Yadav", "Jha", "Reddy", "Nair",
    "Iyer", "Patel", "Das", "Sinha", "Chatterjee", "Rao", "Menon", "Pandey", "Joshi", "Mehta",
]
CITIES = [
    ("Patna", "Bihar"), ("Gaya", "Bihar"), ("Ranchi", "Jharkhand"), ("Kolkata", "West Bengal"),
    ("Delhi", "Delhi"), ("Noida", "Uttar Pradesh"), ("Lucknow", "Uttar Pradesh"), ("Jaipur", "Rajasthan"),
    ("Bengaluru", "Karnataka"), ("Chennai", "Tamil Nadu"), ("Hyderabad", "Telangana"), ("Kochi", "Kerala"),
    ("Mumbai", "Maharashtra"), ("Pune", "Maharashtra"), ("Ahmedabad", "Gujarat"),
]

# Messy spellings each branch might use for the same category.
CATEGORY_VARIANTS = {
    "smartphones": ["smartphones", "Smartphones", "SMARTPHONES", "smart phones", "Mobile Phones"],
    "groceries": ["groceries", "Groceries", "GROCERIES", "grocery", "Grocery "],
    "fragrances": ["fragrances", "Fragrances", "perfume", "Perfumes", "FRAGRANCES"],
    "beauty": ["beauty", "Beauty", "BEAUTY", "makeup", "Cosmetics"],
    "furniture": ["furniture", "Furniture", "FURNITURE", "furnitures"],
    "home-decoration": ["home-decoration", "Home Decoration", "home decor", "HOME_DECORATION"],
    "laptops": ["laptops", "Laptops", "laptop", "LAPTOPS", "notebooks"],
    "kitchen-accessories": ["kitchen-accessories", "Kitchen Accessories", "kitchen", "KITCHEN ACCESSORIES"],
}

REGION_VARIANTS = {
    "East": ["East", "east", "EAST", "E", "Eastern", "east "],
    "North": ["North", "north", "NORTH", "N", "Northern", " north"],
    "South": ["South", "south", "SOUTH", "S", "Southern"],
    "West": ["West", "west", "WEST", "W", "Western"],
}

PAYMENT_VARIANTS = {
    "UPI": ["UPI", "upi", "U.P.I", "Upi", "gpay", "phonepe"],
    "Credit Card": ["Credit Card", "credit card", "CC", "creditcard", "CREDIT CARD"],
    "Debit Card": ["Debit Card", "debit card", "DC", "debitcard"],
    "Cash": ["Cash", "cash", "CASH", "cod"],
    "Net Banking": ["Net Banking", "netbanking", "NET BANKING", "net-banking"],
    "Wallet": ["Wallet", "wallet", "Paytm", "paytm wallet"],
}
PAYMENT_WEIGHTS = [0.40, 0.18, 0.15, 0.15, 0.07, 0.05]

# Products that branches sell but the API does not know (to test unmatched joins).
UNKNOWN_PRODUCTS = [
    (9001, "Smart Watch X1", "Electronics", 2499.0),
    (9002, "Bluetooth Speaker Mini", "Electronics", 1299.0),
    (9003, "Yoga Mat Pro", "Sports Accessories", 899.0),
    (9004, "LED Desk Lamp", "Home Decoration", 749.0),
]

# Festive season (Oct, Nov) sells more. Index 0 = January.
MONTH_WEIGHTS = [1.0, 0.9, 1.0, 0.95, 0.9, 0.85, 0.9, 1.0, 1.05, 1.4, 1.5, 1.2]


def load_catalogue(offline: bool, price_to_inr: float) -> list[dict]:
    """Get products from the live API (and refresh the snapshot) or from the snapshot."""
    settings = get_settings()
    products = None
    if not offline:
        try:
            products = fetch_all_products(settings.api_base_url, page_size=100, timeout=10, max_retries=2)
            save_snapshot(products, settings.products_snapshot_path)
            print(f"Loaded {len(products)} products from the live API and refreshed the snapshot.")
        except APIExtractionError as exc:
            print(f"API not reachable ({exc}); using the saved snapshot instead.")
    if products is None:
        products = load_snapshot(settings.products_snapshot_path)
        print(f"Loaded {len(products)} products from {settings.products_snapshot_path}")
    return [
        {"id": int(p["id"]), "title": p["title"], "category": p["category"],
         "price_inr": round(float(p["price"]) * price_to_inr, 2)}
        for p in products
    ]


def random_dates(rng, count: int, start: date, end: date) -> list[date]:
    days = (end - start).days + 1
    all_days = [start + timedelta(days=offset) for offset in range(days)]
    weights = np.array([MONTH_WEIGHTS[d.month - 1] * (1.1 if d.year > start.year else 1.0) for d in all_days])
    weights = weights / weights.sum()
    picks = rng.choice(days, size=count, p=weights)
    return [all_days[i] for i in picks]


def messy_spaces(rng, value: str, probability: float = 0.10) -> str:
    if value and rng.random() < probability:
        return rng.choice([" ", "  "]) + value + rng.choice(["", " ", "   "])
    return value


def generate_customers(rng, count: int) -> pd.DataFrame:
    rows = []
    for number in range(1, count + 1):
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        city, state = CITIES[rng.integers(len(CITIES))]
        reg = date(2019, 1, 1) + timedelta(days=int(rng.integers(0, 2190)))
        name = f"{first} {last}"
        email = f"{first.lower()}.{last.lower()}{number}@example.com"
        reg_text = reg.strftime("%Y-%m-%d")

        roll = rng.random()
        if roll < 0.10:
            name = name.lower() if rng.random() < 0.5 else name.upper()
        if rng.random() < 0.02:
            email = ""                                   # missing email
        elif rng.random() < 0.01:
            email = f"{first.lower()}.{last.lower()}@"   # invalid email
        if rng.random() < 0.015:
            name = ""                                    # missing name
        if rng.random() < 0.05:
            reg_text = reg.strftime("%d/%m/%Y")          # different date format
        elif rng.random() < 0.01:
            reg_text = "unknown"                         # invalid date
        rows.append({
            "customer_id": f"C{number:04d}",
            "customer_name": messy_spaces(rng, name),
            "email": email,
            "city": messy_spaces(rng, city if rng.random() > 0.1 else city.lower()),
            "state": state,
            "registration_date": reg_text,
        })

    frame = pd.DataFrame(rows)
    # Exact duplicate rows (same customer exported twice).
    exact = frame.sample(frac=0.03, random_state=int(rng.integers(1_000_000)))
    # Same customer ID with updated details (customer moved city).
    updated = frame.sample(frac=0.02, random_state=int(rng.integers(1_000_000))).copy()
    new_city = [CITIES[rng.integers(len(CITIES))] for _ in range(len(updated))]
    updated["city"] = [c for c, _ in new_city]
    updated["state"] = [s for _, s in new_city]
    # Rows with no customer ID at all (cannot be used).
    no_id = frame.sample(n=max(1, count // 100), random_state=int(rng.integers(1_000_000))).copy()
    no_id["customer_id"] = ""
    combined = pd.concat([frame, exact, updated, no_id], ignore_index=True)
    return combined


def format_date(value: date, branch_id: str, rng) -> str:
    """Write the date the way this branch does, sometimes in a 'wrong' way."""
    fmt = BRANCHES[branch_id]["date_format"]
    roll = rng.random()
    if roll < 0.01:
        # Impossible or unreadable dates.
        return rng.choice(["31-02-2025", "2025-13-45", "N/A", "00/00/0000", "yesterday"])
    if roll < 0.013:
        return (date(2027, 1, 1) + timedelta(days=int(rng.integers(0, 300)))).strftime(fmt)  # future
    if roll < 0.043:
        return value.strftime("%d %b %Y")   # e.g. "05 Mar 2025": another format
    return value.strftime(fmt)


def generate_branch(rng, branch_id: str, rows: int, catalogue: list[dict],
                    customer_count: int, start: date, end: date) -> pd.DataFrame:
    default_region = BRANCHES[branch_id]["default_region"]
    # Cheap items sell more often than expensive ones; random noise creates best sellers.
    prices = np.array([product["price_inr"] for product in catalogue])
    popularity = rng.lognormal(mean=0.0, sigma=0.6, size=len(catalogue)) / np.sqrt(prices)
    popularity = popularity / popularity.sum()
    dates = random_dates(rng, rows, start, end)
    payments = list(PAYMENT_VARIANTS)

    records = []
    for index in range(rows):
        # ---- product (1.5% are products the API does not know) ----
        if rng.random() < 0.015:
            pid, title, category, base_price = UNKNOWN_PRODUCTS[rng.integers(len(UNKNOWN_PRODUCTS))]
            category_text = category
        else:
            product = catalogue[rng.choice(len(catalogue), p=popularity)]
            pid, title, base_price = product["id"], product["title"], product["price_inr"]
            variants = CATEGORY_VARIANTS.get(product["category"], [product["category"]])
            category_text = rng.choice(variants)
        product_id_text = str(pid) if rng.random() > 0.003 else ""
        product_name = title if rng.random() > 0.15 else rng.choice([title.lower(), title.upper()])
        if rng.random() < 0.03:
            product_name = ""                       # missing product name

        # ---- customer ----
        roll = rng.random()
        if roll < 0.03:
            customer_id = ""                         # missing customer ID
        elif roll < 0.05:
            customer_id = f"C{rng.integers(customer_count + 1, customer_count + 21):04d}"  # not in customers.csv
        elif roll < 0.053:
            customer_id = rng.choice(["CUST-??", "C-12X", "#N/A"])  # malformed
        else:
            customer_id = f"C{rng.integers(1, customer_count + 1):04d}"
            if rng.random() < 0.05:
                customer_id = customer_id.lower()   # "c0042": fixable

        # ---- quantity ----
        if base_price > 20000:          # nobody buys five sofas at once
            quantity = int(rng.choice([1, 1, 1, 1, 2]))
        else:
            quantity = int(rng.choice([1, 1, 1, 1, 2, 2, 2, 3, 3, 4, 5]))
        roll = rng.random()
        quantity_text = str(quantity)
        if roll < 0.01:
            quantity_text = str(-quantity)           # negative quantity
        elif roll < 0.015:
            quantity_text = "0"
        elif roll < 0.017:
            quantity_text = "two"

        # ---- price ----
        price = round(base_price * rng.uniform(0.97, 1.03), 2)
        roll = rng.random()
        price_text = f"{price:.2f}"
        if roll < 0.005:
            price_text = rng.choice(["abc", "N/A", "free"])
        elif roll < 0.010:
            price_text = f"{-price:.2f}"
        elif roll < 0.013:
            price_text = "0"
        elif roll < 0.035:
            price_text = f"₹{price:,.2f}"            # "₹1,099.50": fixable

        # ---- discount (branch 2 writes percent, others write a fraction) ----
        discount = float(rng.choice([0, 0, 0, 0, 0, 0, 0.05, 0.10, 0.15, 0.20]))
        discount_text = f"{discount * 100:g}" if branch_id == "B2" else f"{discount:g}"
        roll = rng.random()
        if roll < 0.01:
            discount_text = ""                       # missing -> treated as no discount
        elif roll < 0.013:
            discount_text = rng.choice(["150", "-5"])  # impossible discount

        # ---- region and payment ----
        region = default_region
        if branch_id == "B3" and rng.random() < 0.3:
            region = "West"
        region_text = rng.choice(REGION_VARIANTS[region]) if rng.random() > 0.01 else ""
        payment = payments[rng.choice(len(payments), p=PAYMENT_WEIGHTS)]
        payment_text = rng.choice(PAYMENT_VARIANTS[payment]) if rng.random() > 0.01 else ""

        records.append({
            "transaction_id": f"T{index + 1:05d}",
            "transaction_date": format_date(dates[index], branch_id, rng),
            "customer_id": customer_id,
            "product_id": product_id_text,
            "product_name": messy_spaces(rng, product_name),
            "category": messy_spaces(rng, category_text),
            "quantity": quantity_text,
            "unit_price": price_text,
            "discount": discount_text,
            "region": messy_spaces(rng, region_text),
            "payment_method": messy_spaces(rng, payment_text),
        })

    frame = pd.DataFrame(records)
    # 2% exact duplicate rows (the same sale exported twice).
    exact = frame.sample(frac=0.02, random_state=int(rng.integers(1_000_000)))
    # 0.5% same transaction ID but a different quantity (conflicting record).
    conflict = frame.sample(frac=0.005, random_state=int(rng.integers(1_000_000))).copy()
    conflict["quantity"] = "7"
    combined = pd.concat([frame, exact, conflict], ignore_index=True)
    return combined.sample(frac=1.0, random_state=int(rng.integers(1_000_000))).reset_index(drop=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate messy sales data for the ETL project")
    parser.add_argument("--rows-per-branch", type=int, default=2000)
    parser.add_argument("--customers", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2026-10-31")
    parser.add_argument("--output", default=None, help="folder for the CSV files (default data/source)")
    parser.add_argument("--offline", action="store_true", help="use the saved product snapshot only")
    args = parser.parse_args(argv)

    settings = get_settings()
    output = Path(args.output) if args.output else settings.source_dir
    output.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)

    catalogue = load_catalogue(args.offline, settings.api_price_to_inr)

    customers = generate_customers(rng, args.customers)
    customers.to_csv(output / CUSTOMERS_FILE_NAME, index=False)
    print(f"customers.csv: {len(customers)} rows")

    for branch_id, branch in BRANCHES.items():
        frame = generate_branch(rng, branch_id, args.rows_per_branch, catalogue, args.customers, start, end)
        frame.to_csv(output / branch["file_name"], index=False)
        print(f"{branch['file_name']}: {len(frame)} rows")
    print(f"Done. Files written to {output}")


if __name__ == "__main__":
    main()
