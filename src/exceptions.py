"""
Custom error types for the pipeline.

Why custom errors?
    "ValueError" could mean anything. "SourceFileError: sales_branch_2.csv
    not found" tells you instantly which stage broke and why. Airflow shows
    this message in the task log, so good error names save debugging time.
"""


class ETLError(Exception):
    """Base class for every error raised on purpose by this pipeline."""


class SourceFileError(ETLError):
    """A CSV file is missing, empty, corrupted, or has the wrong columns."""


class APIExtractionError(ETLError):
    """The product API timed out, refused the connection, or sent bad data."""


class DataValidationError(ETLError):
    """Data is so broken that the pipeline cannot continue safely."""


class DatabaseError(ETLError):
    """Connecting to or writing into PostgreSQL failed."""
