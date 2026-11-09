# 8. Reports

Every run produces **two kinds of report**, both carrying the DataSentinel name and version.

## 1. Standalone validation report - `reports/validation_report.html`

One self-contained file (CSS, JS and screenshots inlined; works offline; follows dark mode).

* **Header:** framework name/version, report title, timestamp, environment, and for parallel runs workers/scheme/wall time.
* **Summary cards:** scenarios and checkpoints - passed / failed / warnings.
* **Filters:** *All*, *Failures only*, *Expand all*, *Collapse all*.
* **Per scenario:** status, tags, duration, worker, and "fact chips" (row counts, config path, matched rows, ...).
* **Per checkpoint:** `PASSED | FAILED | WARNING`, expected vs actual, message, and **evidence tables**
  (missing keys, per-column mismatch counts, field mismatches with source/target values, sample invalid rows, differing cells).
* **Screenshots** for UI scenarios (automatic on failure, or via the screenshot step).

Failed scenarios are opened automatically. Evidence is capped by `max_report_rows` (the table header shows
"showing 200 of 1,534").

## 2. Standard BDD report - `reports/behave_report.html`

The familiar behave report (features -> scenarios -> steps with timings) produced by
`behave-html-formatter`, subclassed in `datasentinel/reporting/bdd_html.py` to show the framework name.
For parallel runs open `reports/bdd_index.html`, which links each unit's report.

## Other files

| File | Use |
|---|---|
| `validation_results.json` | same data as the HTML, machine readable (dashboards, custom publishing) |
| `junit/*.xml` | CI test-result views |
| `ui_artifacts/` | Playwright traces / videos of failed scenarios (when enabled) |
| `runs/<ts>/run_summary.json` | per-unit status, duration, attempts (parallel runner) |

## Customising

* Name/tagline/version: `datasentinel/branding.py` (one place, flows into every report).
* Look and feel: the `_CSS` constant in `datasentinel/reporting/html_report.py`.
* Title/environment: `-D report_title="Release 42" -D env=QA` or `--title/--env` on the runner.
