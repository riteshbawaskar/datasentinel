"""Databricks SQL connector (databricks-sql-connector)."""
from __future__ import annotations

import pandas as pd

from datasentinel.connectors.base import BaseConnector, cursor_to_df


class DatabricksConnector(BaseConnector):
    type_name = "databricks"

    def connect(self) -> None:
        from databricks import sql

        c = self.config
        kwargs = {
            "server_hostname": c["server_hostname"],
            "http_path": c["http_path"],
            "access_token": c["access_token"],   # personal access token (can be ENC(...))
        }
        for opt in ("catalog", "schema"):        # optional default catalog/schema
            if c.get(opt):
                kwargs[opt] = c[opt]
        self._conn = sql.connect(**kwargs)

    def fetch_df(self, query: str) -> pd.DataFrame:
        with self._conn.cursor() as cur:
            cur.execute(query)
            return cursor_to_df(cur)

    def close(self) -> None:
        if getattr(self, "_conn", None):
            self._conn.close()
