# 7. UI automation with Playwright

## Install

```bash
pip install -e ".[ui]"
playwright install chromium        # or firefox / webkit; in CI: playwright install --with-deps chromium
```

UI scenarios are tagged `@ui @requires_browser` (skipped by default so suites run without browsers). Run them with
`behave --tags=ui` or `python run_tests.py -t ui`.

## Settings

`config/ui.yml` (all optional):

| key | default | meaning |
|---|---|---|
| `browser` | `chromium` | `chromium \| firefox \| webkit` |
| `headless` | `true` | `false` to watch the browser |
| `base_url` | `""` | relative URLs in steps are appended to it |
| `timeout_ms` | `5000` | default wait for elements/navigation (also how long a failing assertion waits) |
| `viewport` | 1366x768 | window size |
| `slow_mo_ms` | `0` | slow actions down for debugging |
| `screenshot_on_failure` | `true` | full-page PNG embedded in the HTML report |
| `trace_on_failure` | `false` | keep `reports/ui_artifacts/<scenario>_trace.zip` (`playwright show-trace file.zip`) |
| `record_video` | `false` | keep a `.webm` for failed scenarios |

Override per run: `behave -D browser=firefox -D headless=false`.

## Steps

Selectors are Playwright selectors: CSS (`#id`, `.cls`, `table tr`), text (`text=Save`), role
(`role=button[name='Save']`), test ids (`[data-testid=submit]`).

| Step | |
|---|---|
| `Given I open the page "URL"` | `http(s)://`, a project file path (opened as `file://`), or a path appended to `base_url` |
| `When I click "SEL"` / `I fill "SEL" with "TEXT"` / `I select "OPTION" from "SEL"` | actions |
| `When I wait for "SEL" to be visible` | explicit wait |
| `When I take a screenshot named "NAME"` | attaches a screenshot to the report |
| `Then the page title should be "TITLE"` | |
| `Then the element "SEL" should be visible` | |
| `Then the element "SEL" should contain the text "TEXT"` | |
| `Then the element "SEL" should have the value "VALUE"` | inputs |
| `Then there should be 30 elements matching "SEL"` | |
| `Then the text of "SEL" should equal the value returned by "SQL" on connection "NAME"` | UI vs database single value (numbers compared numerically, so `1,234.50` = `1234.5`) |

Assertions use Playwright's auto-retrying `expect`, and every one is recorded as a checkpoint (expected vs actual).
On a failed step a **screenshot is captured automatically** and embedded in the report.

## Compare a UI grid with the database

Use the `web_table` connector as either side of a normal compare config - same engine, same steps, same report:

```yaml
source: {connection: snowflake_dev, query: "SELECT ID, NAME, STATUS FROM CRM.CUSTOMERS"}
target:
  type: web_table
  url: https://app.example.com/customers
  selector: "#customers"
  actions:
    - {fill: "#user", value: "qa_user"}
    - {fill: "#pwd",  value: "ENC(gAAAA...)"}
    - {click: "#login"}
    - {wait_for: "#customers"}
primary_key: [ID]
options: {numeric_tolerance: 0.01}      # UI text such as "12.50" compares numerically with DB numbers
```
```gherkin
@ui @requires_browser
Scenario: The customer grid shows what the database holds
  Given the compare config "compare_configs/customers_db_vs_ui.yml"
  When I run the data comparison
  Then the data comparison should pass
```
Table cells are read as text (whitespace collapsed, nested tables ignored); pagination is not followed - filter the page
with `actions` or compare one page at a time.

## Architecture notes

* One **browser per process**, one **isolated context + page per scenario** (clean cookies/storage).
* Playwright's sync API allows a **single driver per process**, so `ui/session.py` keeps one shared `BrowserManager`;
  the `web_table` connector takes its own *scratch context* from it and never disturbs a scenario's page.
* Parallel workers are separate processes, so each has its own driver - UI suites parallelise safely.
* The browser starts lazily on the first UI step; non-UI scenarios pay nothing.

## Adding your own UI steps

```python
# features/steps/my_ui_steps.py
from behave import when
from datasentinel.ui.session import get_page

@when('I log in as "{user}"')
def step(context, user):
    page = get_page(context)               # Playwright Page for this scenario
    page.fill("#user", user); page.click("#login")
```
For page objects, keep them in `datasentinel/ui/pages/` and build them from `get_page(context)`.
