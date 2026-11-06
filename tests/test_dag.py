"""
Airflow DAG validation.

* Static checks (always run, no Airflow needed): the file is valid Python and
  contains the DAG id, the 8 task ids and the retry settings.
* Real checks (run only where Airflow is installed, e.g. inside the Airflow
  container): Airflow imports the DAG without errors and the dependencies are right.
  Run them with:
      docker compose exec airflow-scheduler python -m pytest /opt/etl/tests/test_dag.py -q
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

DAG_FILE = Path(__file__).resolve().parents[1] / "dags" / "sales_etl_dag.py"
EXPECTED_TASKS = [
    "check_data_sources", "extract_sales_data", "extract_customer_data", "extract_product_data",
    "transform_and_validate_data", "load_data_into_postgresql", "generate_data_quality_report",
    "log_pipeline_execution",
]


def _task_ids_in_source() -> list[str]:
    tree = ast.parse(DAG_FILE.read_text(encoding="utf-8"))
    ids = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "task_id" and isinstance(node.value, ast.Constant):
            ids.append(node.value.value)
    return ids


def test_dag_file_is_valid_python_with_all_tasks():
    source = DAG_FILE.read_text(encoding="utf-8")
    assert 'dag_id="sales_data_etl_pipeline"' in source
    assert sorted(_task_ids_in_source()) == sorted(EXPECTED_TASKS)
    assert '"retries": 2' in source and "retry_delay" in source and "execution_timeout" in source


def test_dag_tasks_call_pipeline_functions_that_exist():
    import src.pipeline as pipeline
    for name in ("step_check_sources", "step_extract_sales", "step_extract_customers",
                 "step_extract_products", "step_transform", "step_load",
                 "step_quality_report", "step_log_execution"):
        assert callable(getattr(pipeline, name))


def test_dag_loads_in_airflow():
    pytest.importorskip("airflow")
    from airflow.models import DagBag

    bag = DagBag(dag_folder=str(DAG_FILE.parent), include_examples=False)
    assert bag.import_errors == {}
    dag = bag.get_dag("sales_data_etl_pipeline")
    assert dag is not None
    assert sorted(dag.task_ids) == sorted(EXPECTED_TASKS)
    transform = dag.get_task("transform_and_validate_data")
    assert transform.upstream_task_ids == {"extract_sales_data", "extract_customer_data", "extract_product_data"}
    assert dag.get_task("log_pipeline_execution").trigger_rule == "all_done"
