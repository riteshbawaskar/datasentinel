# 10. Troubleshooting and FAQ

| Symptom | Cause / fix |
|---|---|
| `behave: error: BAD_FORMAT=html (problem: ModuleNotFoundError)` | the framework isn't importable at start-up. Run `pip install -e .` or use `python -m behave` from the project root |
| `Connection 'x': environment variables not set for ['password']` | export the variable referenced as `${...}` in `connections.yml` (or give a default `${VAR:default}`) |
| `No master key found...` | a config contains `ENC(...)`; run `python -m datasentinel.security keygen` or set `DATASENTINEL_KEY` |
| `Could not decrypt value: wrong master key or corrupted token` | the value was encrypted with another key; re-encrypt, or `rotate` |
| `Playwright is not installed` / *Executable doesn't exist* | `pip install playwright && playwright install chromium` |
| *It looks like you are using Playwright Sync API inside the asyncio loop* | a second Playwright driver was started in one process; use the shared manager (`ui.session.shared_manager`) - the built-in steps and `web_table` connector already do |
| `Column(s) [...] not found in target dataset` | typo, or the query doesn't select it; remember names are matched case-insensitively and `column_mapping` is `target: source` |
| Mismatches on numbers like `10` vs `10.0` | keep `coerce_numeric: true` (default); for fixed decimals add `numeric_tolerance` |
| Mismatches only on `NULL` vs `''` | keep `null_equals_empty: true` (default) |
| Mismatches on dates between systems | use `datetime_truncate: s` (or `D`) to drop precision; Excel dates arrive as text through the SQL layer but are parsed when the other side is a datetime column |
| Leading zeros lost from Excel IDs | `read_as_text: true` on the Excel endpoint |
| Sheet name with spaces in Excel query | quote it: `SELECT * FROM "Sales Data"` |
| `No scenarios selected` (runner) | tags matched nothing; remember repeated `-t` are AND-ed - use commas for OR |
| Only the first failure is shown | behave stops at the first failing step; finish with `the data comparison should pass` / `all validations should pass` |
| Large comparisons are slow/heavy | select only needed columns in the queries, filter by date/partition, use `use_arrow: true` (Snowflake), lower `--workers` |
| Failed UI assertion takes long | it waits up to `timeout_ms`; lower it in `config/ui.yml` for fast feedback |

**Which parts have been verified?** The comparison, validation, Excel, reporting, encryption, runner and Playwright
layers are exercised by the demo scenarios (SQLite + Excel + a local web page in Chromium) and `pytest`. The Snowflake,
Oracle and Databricks connectors use each vendor's standard DB-API driver through the same code path, but need your
credentials to be exercised - run the `@requires_creds` scenarios against a non-production account first.

**Can I use a different test data source for CI?** Yes - point `DC_CONNECTIONS_FILE` at an environment-specific file.

**Does the framework modify my data?** No. It only reads (SELECT queries and page reads). Use read-only accounts.
