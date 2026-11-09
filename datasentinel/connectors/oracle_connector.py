"""Oracle connector (python-oracledb; "thin" mode needs no Oracle client install)."""
from __future__ import annotations

import pandas as pd

from datasentinel.connectors.base import BaseConnector, cursor_to_df


class OracleConnector(BaseConnector):
    type_name = "oracle"

    def connect(self) -> None:
        import oracledb

        c = self.config
        if c.get("thick_mode"):                  # only for legacy features (needs Instant Client)
            oracledb.init_oracle_client(lib_dir=c.get("lib_dir"))
        oracledb.defaults.fetch_lobs = False     # return CLOB/BLOB as str/bytes, not LOB handles
        # Either a ready-made DSN ("host:1521/service") or host/port/service_name.
        dsn = c.get("dsn") or oracledb.makedsn(
            c["host"], int(c.get("port", 1521)), service_name=c["service_name"])
        self._conn = oracledb.connect(user=c["user"], password=c["password"], dsn=dsn)

    def fetch_df(self, query: str) -> pd.DataFrame:
        cur = self._conn.cursor()
        try:
            cur.execute(query)                   # factory already stripped any trailing ';'
            return cursor_to_df(cur)
        finally:
            cur.close()

    def close(self) -> None:
        if getattr(self, "_conn", None):
            self._conn.close()
