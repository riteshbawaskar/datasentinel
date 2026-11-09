"""SQLite connector - used by the demo scenarios and by the framework's own unit tests."""
from __future__ import annotations

import sqlite3

import pandas as pd

from datasentinel.config_loader import resolve_path
from datasentinel.connectors.base import BaseConnector


class SqliteConnector(BaseConnector):
    type_name = "sqlite"

    def connect(self) -> None:
        self._conn = sqlite3.connect(str(resolve_path(self.config["path"])))

    def fetch_df(self, query: str) -> pd.DataFrame:
        return pd.read_sql_query(query, self._conn)

    def close(self) -> None:
        if getattr(self, "_conn", None):
            self._conn.close()
