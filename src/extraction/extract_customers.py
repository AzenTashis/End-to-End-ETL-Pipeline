"""
Extract customer information from customers.csv.

Same approach as the sales files: read as text, check the columns,
and save an untouched copy into data/raw/<run_id>/.
"""

from __future__ import annotations

from pathlib import Path

from config.config import CUSTOMER_REQUIRED_COLUMNS, CUSTOMERS_FILE_NAME
from src.extraction.extract_csv import read_csv_safely
from src.monitoring.logger import get_logger

logger = get_logger(__name__)


def extract_customers(source_dir: Path, output_dir: Path) -> dict:
    path = source_dir / CUSTOMERS_FILE_NAME
    frame = read_csv_safely(path, CUSTOMER_REQUIRED_COLUMNS)
    frame = frame[CUSTOMER_REQUIRED_COLUMNS].copy()
    frame["source_row_number"] = range(2, len(frame) + 2)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "customers_raw.csv"
    frame.to_csv(output_path, index=False)
    logger.info("Read %d customer rows from %s", len(frame), path.name)
    return {"customers_extracted": int(len(frame)), "raw_customers_path": str(output_path)}
