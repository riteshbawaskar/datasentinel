# 3. Configuration reference

All YAML files share two conventions: **relative paths resolve from the project root**, and
**`${VAR}` / `${VAR:default}`** are replaced from environment variables. Unknown *option* names raise an error,
so typos are caught immediately.

## 3.1 `config/connections.yml`

```yaml
connections:
  <name>:
    type: snowflake | oracle | databricks | sqlite      # excel and web_table are defined inline (see 3.2)
    ...type specific keys...
```

| type | keys |
|---|---|
| `snowflake` | `account, user, password, warehouse, database, schema, role`, optional `authenticator` (e.g. `externalbrowser`), `private_key_path` + `private_key_passphrase`, `session_parameters`, `use_arrow: true` (faster for big results; needs pyarrow) |
| `oracle` | `user, password` + (`host, port, service_name` **or** `dsn`), optional `thick_mode: true`, `lib_dir` |
| `databricks` | `server_hostname, http_path, access_token`, optional `catalog, schema` |
| `sqlite` | `path` (used by the demo and the tests) |

Secrets can be `${ENV}` references, `ENC(...)` encrypted tokens, or plain text (demo only).
A missing environment variable is reported as *"Connection 'x': environment variables not set for [...]"*.

## 3.2 Endpoints (`source:` / `target:`) - shared by compare and validation configs

```yaml
connection: snowflake_dev            # a name from connections.yml ...
# or inline:  type: excel, path: data/file.xlsx
query: SELECT ...                    # or:  query_file: sql/orders.sql   or:  table: SCHEMA.TABLE
schema: QA                           # any other key overrides the named connection's setting
```

Precedence for settings: **named connection < keys written inline**. A trailing `;` in a query is removed (Oracle).

**Excel endpoint** - every sheet is a SQL table (sheet names with spaces need double quotes):
```yaml
type: excel
path: data/customers.xlsx
query: SELECT * FROM "Customers" WHERE STATUS = 'ACTIVE'
# optional: sheet: Customers (load one sheet) | header_row: 3 (1-based) | read_as_text: true (keep leading zeros)
```
With no `query` and a single `sheet`, the whole sheet is returned.

**Web table endpoint** (Playwright reads an on-screen `<table>`):
```yaml
type: web_table
url: https://app.example.com/customers      # or a local file path
selector: "#customers"                       # CSS selector of the table (default: table)
header: true                                 # first row = column names (false -> COL_1, COL_2 ...)
actions:                                     # optional steps before reading (login, filters ...)
  - {fill: "#user", value: "qa_user"}
  - {fill: "#pwd",  value: "ENC(gAAAA...)"}  # encrypted values are decrypted automatically
  - {click: "#login"}
  - {wait_for: "#customers"}
```

## 3.3 Compare config (`compare_configs/*.yml`)

```yaml
name: Customers - Oracle vs Snowflake        # shown in the report
source: {...endpoint...}
target: {...endpoint...}
primary_key: [CUSTOMER_ID]                   # one or more columns (composite keys supported)
compare_fields: all                          # 'all' = every column on BOTH sides, or an explicit list
exclude_fields: [LOAD_TS]                    # only used with 'all'
column_mapping: {CUSTOMER_ID: CUST_ID}       # target_column: source_column (rename target to source names)
options: {...}
```

| option | default | meaning |
|---|---|---|
| `case_insensitive_columns` | `true` | match column **names** ignoring case |
| `trim_strings` | `true` | strip whitespace before comparing text |
| `ignore_case` | `false` | compare text **values** ignoring case |
| `null_equals_empty` | `true` | `NULL` equals `''`/whitespace (Oracle stores `''` as NULL) |
| `numeric_tolerance` | `0.0` | absolute tolerance, `\|a-b\| <= tol` is equal |
| `coerce_numeric` | `true` | `"10"`, `10`, `10.0`, `Decimal(10)` all equal (needs *every* value numeric) |
| `datetime_truncate` | none | e.g. `s` or `D` to drop sub-second / time precision |
| `max_report_rows` | `200` | rows shown per evidence table |

**Comparison rules.** Key parts are normalised so `101`, `101.0`, `"101"` and `" 101 "` match. Duplicate keys are
reported and only the first occurrence is compared. For each field on rows present in both sides: both empty =
equal; exactly one empty = different; otherwise values are compared as datetime → number → text (each stage is used
only if *all* values convert, so mixed columns fall back to text instead of failing).

## 3.4 Validation config (`validation_configs/*.yml`)

```yaml
name: ORDERS sanity checks
connection: snowflake_dev                    # the top level IS an endpoint
table: SALES.ORDERS                          # or query: / query_file:
max_report_rows: 200
checks:
  - {type: ..., ...}
```

Every check accepts `name:` (label in the report), `severity: error|warning` (warnings are recorded but never fail
the scenario) and `message:` (extra text shown on failure). `column:` / `columns:` accept a name, a list, or `all`.

| type | parameters | fails when |
|---|---|---|
| `row_count` | `min`, `max`, `equals` | row count outside the bounds |
| `columns_exist` | `columns` | a column is missing |
| `not_null` | `columns`, `treat_empty_as_null` (true) | NULL (or blank text) found |
| `unique` | `columns` (composite) | duplicate values |
| `numeric` | `columns`, `integer: true` | non-numeric (or non-integer) value |
| `date` | `columns`, `format` (strptime), `min`, `max` | unparsable or out-of-range date |
| `range` | `column(s)`, `min`, `max` | non-numeric or outside the range |
| `allowed_values` | `column(s)`, `values`, `case_sensitive` (true) | value not in the list |
| `regex` | `column(s)`, `pattern`, `full_match` (true) | value does not match |
| `length` | `column(s)`, `min`, `max` | text length outside the bounds |
| `expression` | `expression` (pandas expr, e.g. `SHIP_DATE >= ORDER_DATE`) | any row violates it |
| `sql` | `query`, `expect` (default 0) or `min`/`max`, optional `connection` | first cell of the query result is wrong |

NULLs are ignored by `numeric/date/range/allowed_values/regex/length` (use `not_null` to forbid them).
A check that cannot run (bad column, bad regex) is **reported as a failed checkpoint** with the error message.

## 3.5 Excel cell comparison (`cell_compare_configs/*.yml`)

```yaml
name: Sales v1 vs v2
source: {path: data/sales_v1.xlsx}
target: {path: data/sales_v2.xlsx}
sheets: all                       # or [Summary, Targets]  or  [{source: Q1, target: Q1_new}]
options:
  trim_strings: true
  ignore_case: false
  empty_equals_none: true         # '' equals an empty cell
  numeric_tolerance: 0.0
  compare_formulas: false         # false = cached values, true = formula text (=SUM(B2:E2))
  range: A1:H200                  # only compare this area
  ignore_ranges: [F1:F200, A1]    # skip cells (e.g. volatile columns)
  max_diffs_stored: 5000
  max_report_rows: 200
```

Cells empty on both sides are skipped (not counted). Sheets missing on one side are reported.

## 3.6 `config/ui.yml` (Playwright)

See [UI automation](07-ui-automation-playwright.md#settings).

## 3.7 `behave.ini`

| key | purpose |
|---|---|
| `format` / `outfiles` | `html` (branded BDD report) goes to the outfile, `pretty` to the console |
| `default_tags` | scenarios excluded unless you pass `--tags`: `@requires_creds`, `@requires_browser`, `@demo_fail` |
| `junit`, `junit_directory` | JUnit XML for CI |
| `[behave.formatters]` | registers `html` = `datasentinel.reporting.bdd_html:BrandedHTMLFormatter` |

## 3.8 behave user data (`-D key=value`)

| key | effect |
|---|---|
| `report_dir` | output folder (default `reports`; the parallel runner sets one per worker) |
| `report_title` | title in the standalone report |
| `env` | environment label shown in the report header |
| `browser` / `headless` | `chromium\|firefox\|webkit` / `true\|false` |
| `worker` | worker id (set by the runner) |
