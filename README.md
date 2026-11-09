# DataSentinel

**Data comparison, validation and UI verification, driven by BDD** (Python, behave, Playwright).

Prove that data is right - across Snowflake, Oracle, Databricks, Excel and what your web app actually displays -
using plain-English scenarios and YAML configs, with parallel execution, encrypted secrets and a compact
standalone HTML report.

```gherkin
Scenario: Oracle to Snowflake customer migration is complete
  Given the compare config "compare_configs/oracle_vs_snowflake.yml"
  When I run the data comparison
  Then the data comparison should pass
```

## Features

| | |
|---|---|
| **Data comparison** | primary-key based (single/composite), `compare_fields: all` or a list, column mapping, tolerance, trim/case/NULL rules; missing/extra/duplicate/mismatch evidence |
| **Sources** | Snowflake, Oracle, Databricks, **Excel read as a SQL recordset**, SQLite, and **web tables via Playwright** |
| **Data validation** | not-null, unique, numeric, date, range, allowed values, regex, length, row count, columns exist, pandas expressions, custom SQL; error/warning severity |
| **Excel cell-to-cell** | sheet by sheet, exact cell coordinates, ranges, ignore ranges, tolerance, formula or value mode |
| **UI automation** | Playwright steps, auto screenshots on failure, optional trace/video, UI-grid-vs-database comparison |
| **Parallel runs** | `python run_tests.py -w 4 [--scheme feature\|scenario] [--retries N]`, merged report, CI-friendly exit codes |
| **Encrypted secrets** | `password: ENC(...)` decrypted in memory at connect time; keygen / encrypt / rotate CLI |
| **Reports** | standalone `validation_report.html` + standard BDD report, JSON, JUnit - all branded |

## Quick start

```bash
pip install -e .                       # + extras as needed: ".[snowflake]" ".[oracle]" ".[databricks]" ".[ui]"
playwright install chromium            # only for UI scenarios
behave                                 # runs the credential-free demo scenarios
python run_tests.py -w 4               # the same, in parallel
pytest -q                              # framework self-tests
```
Open `reports/validation_report.html` (and `reports/behave_report.html`).
`behave --tags=demo_fail` shows how failures look; `behave --tags=ui` runs the browser scenarios.

## Encrypt a password

```bash
python -m datasentinel.security keygen                                   # once (key is git-ignored)
python -m datasentinel.security encrypt-config config/connections.yml    # encrypts plaintext secrets in place
```

## Documentation

| | |
|---|---|
| [1. Overview and architecture](docs/01-overview-and-architecture.md) | concepts, data flow, module map |
| [2. Getting started](docs/02-getting-started.md) | install, demo, first comparison |
| [3. Configuration reference](docs/03-configuration-reference.md) | every YAML key and option |
| [4. Writing scenarios](docs/04-writing-scenarios.md) | all steps, tags, outlines, custom steps |
| [5. Parallel execution](docs/05-parallel-execution.md) | runner, schemes, outputs, CI |
| [6. Security and encryption](docs/06-security-and-encryption.md) | master key, ENC() values, threat model |
| [7. UI automation (Playwright)](docs/07-ui-automation-playwright.md) | steps, settings, UI vs database |
| [8. Reports](docs/08-reports.md) | what each report contains |
| [9. Extending](docs/09-extending-the-framework.md) | new database, check, step, branding |
| [10. Troubleshooting and FAQ](docs/10-troubleshooting-and-faq.md) | common errors, verified scope |

## Layout

```
datasentinel/   framework package      features/   scenarios, steps, hooks
config/         connections.yml, ui.yml   compare_configs/ validation_configs/ cell_compare_configs/
data/           demo data              tests/      framework self-tests        docs/   documentation
```
