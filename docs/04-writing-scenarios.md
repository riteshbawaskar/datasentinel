# 4. Writing scenarios (step reference)

Scenarios live in `features/*.feature`. Tags control what runs:

| tag | meaning | default |
|---|---|---|
| `@requires_creds` | needs real Snowflake/Oracle/Databricks access | skipped |
| `@requires_browser` | needs Playwright browsers | skipped |
| `@demo_fail` | fails on purpose (shows failures in reports) | skipped |
| `@snowflake @oracle @databricks @excel @ui` | free-form filters | run |

`behave --tags=snowflake` **replaces** the default exclusions, so add them back if you want them:
`behave --tags=snowflake --tags=-demo_fail`. Several `--tags` are AND-ed; commas inside one are OR-ed.

> behave stops a scenario at its **first failing step**. When you want every problem in one run, end the scenario
> with a composite step (`the data comparison should pass`, `all validations should pass`).

## Data comparison

```gherkin
Given the compare config "compare_configs/x.yml"
When I run the data comparison
```
| Then step | Checks |
|---|---|
| `the source and target row counts should match` | raw row counts equal |
| `there should be no records missing in the target` | keys only in source |
| `there should be no records missing in the source` | keys only in target |
| `there should be no duplicate primary keys in the source` / `...in the target` | duplicate keys |
| `the source and target should have the same columns` | column sets identical |
| `there should be no field mismatches` | no differing field on common rows |
| `the field "NAME" should have no mismatches` | one field only |
| `the mismatch percentage should be at most 5` | share of common rows with a difference |
| `the data comparison should pass` | all of the above, all recorded |

## Data validation

```gherkin
Given the validation config "validation_configs/x.yml"
When I run the data validations
```
| Then step | Checks |
|---|---|
| `all validations should pass` | every configured check |
| `all "not_null" validations should pass` | one check type |
| `the validation "no_orphan_orders" should pass` | one named check |

## Excel cell comparison

```gherkin
Given the excel compare config "cell_compare_configs/x.yml"
When I run the excel cell comparison
```
| Then step | Checks |
|---|---|
| `both workbooks should contain the same sheets` | no sheet missing on either side |
| `there should be no cell differences` | whole comparison |
| `the sheet "Summary" should have no cell differences` | one sheet |
| `the cell "B2" in sheet "Summary" should match` | one cell |

## UI (Playwright) - see [chapter 7](07-ui-automation-playwright.md)

`I open the page "..."`, `I click "..."`, `I fill "..." with "..."`, `I select "..." from "..."`,
`I wait for "..." to be visible`, `I take a screenshot named "..."`, and assertions on title, visibility, text,
value, element count, and UI-vs-database values.

## Scenario Outlines (data-driven)

```gherkin
Scenario Outline: Every migrated table matches
  Given the compare config "<config>"
  When I run the data comparison
  Then the data comparison should pass
  Examples:
    | config                              |
    | compare_configs/customers.yml       |
    | compare_configs/orders.yml          |
```
Each example row is its own scenario in the report (and its own unit with `--scheme scenario`).

## Adding a custom step

```python
# features/steps/my_steps.py
from behave import then
from datasentinel.bdd import checkpoint

@then("the source should contain at least {n:d} rows")
def step(context, n):
    actual = context.result.source_count
    checkpoint(context, f"Source has >= {n} rows", actual >= n, f">= {n}", actual)
```
`checkpoint(context, name, passed, expected, actual, message="", tables=None, severity="error", raise_on_fail=True)`
records the result in the report and raises `AssertionError` on failure. Use `severity="warning"` for non-blocking
findings and `raise_on_fail=False` to record several checkpoints before failing once.
