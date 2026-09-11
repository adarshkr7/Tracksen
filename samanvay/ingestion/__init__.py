"""Ingestion: three departmental systems in, one Unified Task Model out."""

from .adapters import (
    CsvAdapter,
    IngestionResult,
    Rejection,
    RestAdapter,
    SourceReport,
    SqliteViewAdapter,
    ingest,
    ingest_source,
)
from .sources import SourceSpec, export_all

__all__ = [
    "CsvAdapter", "IngestionResult", "Rejection", "RestAdapter", "SourceReport",
    "SourceSpec", "SqliteViewAdapter", "export_all", "ingest", "ingest_source",
]
