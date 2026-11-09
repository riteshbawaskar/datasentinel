"""Symmetric encryption for secrets stored in YAML configs.

How it works
------------
* A *master key* (Fernet key: 32 random bytes, url-safe base64) lives OUTSIDE version control:
    1. environment variable  DATASENTINEL_KEY            (best for CI/CD secret stores), or
    2. a key file            config/.datasentinel.key    (override path: DATASENTINEL_KEY_FILE)
* A secret is stored in YAML as  ENC(<fernet token>)  e.g.
      password: ENC(gAAAAABl...)
* The token is decrypted **in memory, only when a connection is actually built**. Plaintext is
  never written back to disk, to reports, or to logs.

Fernet = AES-128-CBC + HMAC-SHA256 with a random IV per encryption, so encrypting the same
password twice gives different tokens, and any tampering is detected on decrypt.

Threat model (be honest with yourself): this keeps passwords out of plain sight in git history,
tickets and screenshots. Anyone holding BOTH the config file and the master key can decrypt, so
guard the key like a password (CI secret store / vault, file mode 600, never committed).
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken

from datasentinel.config_loader import BASE_DIR

ENV_KEY = "DATASENTINEL_KEY"
ENV_KEY_FILE = "DATASENTINEL_KEY_FILE"
DEFAULT_KEY_FILE = BASE_DIR / "config" / ".datasentinel.key"

# Matches the whole string  ENC(...)  - used to recognise encrypted values.
_ENC_RE = re.compile(r"^ENC\((?P<token>.+)\)$", re.DOTALL)
# Same, but searches inside a larger text (used by key rotation over raw file text).
_ENC_ANYWHERE = re.compile(r"ENC\((?P<token>[A-Za-z0-9_\-=]+)\)")

# YAML keys whose plaintext values `encrypt-config` will encrypt automatically.
SENSITIVE_KEYS = ("password", "passwd", "secret", "access_token", "token",
                  "api_key", "private_key_passphrase", "client_secret")


class SecurityError(Exception):
    """Raised for missing keys, bad tokens or other secret-handling problems."""


# ----------------------------------------------------------------------------- keys
def generate_key() -> str:
    """Create a fresh master key (returned as text)."""
    return Fernet.generate_key().decode()


def key_file_path() -> Path:
    return Path(os.environ.get(ENV_KEY_FILE, DEFAULT_KEY_FILE)).expanduser()


def save_key(key: str, path: Optional[Path] = None, overwrite: bool = False) -> Path:
    """Write *key* to a file readable only by the current user (mode 600 on POSIX)."""
    path = Path(path) if path else key_file_path()
    if path.exists() and not overwrite:
        raise SecurityError(f"Key file already exists: {path} (use --force to overwrite; "
                            f"existing ENC() values would become undecryptable)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key + "\n", encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:  # e.g. Windows - best effort only
        pass
    return path


def load_key(path: Optional[Path] = None) -> bytes:
    """Return the master key: explicit path > env var > default key file."""
    if path is None and os.environ.get(ENV_KEY):
        return os.environ[ENV_KEY].strip().encode()
    kf = Path(path) if path else key_file_path()
    if kf.exists():
        return kf.read_text(encoding="utf-8").strip().encode()
    raise SecurityError(
        f"No master key found. Set {ENV_KEY}, or create a key file at {kf} with:\n"
        f"    python -m datasentinel.security keygen")


def _fernet(key: Optional[bytes] = None) -> Fernet:
    try:
        return Fernet(key or load_key())
    except ValueError as exc:  # malformed key
        raise SecurityError(f"Master key is not a valid Fernet key: {exc}") from exc


# ------------------------------------------------------------------- values / trees
def is_encrypted(value: Any) -> bool:
    return isinstance(value, str) and _ENC_RE.match(value.strip()) is not None


def encrypt_value(plain: str, key: Optional[bytes] = None) -> str:
    """Encrypt *plain* and return it wrapped as  ENC(...)."""
    return f"ENC({_fernet(key).encrypt(plain.encode()).decode()})"


def decrypt_value(value: str, key: Optional[bytes] = None) -> str:
    """Decrypt an  ENC(...)  string. Plain strings are returned unchanged."""
    m = _ENC_RE.match(value.strip())
    if not m:
        return value
    try:
        return _fernet(key).decrypt(m.group("token").encode()).decode()
    except InvalidToken as exc:
        raise SecurityError("Could not decrypt value: wrong master key or corrupted token") from exc


def decrypt_tree(obj: Any) -> Any:
    """Return a copy of a dict/list structure with every ENC(...) string decrypted.

    The key is loaded lazily, so configs without encrypted values need no key at all.
    """
    if isinstance(obj, dict):
        return {k: decrypt_tree(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [decrypt_tree(v) for v in obj]
    if is_encrypted(obj):
        return decrypt_value(obj)
    return obj


# --------------------------------------------------------------- config file helpers
# Line-based so YAML comments/formatting survive (a YAML round-trip would drop them).
_LINE_RE = re.compile(
    r"^(?P<indent>\s*(?:-\s+)?)(?P<key>" + "|".join(SENSITIVE_KEYS) + r")\s*:\s*"
    r"(?P<value>\"[^\"]*\"|'[^']*'|[^#\n]*?)\s*(?P<comment>#.*)?$", re.IGNORECASE)


def encrypt_config_file(path: Path, dry_run: bool = False) -> list[str]:
    """Encrypt plaintext sensitive values in a YAML file, in place (a .bak copy is kept).

    Skips empty values, ${ENV} placeholders and values that are already ENC(...).
    Returns the list of keys that were (or would be) encrypted, e.g. ['line 12: password'].
    """
    path = Path(path)
    changed, out = [], []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        m = _LINE_RE.match(line)
        value = m.group("value").strip().strip("'\"") if m else ""
        if m and value and not value.startswith("${") and not is_encrypted(value):
            token = encrypt_value(value)
            comment = f"  {m.group('comment')}" if m.group("comment") else ""
            line = f"{m.group('indent')}{m.group('key')}: {token}{comment}"
            changed.append(f"line {n}: {m.group('key')}")
        out.append(line)
    if changed and not dry_run:
        path.with_suffix(path.suffix + ".bak").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return changed


def rotate_config_file(path: Path, old_key: bytes, new_key: bytes) -> int:
    """Re-encrypt every ENC(...) token in a file from *old_key* to *new_key*. Returns the count."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    count = 0

    def _swap(m: re.Match) -> str:
        nonlocal count
        count += 1
        return encrypt_value(decrypt_value(m.group(0), old_key), new_key)

    new_text = _ENC_ANYWHERE.sub(_swap, text)
    if count:
        path.with_suffix(path.suffix + ".bak").write_text(text, encoding="utf-8")
        path.write_text(new_text, encoding="utf-8")
    return count
