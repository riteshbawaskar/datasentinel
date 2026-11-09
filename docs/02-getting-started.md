# 2. Getting started

## Install

```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .                      # the framework + core dependencies (behave, pandas, openpyxl, PyYAML, cryptography)
pip install -e ".[snowflake]"         # add only the drivers you need: snowflake | oracle | databricks | ui | dev
# UI automation additionally needs the browser binaries:
pip install -e ".[ui]" && playwright install chromium
```

`pip install -e .` matters: `behave.ini` references a framework class (the branded BDD formatter), which behave must
be able to import at start-up. Without installing, run `python -m behave ...` from the project root instead.

## Run the demo (no credentials needed)

```bash
python scripts/generate_demo_data.py   # (re)creates data/demo.db, Excel files and data/demo_site/
behave                                 # 6 demo scenarios -> reports/
python run_tests.py -w 4               # same, in parallel
pytest -q                              # framework self-tests
```

The demo compares a SQLite table with Excel files, validates a SQLite table, compares two workbooks and (with
Playwright) drives a local web page. Scenarios tagged `@demo_fail` fail **on purpose** so you can see how problems
look in the reports:

```bash
behave --tags=demo_fail                # intentional failures
behave --tags=ui                       # Playwright scenarios (needs `playwright install chromium`)
```

## Your first real comparison (5 minutes)

1. **Add a connection** to `config/connections.yml` (use `${ENV_VAR}` or an encrypted `ENC(...)` password -
   see [Security](06-security-and-encryption.md)).
2. **Create `compare_configs/orders_dev_vs_qa.yml`:**
   ```yaml
   name: ORDERS - DEV vs QA
   source: {connection: snowflake_dev, query: "SELECT ORDER_ID, STATUS, AMOUNT FROM SALES.ORDERS"}
   target: {connection: snowflake_qa,  query: "SELECT ORDER_ID, STATUS, AMOUNT FROM SALES.ORDERS"}
   primary_key: [ORDER_ID]
   compare_fields: all
   options: {numeric_tolerance: 0.0001}
   ```
3. **Add a scenario** to a `.feature` file:
   ```gherkin
   @snowflake
   Scenario: ORDERS are identical in DEV and QA
     Given the compare config "compare_configs/orders_dev_vs_qa.yml"
     When I run the data comparison
     Then the data comparison should pass
   ```
4. **Run it:** `behave --tags=snowflake` (or `python run_tests.py -t snowflake`).
5. **Open** `reports/validation_report.html`.

## Environment variables you will use

| Variable | Purpose |
|---|---|
| `SNOWFLAKE_*`, `ORACLE_*`, `DATABRICKS_*` | referenced by `${...}` in `connections.yml` |
| `DC_CONNECTIONS_FILE` | use another connections file per environment (e.g. `config/connections.qa.yml`) |
| `DATASENTINEL_KEY` / `DATASENTINEL_KEY_FILE` | master key for `ENC(...)` secrets |
| `DATASENTINEL_BROWSER`, `DATASENTINEL_HEADLESS` | set automatically from `-D browser=...` / `-D headless=...` |
