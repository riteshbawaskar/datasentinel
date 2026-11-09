# 6. Security: encrypting passwords in config files

## Summary

Passwords/tokens in YAML can be stored as `ENC(<token>)`. DataSentinel **decrypts them in memory only at the moment a
connection is built** - plaintext is never written back to disk, to the HTML/JSON reports, or to logs.

```yaml
snowflake_dev:
  type: snowflake
  user: QA_USER
  password: ENC(gAAAAABq8W6O...)        # decrypted automatically when connecting
```

## Setup (once)

```bash
python -m datasentinel.security keygen          # writes config/.datasentinel.key (mode 600, git-ignored)
python -m datasentinel.security keygen --print  # or print the key to store it in a CI secret instead
```

The **master key** is found in this order: `DATASENTINEL_KEY` env var, then the key file
(`DATASENTINEL_KEY_FILE` or `config/.datasentinel.key`).

## Everyday commands

| Command | Does |
|---|---|
| `python -m datasentinel.security encrypt` | prompts (hidden) and prints an `ENC(...)` token to paste into YAML |
| `python -m datasentinel.security encrypt-config config/connections.yml` | encrypts **every plaintext** `password, passwd, secret, access_token, token, api_key, private_key_passphrase, client_secret` value in place; keeps comments; writes a `.bak`; skips `${ENV}` and already-encrypted values. Add `--dry-run` to preview |
| `python -m datasentinel.security decrypt "ENC(...)"` | prints the secret (use sparingly) |
| `python -m datasentinel.security rotate FILE --old-key-file A --new-key-file B` | re-encrypts all `ENC()` values with a new key |

(`datasentinel-secrets` is the same CLI as an installed command.)

## Where decryption applies

* every key of a connection in `connections.yml`, and inline endpoint settings in compare/validation configs;
* nested values such as `web_table` `actions: [{fill: "#pwd", value: "ENC(...)"}]`;
* values that arrive through `${ENV_VAR}` and happen to contain `ENC(...)`.

The key is loaded **lazily**: configs without `ENC()` values need no key at all.

## How it works / what it protects

Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography` library. Each encryption uses a random IV, so encrypting the
same password twice yields different tokens; tampering or a wrong key raises
`SecurityError: Could not decrypt value: wrong master key or corrupted token`.

**Be clear about the threat model:** this keeps secrets out of plain sight in git, tickets, chat and screenshots.
Anyone who holds *both* the config file and the master key can decrypt. Therefore:

1. never commit the key (`.gitignore` already excludes `*.key`);
2. in CI, supply the key from the secret store as `DATASENTINEL_KEY`;
3. use a different key per environment, and rotate with `rotate` when people leave or a key leaks;
4. prefer short-lived credentials / SSO / key-pair auth where your platform supports them - encryption does not
   replace least-privilege read-only accounts for test users.

## Reports and logs

Connection settings are never put into `info` chips, checkpoints or JSON. Error messages come from the database
drivers; they normally do not echo passwords, but review them if you use a driver that does.
