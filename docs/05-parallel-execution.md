# 5. Parallel execution

behave is single-process, so DataSentinel parallelises by running **several independent behave processes** and
merging their results. Use the runner:

```bash
python run_tests.py                          # auto workers (min(4, CPUs)), one unit per feature file
python run_tests.py -w 8 --scheme scenario   # 8 workers, one unit per scenario
datasentinel-run -w 4                        # same thing, installed console command
```

## Options

| option | meaning |
|---|---|
| `paths...` | feature files or folders (default `features`) |
| `-w, --workers N\|auto` | number of parallel processes (capped at the number of units) |
| `--scheme feature\|scenario` | unit of parallelism (below) |
| `-t, --tags EXPR` | behave tag expression; repeat = AND, comma = OR; **replaces** `default_tags` |
| `-D KEY=VALUE` | behave user data passed to every worker (`-D browser=firefox`) |
| `--report-dir DIR`, `--title`, `--env` | output folder, report title, environment label |
| `--retries N` | re-run a failed unit up to N times (useful for flaky UI scenarios) |
| `--timeout S` | kill a unit after S seconds (reported as `timeout`) |
| `--fail-fast` | don't start new units after the first failure |
| `--list` | print the units and exit |

**Exit code:** `0` all units passed - `1` at least one failed - `2` nothing to run.

## Choosing a scheme

| scheme | unit | choose it when |
|---|---|---|
| `feature` (default) | one `.feature` file | many feature files of similar size; fewest start-ups (each unit = one process, one browser, one DB session) |
| `scenario` | one scenario / outline example | few features with many slow scenarios, or one giant feature file |

With `--retries`, remember a retried **unit** re-runs completely - in the `feature` scheme that includes scenarios that
already passed, so prefer `--scheme scenario --retries 1` for UI suites.

## How it works

```
discover units (same tag rules as behave)      python run_tests.py
        |
        v    ThreadPoolExecutor supervises N subprocesses
   [behave ... -D report_dir=<run>/workers/<unit> -D worker=<unit>]  x N
        |
        v    each worker writes: validation_report.html/.json, behave_report.html, junit/, behave.log
   merge validation_results.json of all workers  ->  one standalone report
```

* **Isolation:** `-D report_dir` gives every worker its own folder, so nothing is overwritten; each UI scenario gets a
  fresh browser context and each process its own Playwright driver (Playwright's sync API allows one per process).
* **Scheduling:** unit durations from earlier runs are stored in `reports/.durations.json`; the slowest units start
  first (longest-processing-time-first) to shorten the total wall time.
* **Crashes are visible:** a worker that dies before writing results appears in the merged report as an *error*
  scenario with the last lines of its log.

## Outputs

```
reports/
  validation_report.html      latest merged standalone report
  validation_results.json     latest merged results
  bdd_index.html              links to the standard BDD report of every unit
  runs/<timestamp>/           full history of this run
     validation_report.html   validation_results.json   bdd_index.html   run_summary.json
     junit/                   all JUnit XML files (flattened, prefixed with the unit id)
     workers/<unit>/          that worker's own reports + behave.log
```
The standard behave HTML report cannot be merged, so `bdd_index.html` links to each unit's own BDD report.

## Guidelines for parallel-safe suites

* Scenarios must be **independent** - no scenario may rely on another's side effects or ordering.
* Don't let two scenarios **write** to the same table/file. Read-only data checks (the main use case) are safe.
* Watch **concurrency limits**: every worker opens its own DB sessions (Snowflake warehouse queueing, Oracle
  session limits, Databricks SQL warehouse concurrency). Start with 3-4 workers and increase gradually.
* Memory: each worker holds its datasets in RAM; large comparisons x many workers add up.

## CI example

```yaml
- run: pip install -e ".[ui,snowflake]" && playwright install --with-deps chromium
- run: python run_tests.py -w 4 --scheme scenario --retries 1 -t "snowflake,ui" --env QA
  env: {DATASENTINEL_KEY: "${{ secrets.DATASENTINEL_KEY }}", DC_CONNECTIONS_FILE: config/connections.qa.yml}
- uses: actions/upload-artifact@v4
  if: always()
  with: {name: reports, path: reports/}
```
Publish `reports/runs/*/junit/*.xml` to your CI's test-result view.

Plain `behave` still works for a single process; use `-D report_dir=...` yourself if you start several by hand.
