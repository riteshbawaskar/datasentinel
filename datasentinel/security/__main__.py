"""Command line for secret management:  python -m datasentinel.security <command>

  keygen                  create the master key file (config/.datasentinel.key)
  encrypt [VALUE]         encrypt one value (prompts, hidden, if VALUE is omitted)
  decrypt TOKEN           decrypt one ENC(...) token (prints the secret - use with care)
  encrypt-config FILE     encrypt every plaintext password/token/secret in a YAML file
  rotate FILE --old-key-file A --new-key-file B
                          re-encrypt a file's ENC() values with a new master key
"""
import argparse
import getpass
import sys
from pathlib import Path

from datasentinel.security import crypto


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m datasentinel.security", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    k = sub.add_parser("keygen", help="create the master key file")
    k.add_argument("--out", help=f"key file path (default {crypto.DEFAULT_KEY_FILE})")
    k.add_argument("--force", action="store_true", help="overwrite an existing key file")
    k.add_argument("--print", dest="show", action="store_true",
                   help="print the key instead of writing a file (e.g. to store in a CI secret)")

    e = sub.add_parser("encrypt", help="encrypt a single value")
    e.add_argument("value", nargs="?")

    d = sub.add_parser("decrypt", help="decrypt a single ENC(...) token")
    d.add_argument("token")

    ec = sub.add_parser("encrypt-config", help="encrypt plaintext secrets in a YAML file")
    ec.add_argument("file")
    ec.add_argument("--dry-run", action="store_true")

    r = sub.add_parser("rotate", help="re-encrypt a file with a new master key")
    r.add_argument("file")
    r.add_argument("--old-key-file", required=True)
    r.add_argument("--new-key-file", required=True)

    a = p.parse_args(argv)
    try:
        if a.cmd == "keygen":
            key = crypto.generate_key()
            if a.show:
                print(key)
            else:
                path = crypto.save_key(key, Path(a.out) if a.out else None, overwrite=a.force)
                print(f"Master key written to {path}\nKeep it secret and out of git "
                      f"(or export it as {crypto.ENV_KEY} in CI).")
        elif a.cmd == "encrypt":
            value = a.value if a.value is not None else getpass.getpass("Value to encrypt: ")
            print(crypto.encrypt_value(value))
        elif a.cmd == "decrypt":
            print(crypto.decrypt_value(a.token))
        elif a.cmd == "encrypt-config":
            changed = crypto.encrypt_config_file(Path(a.file), dry_run=a.dry_run)
            verb = "Would encrypt" if a.dry_run else "Encrypted"
            print(f"{verb} {len(changed)} value(s) in {a.file}" + ("".join(f"\n  {c}" for c in changed)))
        elif a.cmd == "rotate":
            old = Path(a.old_key_file).read_text().strip().encode()
            new = Path(a.new_key_file).read_text().strip().encode()
            print(f"Re-encrypted {crypto.rotate_config_file(Path(a.file), old, new)} value(s) in {a.file}")
    except crypto.SecurityError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
