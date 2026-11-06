"""
Application logging.

Two kinds of logs exist in this project:

1. Application logs (this file). Our own messages such as
   "Read 2,041 rows from sales_branch_1.csv". They go to the console and to
   logs/pipeline.log, so you can read them even when Airflow is not running.

2. Airflow task logs. Airflow captures everything a task prints and shows
   it in the web UI (click a task, then "Logs"). When our code runs inside
   Airflow, our messages flow into those task logs too.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from config.config import get_settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_configured = False


def _running_inside_airflow() -> bool:
    # Airflow sets AIRFLOW_CTX_* variables while a task is running.
    return any(key.startswith("AIRFLOW_CTX_") for key in os.environ)


def _configure_root_logger() -> None:
    global _configured
    if _configured:
        return

    settings = get_settings()
    logger = logging.getLogger("etl")
    logger.setLevel(settings.log_level)
    formatter = logging.Formatter(_LOG_FORMAT)

    # File handler: keeps the last 5 files of 5 MB each, then rotates.
    try:
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            settings.logs_dir / "pipeline.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        # If the log folder is read-only we still want console logs.
        pass

    if _running_inside_airflow():
        # Let messages travel up to Airflow's own handlers (task log in the UI).
        logger.propagate = True
    else:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(console)
        logger.propagate = False

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger such as 'etl.extraction.extract_csv'."""
    _configure_root_logger()
    short = "pipeline" if name == "__main__" else name.replace("src.", "")
    return logging.getLogger(f"etl.{short}")
