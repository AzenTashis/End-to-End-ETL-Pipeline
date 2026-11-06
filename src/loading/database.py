"""
Database connection helpers (SQLAlchemy).

Key ideas
---------
* Engine: SQLAlchemy's "connection factory". Created once, it opens and
  reuses connections to PostgreSQL for us (a connection pool).
* Transaction: `with engine.begin() as conn:` opens a transaction. If the
  block finishes, everything is COMMITTED (saved). If any error happens
  inside, everything is ROLLED BACK (undone). This is what keeps the
  database consistent when something fails half way.
* pool_pre_ping: checks a connection is still alive before using it, which
  avoids confusing errors after the database restarts.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from config.config import get_settings
from src.exceptions import DatabaseError
from src.monitoring.logger import get_logger

logger = get_logger(__name__)


def get_engine(database_url: str | None = None) -> Engine:
    """Create a SQLAlchemy engine for the sales database."""
    url = database_url or get_settings().database_url
    engine = create_engine(url, pool_pre_ping=True)

    if engine.dialect.name == "sqlite":
        # SQLite (used only by tests) ignores foreign keys unless asked.
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):  # pragma: no cover - tiny hook
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def check_connection(engine: Engine, attempts: int = 3, wait_seconds: float = 5) -> None:
    """Run SELECT 1, retrying a few times (the database may still be starting)."""
    for attempt in range(1, attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database connection OK (%s)", engine.url.render_as_string(hide_password=True))
            return
        except OperationalError as exc:
            logger.warning("Database not reachable (attempt %d/%d): %s", attempt, attempts, exc.orig)
            if attempt == attempts:
                raise DatabaseError(f"Cannot connect to the database after {attempts} attempts: {exc.orig}") from exc
            time.sleep(wait_seconds)


def split_sql_statements(sql: str) -> list[str]:
    """Split a .sql file into single statements (comments removed)."""
    without_comments = re.sub(r"--[^\n]*", "", sql)
    return [statement.strip() for statement in without_comments.split(";") if statement.strip()]


def create_tables(engine: Engine, sql_path: Path | None = None) -> None:
    """Run sql/create_tables.sql. Safe to call on every run (IF NOT EXISTS)."""
    path = sql_path or get_settings().sql_dir / "create_tables.sql"
    statements = split_sql_statements(path.read_text(encoding="utf-8"))
    try:
        with engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))
    except SQLAlchemyError as exc:
        raise DatabaseError(f"Creating tables failed: {exc}") from exc
    logger.info("Tables are ready (%d statements executed)", len(statements))


def table_counts(engine: Engine) -> dict[str, int]:
    tables = ["customers", "products", "sales_transactions", "etl_logs"]
    with engine.connect() as conn:
        return {table: int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()) for table in tables}


if __name__ == "__main__":
    # `python -m src.loading.database` creates the tables and prints row counts.
    db = get_engine()
    check_connection(db)
    create_tables(db)
    print(table_counts(db))
