"""Excel connector: query a workbook with SQL and get a recordset back.

Trick: every sheet is loaded into an in-memory SQLite database as a table named after the
sheet. The user's SQL then runs against that database, so you get filtering, joins, aggregates
and column selection for free:

    query: SELECT * FROM "Customers" WHERE STATUS = 'ACTIVE'

Sheet names with spaces must be double-quoted. If no SQL is given (or the "query" is just a
sheet name) the whole sheet is returned unchanged.
"""
from __future__ import annotations

import sqlite3
from typing import Dict

import pandas as pd

from datasentinel.config_loader import ConfigError, resolve_path
from datasentinel.connectors.base import BaseConnector, clean_sql


class ExcelConnector(BaseConnector):
    type_name = "excel"

    def connect(self) -> None:
        path = resolve_path(self.config["path"])
        if not path.exists():
            raise ConfigError(f"Excel file not found: {path}")

        # header_row is 1-based for humans; pandas wants a 0-based index.
        read_args = {"header": int(self.config.get("header_row", 1)) - 1}
        if self.config.get("read_as_text"):
            read_args["dtype"] = str             # keeps leading zeros / exact text

        sheet = self.config.get("sheet")         # None -> load every sheet
        loaded = pd.read_excel(path, sheet_name=sheet if sheet else None, **read_args)
        self._sheets: Dict[str, pd.DataFrame] = {sheet: loaded} if sheet else loaded

        # Expose each sheet as a SQL table.
        self._db = sqlite3.connect(":memory:")
        for name, df in self._sheets.items():
            df.to_sql(name, self._db, index=False)

    def fetch_df(self, query: str | None) -> pd.DataFrame:
        q = clean_sql(query or "")
        if not q:                                # no query: single sheet shortcut
            if len(self._sheets) == 1:
                return next(iter(self._sheets.values())).copy()
            raise ConfigError("Excel source needs a 'query' or a single 'sheet' to read")
        if q in self._sheets:                    # query is just a sheet name
            return self._sheets[q].copy()
        return pd.read_sql_query(q, self._db)

    def close(self) -> None:
        if getattr(self, "_db", None):
            self._db.close()
