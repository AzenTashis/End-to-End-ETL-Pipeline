"""
# sales_data_etl_pipeline

Daily ETL for Meridian Retail: branch CSVs + customer CSV + product API
-> cleaned, validated, integrated -> PostgreSQL (`sales_dw`).

This file only ORCHESTRATES. All business logic lives in `src/`, and each
task simply calls one function from `src/pipeline.py`. That keeps the DAG
short, and lets you run and test the same logic without Airflow.

Task flow:

    check_data_sources
        -> extract_sales_data, extract_customer_data, extract_product_data   (in parallel)
        -> transform_and_validate_data
        -> load_data_into_postgresql
        -> generate_data_quality_report   (runs even if the load failed)
        -> log_pipeline_execution         (always runs; writes etl_logs)
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import timedelta
from pathlib import Path

import pendulum

# Make `src` and `config` importable. In Docker the project is mounted at /opt/etl.
PROJECT_ROOT = Path(os.getenv("ETL_PROJECT_ROOT", str(Path(__file__).resolve().parents[1])))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Airflow 3 moved some imports; the fallbacks keep the DAG working on Airflow 2.x too.
try:
    from airflow.sdk import DAG
except ImportError:  # Airflow 2.x
    from airflow import DAG

try:
    from airflow.providers.standard.operators.python import PythonOperator
except ImportError:  # Airflow 2.x
    from airflow.operators.python import PythonOperator

try:
    from airflow.exceptions import AirflowFailException
except ImportError:  # pragma: no cover
    AirflowFailException = RuntimeError

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Small wrappers. Imports happen INSIDE the functions so that Airflow's DAG
# parser (which re-reads this file every few seconds) does not load pandas.
# ---------------------------------------------------------------------------

def _run_id(context) -> str:
    from src.pipeline import make_run_id
    return make_run_id(context["run_id"])


def check_data_sources(**context):
    from src.pipeline import step_check_sources
    return step_check_sources(_run_id(context))


def extract_sales_data(**context):
    from src.pipeline import step_extract_sales
    return step_extract_sales(_run_id(context))


def extract_customer_data(**context):
    from src.pipeline import step_extract_customers
    return step_extract_customers(_run_id(context))


def extract_product_data(**context):
    from src.pipeline import step_extract_products
    return step_extract_products(_run_id(context))


def transform_and_validate_data(**context):
    from src.pipeline import step_transform
    return step_transform(_run_id(context))


def load_data_into_postgresql(**context):
    from src.pipeline import step_load
    result = step_load(_run_id(context))
    return {key: value for key, value in result.items() if key != "table_counts"}


def generate_data_quality_report(**context):
    from src.pipeline import step_quality_report
    return step_quality_report(_run_id(context))


def log_pipeline_execution(**context):
    from src.pipeline import step_log_execution
    record = step_log_execution(_run_id(context), run_source="airflow")
    if record["execution_status"] != "SUCCESS":
        # The log row is saved; now mark this task (and the DAG run) as failed,
        # without retrying, so the failure is visible in the Airflow UI.
        raise AirflowFailException(f"Pipeline run failed: {record['error_message']}")
    return record


def notify_failure(context):
    """Called by Airflow when a task fails (after its last retry)."""
    task_instance = context.get("task_instance")
    log.error(
        "Task %s failed in DAG run %s. Error: %s",
        getattr(task_instance, "task_id", "?"),
        context.get("run_id"),
        context.get("exception"),
    )


default_args = {
    "owner": "data-engineering",
    "retries": 2,                                # try again twice before giving up
    "retry_delay": timedelta(minutes=2),         # first wait 2 minutes
    "retry_exponential_backoff": True,           # then wait longer each time
    "max_retry_delay": timedelta(minutes=10),
    "execution_timeout": timedelta(minutes=15),  # kill a task that hangs
    "on_failure_callback": notify_failure,
}

with DAG(
    dag_id="sales_data_etl_pipeline",
    description="Multi-source sales ETL: CSV + REST API -> PostgreSQL",
    schedule="0 2 * * *",                        # every day at 02:00
    start_date=pendulum.datetime(2026, 11, 1, tz="Asia/Kolkata"),
    catchup=False,                               # do not back-fill old days
    max_active_runs=1,                           # never two runs at the same time
    dagrun_timeout=timedelta(hours=1),
    default_args=default_args,
    tags=["etl", "sales", "postgres"],
    doc_md=__doc__,
) as dag:

    t_check = PythonOperator(task_id="check_data_sources", python_callable=check_data_sources)
    t_sales = PythonOperator(task_id="extract_sales_data", python_callable=extract_sales_data)
    t_customers = PythonOperator(task_id="extract_customer_data", python_callable=extract_customer_data)
    t_products = PythonOperator(task_id="extract_product_data", python_callable=extract_product_data)
    t_transform = PythonOperator(task_id="transform_and_validate_data",
                                 python_callable=transform_and_validate_data)
    t_load = PythonOperator(task_id="load_data_into_postgresql", python_callable=load_data_into_postgresql)
    t_report = PythonOperator(
        task_id="generate_data_quality_report",
        python_callable=generate_data_quality_report,
        trigger_rule="all_done",                 # run even if the load failed
    )
    t_log = PythonOperator(
        task_id="log_pipeline_execution",
        python_callable=log_pipeline_execution,
        trigger_rule="all_done",                 # always record what happened
        retries=1,
    )

    t_check >> [t_sales, t_customers, t_products] >> t_transform >> t_load >> t_report >> t_log
