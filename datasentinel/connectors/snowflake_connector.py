"""Snowflake connector (snowflake-connector-python)."""
from __future__ import annotations

import pandas as pd

from datasentinel.config_loader import resolve_path
from datasentinel.connectors.base import BaseConnector, cursor_to_df

# Settings forwarded verbatim to snowflake.connector.connect() when present.
_PASSTHROUGH = ("account", "user", "password", "warehouse", "database", "schema",
                "role", "authenticator", "token", "session_parameters")


class SnowflakeConnector(BaseConnector):
    type_name = "snowflake"

    def connect(self) -> None:
        # Imported lazily so users who never touch Snowflake don't need the driver installed.
        import snowflake.connector

        params = {k: self.config[k] for k in _PASSTHROUGH if self.config.get(k)}
        if self.config.get("private_key_path"):          # key-pair authentication
            params["private_key"] = self._load_private_key()
        self._conn = snowflake.connector.connect(**params)

    def _load_private_key(self) -> bytes:
        """Load a PEM private key and return it as DER bytes, the format Snowflake expects."""
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import serialization

        passphrase = self.config.get("private_key_passphrase")  # already decrypted if ENC(...)
        with open(resolve_path(self.config["private_key_path"]), "rb") as fh:
            key = serialization.load_pem_private_key(
                fh.read(),
                password=passphrase.encode() if passphrase else None,
                backend=default_backend(),
            )
        return key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def fetch_df(self, query: str) -> pd.DataFrame:
        cur = self._conn.cursor()
        try:
            cur.execute(query)
            if self.config.get("use_arrow"):     # much faster for big results; needs pyarrow
                return cur.fetch_pandas_all()
            return cursor_to_df(cur)
        finally:
            cur.close()

    def close(self) -> None:
        if getattr(self, "_conn", None):
            self._conn.close()
