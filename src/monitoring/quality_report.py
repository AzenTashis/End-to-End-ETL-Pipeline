"""
Data quality report: a short, human-readable summary of what happened to
the data in one pipeline run.

Output (one folder per run):
    reports/<run_id>/data_quality_report.json   (for programs / dashboard)
    reports/<run_id>/data_quality_report.md     (for humans, opens in VS Code / GitHub)
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.monitoring.logger import get_logger

logger = get_logger(__name__)


def _pct(part: int, whole: int) -> str:
    return f"{(100.0 * part / whole):.1f}%" if whole else "n/a"


def build_report(run_id: str, transform_metrics: dict | None, load_metrics: dict | None,
                 extraction: dict | None = None) -> dict:
    t = transform_metrics or {}
    l = load_metrics or {}
    e = extraction or {}
    extracted = t.get("records_extracted", e.get("sales_extracted", 0))
    return {
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "product_source": e.get("product_source"),
        "summary": {
            "total_records_extracted": extracted,
            "duplicate_records_removed": t.get("exact_duplicates_removed"),
            "conflicting_duplicates_rejected": t.get("conflicting_duplicates_rejected"),
            "total_missing_values": sum((t.get("missing_values_in_raw_sales") or {}).values()) if t else None,
            "records_rejected": t.get("records_rejected"),
            "records_successfully_processed": t.get("records_processed"),
            "records_loaded": l.get("sales_rows_upserted"),
            "new_rows_inserted": l.get("sales_new_rows"),
            "unmatched_customer_records": t.get("unmatched_customer_records"),
            "sales_without_customer_id": t.get("missing_customer_id_records"),
            "unmatched_product_records": t.get("unmatched_product_records"),
        },
        "missing_values_by_column": t.get("missing_values_in_raw_sales"),
        "rejection_reasons": t.get("rejection_reasons"),
        "customers": {
            "extracted": t.get("customers_extracted"),
            "rejected": t.get("customers_rejected"),
            "exact_duplicates_removed": t.get("customer_exact_duplicates_removed"),
            "id_duplicates_resolved": t.get("customer_id_duplicates_resolved"),
            "invalid_emails_cleared": t.get("invalid_emails_cleared"),
            "final_unique_customers": t.get("customers_final"),
            "placeholders_created": t.get("customer_placeholders_created"),
            "unmatched_customer_ids": t.get("unmatched_customer_ids"),
        },
        "products": {
            "extracted": t.get("products_extracted"),
            "final": t.get("products_final"),
            "placeholders_created": t.get("product_placeholders_created"),
            "unmatched_product_ids": t.get("unmatched_product_ids"),
        },
        "raw_vs_clean": t.get("raw_vs_clean"),
        "database_totals_after_load": l.get("table_counts"),
    }


def render_markdown(report: dict) -> str:
    s = report["summary"]
    extracted = s.get("total_records_extracted") or 0
    lines = [
        f"# Data quality report: run `{report['run_id']}`",
        "",
        f"Generated: {report['generated_at']}  ",
        f"Product data source: **{report.get('product_source') or 'unknown'}**",
        "",
        "## Summary",
        "",
        "| Metric | Value | Share of extracted |",
        "|---|---:|---:|",
    ]
    for key, value in s.items():
        label = key.replace("_", " ").capitalize()
        row_metric = key not in ("total_records_extracted", "total_missing_values")  # missing values are cells, not rows
        share = _pct(value, extracted) if isinstance(value, int) and row_metric else ""
        lines.append(f"| {label} | {value if value is not None else 'n/a'} | {share} |")

    if report.get("rejection_reasons"):
        lines += ["", "## Why rows were rejected", "", "| Reason | Rows |", "|---|---:|"]
        lines += [f"| {reason} | {count} |" for reason, count in report["rejection_reasons"].items()]

    if report.get("missing_values_by_column"):
        lines += ["", "## Missing values in the raw sales files", "", "| Column | Empty cells |", "|---|---:|"]
        lines += [f"| {column} | {count} |" for column, count in report["missing_values_by_column"].items()]

    if report.get("raw_vs_clean"):
        lines += ["", "## Raw vs clean", "", "| Measure | Raw | Clean |", "|---|---:|---:|"]
        for key, (raw, clean) in report["raw_vs_clean"].items():
            lines.append(f"| {key.replace('_', ' ')} | {raw} | {clean} |")

    c = report.get("customers") or {}
    if c.get("extracted") is not None:
        lines += ["", "## Customers", ""]
        lines += [f"- {k.replace('_', ' ').capitalize()}: {v}" for k, v in c.items() if k != "unmatched_customer_ids"]
        if c.get("unmatched_customer_ids"):
            lines.append(f"- Customer IDs used in sales but missing from customers.csv: {', '.join(c['unmatched_customer_ids'])}")

    p = report.get("products") or {}
    if p.get("extracted") is not None:
        lines += ["", "## Products", ""]
        lines += [f"- {k.replace('_', ' ').capitalize()}: {v}" for k, v in p.items()]

    if report.get("database_totals_after_load"):
        lines += ["", "## Rows in PostgreSQL after this run", ""]
        lines += [f"- {table}: {count}" for table, count in report["database_totals_after_load"].items()]

    lines += ["", "Rejected rows are saved in `data/rejected/<run_id>/rejected_sales.csv` with a `rejection_reason` column.", ""]
    return "\n".join(lines)


def write_report(report: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "data_quality_report.json"
    md_path = output_dir / "data_quality_report.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    logger.info("Data quality report written to %s", md_path)
    return {"report_json": str(json_path), "report_markdown": str(md_path)}
