"""Base connector contract shared by every data source.

A connector has ONE job: turn a query into a pandas DataFrame (the "recordset").
Everything downstream (comparison, validation, reporting) only ever sees DataFrames, which is
what lets Snowflake, Oracle, Databricks, Excel and even a web page be mixed freely.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

import pandas as pd


class BaseConnector(ABC):
    """Lifecycle: connect() -> fetch_df(query) [any number of times] -> close().

    Use it as a context manager so close() always runs:

        with build_connector(endpoint) as conn:
            df = conn.fetch_df("SELECT ...")
    """

    type_name = "base"

    def __init__(self, config: Dict[str, Any]):
        # `config` is the merged connection settings (secrets already decrypted).
        self.config = dict(config)

    def connect(self) -> None:  # pragma: no cover - optional hook
        """Open the underlying connection (no-op by default)."""

    @abstractmethod
    def fetch_df(self, query: str | None) -> pd.DataFrame:
        """Run *query* and return all rows as a DataFrame."""

    def close(self) -> None:  # pragma: no cover - optional hook
        """Release resources (no-op by default)."""

    def __enter__(self) -> "BaseConnector":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def cursor_to_df(cursor) -> pd.DataFrame:
    """Convert any DB-API cursor that has a result set into a DataFrame.

    Works for Snowflake, Oracle and Databricks cursors alike (they all follow PEP 249), which
    avoids depending on driver-specific pandas helpers such as pyarrow.
    """
    columns = [d[0] for d in cursor.description]
    # Databricks returns Row objects; tuple() normalises them.
    rows = [tuple(r) for r in cursor.fetchall()]
    return pd.DataFrame.from_records(rows, columns=columns)


def clean_sql(query: str) -> str:
    """Strip whitespace and a trailing semicolon (Oracle rejects a trailing ';')."""
    return query.strip().rstrip(";").strip()
