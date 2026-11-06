"""
The pipeline runner: every ETL step as a small function, plus a command line.

Each step function:
    * takes a run_id (a name for this run, e.g. "cli_20261107T020000"),
    * reads its input files from the previous step's folder,
    * writes its output files into folders named after the run_id,
    * records whether it succeeded in reports/<run_id>/steps/<step>.json.

Airflow calls these same functions one per task (see dags/sales_etl_dag.py).
You can also run everything without Airflow:

    python -m src.pipeline                  # full run
    python -m src.pipeline --run-id test1   # choose the run name
    python -m src.pipeline --skip-load      # extract + transform only (no database needed)
"""

from __future__ import annotations

import argparse
import functools
import json
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path

from config.config import get_settings
from src.monitoring.logger import get_logger

logger = get_logger(__name__)

STEPS = [
    "check_data_sources",
    "extract_sales_data",
    "extract_customer_data",
    "extract_product_data",
    "transform_and_validate_data",
    "load_data_into_postgresql",
    "generate_data_quality_report",
]


# ---------------------------------------------------------------- helpers ----

def make_run_id(raw: str | None = None) -> str:
    """Turn any run name into a safe folder name (Windows forbids ':' and '+')."""
    if not raw:
        raw = "cli_" + datetime.now().strftime("%Y%m%dT%H%M%S")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_")[:120]


def run_dirs(run_id: str) -> dict[str, Path]:
    s = get_settings()
    return {
        "raw": s.raw_dir / run_id,
        "processed": s.processed_dir / run_id,
        "rejected": s.rejected_dir / run_id,
        "reports": s.reports_dir / run_id,
        "steps": s.reports_dir / run_id / "steps",
    }


def _write_status(run_id: str, step: str, status: str, summary: dict | None = None, error: str | None = None):
    path = run_dirs(run_id)["steps"]
    path.mkdir(parents=True, exist_ok=True)
    payload = {"step": step, "status": status, "finished_at": datetime.now().isoformat(timespec="seconds"),
               "summary": summary or {}, "error": error}
    (path / f"{step}.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def read_status(run_id: str, step: str) -> dict | None:
    path = run_dirs(run_id)["steps"] / f"{step}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def tracked_step(step_name: str):
    """Decorator: log start/end and save success or failure for this step."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(run_id: str, *args, **kwargs):
            logger.info("=== %s started (run %s) ===", step_name, run_id)
            try:
                summary = func(run_id, *args, **kwargs) or {}
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                logger.error("=== %s FAILED: %s ===", step_name, message)
                logger.debug(traceback.format_exc())
                _write_status(run_id, step_name, "failed", error=message)
                raise
            _write_status(run_id, step_name, "success", summary=summary)
            logger.info("=== %s finished ===", step_name)
            return summary
        return wrapper
    return decorator


# ------------------------------------------------------------------ steps ----

@tracked_step("check_data_sources")
def step_check_sources(run_id: str) -> dict:
    from src.extraction.check_sources import check_data_sources
    return check_data_sources()


@tracked_step("extract_sales_data")
def step_extract_sales(run_id: str) -> dict:
    from src.extraction.extract_csv import extract_sales
    return extract_sales(get_settings().source_dir, run_dirs(run_id)["raw"])


@tracked_step("extract_customer_data")
def step_extract_customers(run_id: str) -> dict:
    from src.extraction.extract_customers import extract_customers
    return extract_customers(get_settings().source_dir, run_dirs(run_id)["raw"])


@tracked_step("extract_product_data")
def step_extract_products(run_id: str) -> dict:
    from src.extraction.extract_api import extract_products
    return extract_products(run_dirs(run_id)["raw"])


@tracked_step("transform_and_validate_data")
def step_transform(run_id: str) -> dict:
    from src.transformation.transform_data import run_transformation
    dirs = run_dirs(run_id)
    metrics = run_transformation(dirs["raw"], dirs["processed"], dirs["rejected"])
    # Keep the step summary short; full metrics live in transform_metrics.json.
    return {key: metrics[key] for key in ("records_extracted", "records_processed", "records_rejected",
                                          "exact_duplicates_removed", "unmatched_customer_records",
                                          "unmatched_product_records")}


@tracked_step("load_data_into_postgresql")
def step_load(run_id: str) -> dict:
    from src.loading.database import check_connection, get_engine
    from src.loading.load_data import load_processed_files
    engine = get_engine()
    try:
        check_connection(engine)
        return load_processed_files(engine, run_dirs(run_id)["processed"])
    finally:
        engine.dispose()


@tracked_step("generate_data_quality_report")
def step_quality_report(run_id: str) -> dict:
    from src.monitoring.quality_report import build_report, write_report
    dirs = run_dirs(run_id)
    metrics_path = dirs["processed"] / "transform_metrics.json"
    transform_metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else None
    load_status = read_status(run_id, "load_data_into_postgresql")
    load_metrics = load_status["summary"] if load_status and load_status["status"] == "success" else None
    product_status = read_status(run_id, "extract_product_data")
    extraction = dict(product_status["summary"]) if product_status else {}
    sales_status = read_status(run_id, "extract_sales_data")
    if sales_status:
        extraction.update(sales_status["summary"])
    report = build_report(run_id, transform_metrics, load_metrics, extraction)
    return write_report(report, dirs["reports"])


def step_log_execution(run_id: str, run_source: str = "cli") -> dict:
    """Write one row into etl_logs describing this run (success or failure)."""
    from src.loading.database import get_engine
    from src.loading.load_data import write_etl_log

    statuses = {step: read_status(run_id, step) for step in STEPS}
    errors = [f"{step}: {s['error']}" for step, s in statuses.items() if s and s["status"] == "failed"]
    not_run = [step for step, s in statuses.items() if s is None]
    if not_run:
        errors.append("steps that did not run: " + ", ".join(not_run))

    def summary(step: str, key: str) -> int:
        s = statuses.get(step)
        return int(s["summary"].get(key, 0)) if s and s["status"] == "success" else 0

    record = {
        "execution_id": run_id,
        "records_extracted": summary("extract_sales_data", "sales_extracted"),
        "records_transformed": summary("transform_and_validate_data", "records_processed"),
        "records_loaded": summary("load_data_into_postgresql", "sales_rows_upserted"),
        "records_rejected": summary("transform_and_validate_data", "records_rejected"),
        "execution_status": "FAILED" if errors else "SUCCESS",
        "error_message": " | ".join(errors)[:4000] if errors else None,
        "run_source": run_source,
    }
    engine = get_engine()
    try:
        write_etl_log(engine, record)
    finally:
        engine.dispose()
    return record


# --------------------------------------------------------------- full run ----

def run_pipeline(run_id: str | None = None, skip_load: bool = False) -> dict:
    """Run every step in order. Returns the etl_logs record (or a summary)."""
    run_id = make_run_id(run_id)
    logger.info("Pipeline run %s starting", run_id)
    steps = [step_check_sources, step_extract_sales, step_extract_customers,
             step_extract_products, step_transform]
    if not skip_load:
        steps.append(step_load)

    failed = False
    for step in steps:
        try:
            step(run_id)
        except Exception:  # already logged and recorded by tracked_step
            failed = True
            break

    try:
        step_quality_report(run_id)
    except Exception:
        logger.warning("Quality report could not be generated")

    if skip_load:
        status = "FAILED" if failed else "SUCCESS"
        logger.info("Pipeline run %s finished (no database): %s", run_id, status)
        return {"execution_id": run_id, "execution_status": status}

    try:
        record = step_log_execution(run_id, run_source="cli")
    except Exception as exc:  # e.g. database is down, so the log row cannot be written
        logger.error("Could not write to etl_logs: %s", exc)
        record = {"execution_id": run_id, "execution_status": "FAILED",
                  "error_message": f"etl_logs not written: {exc}"}
    logger.info("Pipeline run %s finished: %s", run_id, record["execution_status"])
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the sales ETL pipeline without Airflow")
    parser.add_argument("--run-id", default=None, help="name for this run (default: cli_<timestamp>)")
    parser.add_argument("--skip-load", action="store_true", help="stop before loading into PostgreSQL")
    args = parser.parse_args(argv)
    result = run_pipeline(args.run_id, skip_load=args.skip_load)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["execution_status"] == "SUCCESS" else 1


if __name__ == "__main__":
    sys.exit(main())
