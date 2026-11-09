"""Connector factory + the single entry point `fetch_dataset(endpoint)`.

An *endpoint* is the dict found under `source:` / `target:` in compare configs (and at the top
level of validation configs):

    connection: snowflake_dev        # a name from config/connections.yml ...
    # ... or an inline definition:   type: excel, path: data/file.xlsx
    query: SELECT ...                # or  query_file: path.sql   or   table: SCHEMA.TABLE
    <any other key overrides the named connection's setting, e.g.  schema: QA>

Resolution order for connection settings:  named connection  <  keys written inline.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any, Dict, Optional

import pandas as pd

from datasentinel.config_loader import ConfigError, get_connection_config, resolve_path
from datasentinel.connectors.base import BaseConnector, clean_sql
from datasentinel.security import decrypt_tree

# type name -> (module, class). Imported lazily, so a missing driver (say oracledb) only
# matters when an Oracle endpoint is actually used.
_REGISTRY = {
    "snowflake": ("datasentinel.connectors.snowflake_connector", "SnowflakeConnector"),
    "oracle": ("datasentinel.connectors.oracle_connector", "OracleConnector"),
    "databricks": ("datasentinel.connectors.databricks_connector", "DatabricksConnector"),
    "excel": ("datasentinel.connectors.excel_connector", "ExcelConnector"),
    "sqlite": ("datasentinel.connectors.sqlite_connector", "SqliteConnector"),
    "web_table": ("datasentinel.connectors.web_table_connector", "WebTableConnector"),
}

# Endpoint keys that describe WHAT to read, not HOW to connect.
_NON_CONNECTION_KEYS = {"query", "query_file", "table", "connection", "name", "description"}


def supported_types() -> list[str]:
    return sorted(_REGISTRY)


def build_connector(endpoint: Dict[str, Any]) -> BaseConnector:
    """Create (but do not connect) the right connector for an endpoint dict."""
    settings: Dict[str, Any] = {}
    if endpoint.get("connection"):                      # 1) named connection from connections.yml
        settings.update(get_connection_config(endpoint["connection"]))
    settings.update({k: v for k, v in endpoint.items()   # 2) inline keys win
                     if k not in _NON_CONNECTION_KEYS})

    kind = str(settings.get("type", "")).lower()
    if kind not in _REGISTRY:
        raise ConfigError(f"Unsupported or missing connection type '{kind}'. "
                          f"Supported: {supported_types()}")

    # 3) Decrypt ENC(...) secrets IN MEMORY, only now that we are about to connect.
    #    The decrypted dict is handed to the connector and never written anywhere.
    settings = decrypt_tree(settings)

    module, cls = _REGISTRY[kind]
    return getattr(import_module(module), cls)(settings)


def resolve_query(endpoint: Dict[str, Any]) -> Optional[str]:
    """Pick the SQL from `query`, `query_file` or `table` (in that order)."""
    if endpoint.get("query"):
        return clean_sql(endpoint["query"])
    if endpoint.get("query_file"):
        return clean_sql(resolve_path(endpoint["query_file"]).read_text(encoding="utf-8"))
    if endpoint.get("table"):
        return f"SELECT * FROM {endpoint['table']}"
    return None   # Excel / web_table sources may legitimately have no query


def fetch_dataset(endpoint: Dict[str, Any]) -> pd.DataFrame:
    """Connect, run the endpoint's query, close the connection, return a DataFrame."""
    query = resolve_query(endpoint)
    with build_connector(endpoint) as conn:
        return conn.fetch_df(query)
