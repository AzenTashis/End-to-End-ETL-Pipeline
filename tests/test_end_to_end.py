"""
End-to-end test: generate data -> run the whole pipeline -> check the database
-> run it again (idempotency) -> run every analytics query.
Uses SQLite by default, PostgreSQL if TEST_DATABASE_URL is set.
"""

from __future__ import annotations

import pytest


def test_full_pipeline_twice_and_analytics(data_root, engine):
    from sqlalchemy import text

    from analytics.run_queries import load_queries, run_query
    from scripts.generate_data import main as generate
    from src.pipeline import run_pipeline

    source = data_root / "data" / "source"
    generate(["--rows-per-branch", "200", "--customers", "50", "--offline", "--output", str(source)])

    first = run_pipeline("e2e_run_1")
    assert first["execution_status"] == "SUCCESS", first.get("error_message")
    assert first["records_loaded"] == first["records_transformed"] > 0
    assert first["records_extracted"] > first["records_transformed"]   # some rows were cleaned away

    with engine.connect() as conn:
        sales_after_first = conn.execute(text("SELECT COUNT(*) FROM sales_transactions")).scalar()
    assert sales_after_first == first["records_loaded"]

    second = run_pipeline("e2e_run_2")
    assert second["execution_status"] == "SUCCESS"
    with engine.connect() as conn:
        sales_after_second = conn.execute(text("SELECT COUNT(*) FROM sales_transactions")).scalar()
        logs = conn.execute(text("SELECT COUNT(*) FROM etl_logs")).scalar()
        orphans = conn.execute(text(
            "SELECT COUNT(*) FROM sales_transactions s LEFT JOIN customers c ON c.customer_id = s.customer_id "
            "WHERE c.customer_id IS NULL")).scalar()
    assert sales_after_second == sales_after_first      # idempotent: no duplicates
    assert logs == 2
    assert orphans == 0

    assert (data_root / "reports" / "e2e_run_1" / "data_quality_report.md").exists()

    queries = load_queries()
    assert len(queries) >= 10
    for name, sql in queries.items():
        frame = run_query(engine, sql)
        assert not frame.empty, f"query {name} returned nothing"
    total = run_query(engine, queries["total_revenue"])
    assert total.loc[0, "transactions"] == sales_after_first


def test_pipeline_records_failure_in_etl_logs(data_root, engine):
    from sqlalchemy import text

    from src.pipeline import run_pipeline

    # No source files at all -> the very first step fails.
    result = run_pipeline("e2e_failure")
    assert result["execution_status"] == "FAILED"
    assert "check_data_sources" in result["error_message"]
    with engine.connect() as conn:
        status = conn.execute(text("SELECT execution_status FROM etl_logs WHERE execution_id='e2e_failure'")).scalar()
    assert status == "FAILED"


@pytest.mark.parametrize("raw, expected", [("manual__2026-11-07T01:18:00+00:00", "manual__2026-11-07T01_18_00_00_00"),
                                           ("scheduled__2026-11-08", "scheduled__2026-11-08")])
def test_run_ids_are_safe_folder_names(raw, expected):
    from src.pipeline import make_run_id
    assert make_run_id(raw) == expected
