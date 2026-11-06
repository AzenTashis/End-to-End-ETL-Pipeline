"""
Run the business SQL queries in analytics/queries.sql and print the answers.

    python -m analytics.run_queries                      # run all queries
    python -m analytics.run_queries --query top_10_products

Every result is also saved as a CSV file in analytics/output/.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

QUERIES_FILE = PROJECT_ROOT / "analytics" / "queries.sql"
OUTPUT_DIR = PROJECT_ROOT / "analytics" / "output"


def parse_queries(sql_text: str) -> dict[str, str]:
    """Split the file on '-- name: xxx' markers -> {name: sql}."""
    queries: dict[str, str] = {}
    parts = re.split(r"^--\s*name:\s*(\w+)\s*$", sql_text, flags=re.MULTILINE)
    # parts = [header, name1, body1, name2, body2, ...]
    for name, body in zip(parts[1::2], parts[2::2]):
        lines = [line for line in body.strip().splitlines() if not line.strip().startswith("--")]
        queries[name] = "\n".join(lines).strip().rstrip(";")
    return queries


def load_queries(path: Path = QUERIES_FILE) -> dict[str, str]:
    return parse_queries(path.read_text(encoding="utf-8"))


def run_query(engine, sql: str) -> pd.DataFrame:
    """Execute one SELECT and return a DataFrame (works with any SQLAlchemy version)."""
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        columns = list(result.keys())
        rows = result.fetchall()
    frame = pd.DataFrame([tuple(row) for row in rows], columns=columns)
    # PostgreSQL returns NUMERIC as Python Decimal; convert to float for printing/plotting.
    for column in frame.columns:
        if frame[column].map(lambda v: v.__class__.__name__ == "Decimal").any():
            frame[column] = frame[column].astype(float)
    return frame


def main(argv: list[str] | None = None) -> None:
    from src.loading.database import get_engine

    parser = argparse.ArgumentParser(description="Run the analytics SQL queries")
    parser.add_argument("--query", help="run only this query (name from queries.sql)")
    args = parser.parse_args(argv)

    queries = load_queries()
    if args.query:
        if args.query not in queries:
            raise SystemExit(f"Unknown query '{args.query}'. Choose from: {', '.join(queries)}")
        queries = {args.query: queries[args.query]}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    engine = get_engine()
    pd.set_option("display.width", 160)
    pd.set_option("display.float_format", lambda v: f"{v:,.2f}")
    for name, sql in queries.items():
        frame = run_query(engine, sql)
        frame.to_csv(OUTPUT_DIR / f"{name}.csv", index=False)
        print(f"\n=== {name} ({len(frame)} rows) ===")
        print(frame.to_string(index=False))
    engine.dispose()
    print(f"\nCSV results saved in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
