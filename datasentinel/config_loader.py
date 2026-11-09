"""YAML loading helpers: env-var expansion, path resolution and connection lookup.

Every config file in the framework (connections, compare, validation, UI) is read through
`load_yaml`, so they all share the same conventions:

* relative paths are resolved from the PROJECT ROOT (not the current directory), so the
  suite behaves the same whether you run it from the repo root, an IDE or CI;
* ``${VAR}`` / ``${VAR:default}`` placeholders are replaced from environment variables.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict

import yaml

# Project root = parent of the `datasentinel` package folder.
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONNECTIONS_FILE = BASE_DIR / "config" / "connections.yml"

# ${NAME} or ${NAME:default value}
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")


class ConfigError(Exception):
    """Raised for missing / invalid configuration (clear message, no stack-trace noise)."""


def resolve_path(path: str | os.PathLike) -> Path:
    """Resolve *path* relative to the project root unless it is already absolute."""
    p = Path(path).expanduser()
    return p if p.is_absolute() else BASE_DIR / p


def expand_env(value: Any) -> Any:
    """Recursively replace ${VAR} / ${VAR:default} using environment variables.

    Unresolved placeholders (no env var, no default) are left untouched so the caller can
    detect them and raise a helpful error (see `get_connection_config`).
    """
    if isinstance(value, str):
        def _sub(m: re.Match) -> str:
            env = os.environ.get(m.group(1))
            if env is not None:
                return env
            return m.group(2) if m.group(2) is not None else m.group(0)
        return _ENV_PATTERN.sub(_sub, value)
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    return value  # numbers, booleans, None ...


def load_yaml(path: str | os.PathLike) -> Dict[str, Any]:
    """Read a YAML file (project-relative or absolute) and expand environment variables."""
    p = resolve_path(path)
    if not p.exists():
        raise ConfigError(f"Config file not found: {p}")
    with p.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return expand_env(data)


def get_connection_config(name: str) -> Dict[str, Any]:
    """Look up the named connection in config/connections.yml.

    The connections file can be switched per environment with the DC_CONNECTIONS_FILE
    environment variable (e.g. config/connections.qa.yml).

    NOTE: values like ``ENC(...)`` are returned still encrypted; they are decrypted later,
    in memory, by `connectors.factory.build_connector` just before connecting.
    """
    conn_file = os.environ.get("DC_CONNECTIONS_FILE", str(DEFAULT_CONNECTIONS_FILE))
    connections = load_yaml(conn_file).get("connections", {})
    if name not in connections:
        raise ConfigError(f"Connection '{name}' not found in {conn_file}. "
                          f"Available: {sorted(connections)}")
    cfg = dict(connections[name])

    # A leftover "${...}" means the env var was not set and had no default.
    unresolved = [k for k, v in cfg.items() if isinstance(v, str) and "${" in v]
    if unresolved:
        raise ConfigError(f"Connection '{name}': environment variables not set for {unresolved}")
    if "type" not in cfg:
        raise ConfigError(f"Connection '{name}' is missing the 'type' key")
    return cfg
