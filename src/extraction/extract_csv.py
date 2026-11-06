"""
Extract sales transactions from the branch CSV files.

What this step does
-------------------
1. Finds each branch file listed in config.BRANCHES.
2. Reads it with Pandas, keeping EVERY column as text (dtype=str).
   Why text? If Pandas guessed types, "05-03-2025" might be read wrongly or
   "abc" in the price column would crash the read. Cleaning happens later,
   on purpose, in the transformation step.
3. Adds three tracking columns: branch_id, source_file, source_row_number.
   These let us trace any rejected row back to the exact line in the file.
4. Combines all branches into one table and saves it in data/raw/<run_id>/.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from config.config import BRANCHES, SALES_REQUIRED_COLUMNS
from src.exceptions import SourceFileError
from src.monitoring.logger import get_logger

logger = get_logger(__name__)


def read_csv_safely(path: Path, required_columns: list[str]) -> pd.DataFrame:
    """Read one CSV file and turn every possible problem into a clear error."""
    if not path.exists():
        raise SourceFileError(f"File not found: {path}")
    if path.stat().st_size == 0:
        raise SourceFileError(f"File is empty: {path}")
    try:
        frame = pd.read_csv(
            path,
            dtype=str,              # read everything as text, clean later
            keep_default_na=True,   # empty cells become NaN (missing)
            skipinitialspace=False,
            encoding="utf-8",
        )
    except pd.errors.EmptyDataError as exc:
        raise SourceFileError(f"File has no data: {path}") from exc
    except pd.errors.ParserError as exc:
        raise SourceFileError(f"File is corrupted (cannot parse rows): {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise SourceFileError(f"File is not valid UTF-8 text (corrupted?): {path}") from exc

    # Header names: remove stray spaces and use lowercase so " Quantity" == "quantity".
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    missing = [column for column in required_columns if column not in frame.columns]
    if missing:
        raise SourceFileError(f"{path.name} is missing required columns: {missing}")
    return frame


def extract_branch_sales(source_dir: Path) -> pd.DataFrame:
    """Read every configured branch file and stack them into one table."""
    frames = []
    for branch_id, branch in BRANCHES.items():
        path = source_dir / branch["file_name"]
        frame = read_csv_safely(path, SALES_REQUIRED_COLUMNS)
        frame = frame[SALES_REQUIRED_COLUMNS].copy()   # ignore unexpected extra columns
        frame["branch_id"] = branch_id
        frame["source_file"] = branch["file_name"]
        frame["source_row_number"] = range(2, len(frame) + 2)  # line 1 is the header
        logger.info("Read %d rows from %s (branch %s)", len(frame), path.name, branch_id)
        frames.append(frame)

    combined = pd.concat(frames, ignore_index=True)
    logger.info("Combined %d sales rows from %d branch files", len(combined), len(frames))
    return combined


def extract_sales(source_dir: Path, output_dir: Path) -> dict:
    """Extraction step: read all branch files and save one raw copy."""
    combined = extract_branch_sales(source_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "sales_raw.csv"
    combined.to_csv(output_path, index=False)
    per_branch = combined.groupby("branch_id").size().to_dict()
    return {
        "sales_extracted": int(len(combined)),
        "sales_extracted_per_branch": {key: int(value) for key, value in per_branch.items()},
        "raw_sales_path": str(output_path),
    }
