"""behave hooks - the lifecycle wiring of the framework.

Order of execution (behave):  before_all -> [before_scenario -> steps (+after_step each)
-> after_scenario]* -> after_all

What this file does
  * creates one ResultStore per process and fills it with scenario/checkpoint data;
  * on UI failures grabs a screenshot and (optionally) keeps trace/video;
  * writes the standalone HTML + JSON reports at the end;
  * supports parallel workers: the runner passes `-D report_dir=...` so every worker writes into
    its own folder and results never collide (see docs/05-parallel-execution.md).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Make the `datasentinel` package importable from step files no matter where behave is started.
sys.path.insert(0, str(ROOT))

from datasentinel.branding import BANNER                         # noqa: E402
from datasentinel.reporting.html_report import write_html_report  # noqa: E402
from datasentinel.reporting.result_store import ResultStore        # noqa: E402
from datasentinel.ui import session as ui_session                  # noqa: E402


def before_all(context):
    """Runs once per behave process: read `-D` options and create the result store."""
    ud = context.config.userdata
    # report_dir may be relative to the project or absolute (the parallel runner uses absolute).
    context.report_dir = ROOT / ud.get("report_dir", "reports")
    context.report_dir.mkdir(parents=True, exist_ok=True)

    # `-D browser=firefox -D headless=false` -> picked up by ui.browser.UiSettings.load()
    # (via env vars, so code running outside a step - e.g. the web_table connector - sees it too).
    if ud.get("browser"):
        os.environ["DATASENTINEL_BROWSER"] = ud["browser"]
    if ud.get("headless"):
        os.environ["DATASENTINEL_HEADLESS"] = ud["headless"]

    context.worker = ud.get("worker", "")          # set by the parallel runner, "" for a plain run
    context.store = ResultStore(title=ud.get("report_title", "Data Validation Report"),
                                environment=ud.get("env", ""))
    if not context.worker:
        print(BANNER)


def before_scenario(context, scenario):
    """Open a new record in the report for this scenario."""
    context.store.start_scenario(scenario.feature.name, scenario.name,
                                 [str(t) for t in scenario.tags])
    if context.worker:
        context.store.info("Worker", context.worker)


def after_step(context, step):
    """On a failed step: remember the error line and, for UI scenarios, grab a screenshot."""
    if step.status.name != "failed":
        return
    detail = (step.error_message or "").strip().splitlines()
    context.store.error(f"{step.keyword} {step.name}\n{detail[-1] if detail else 'step failed'}")

    png = ui_session.capture_failure_screenshot(context)   # None unless a browser page is open
    if png:
        context.store.attach_image(f"Failure: {step.name}", png)


def after_scenario(context, scenario):
    """Close the scenario's browser page (keeping trace/video on failure) and finish the record."""
    failed = scenario.status.name in ("failed", "error")
    kept = ui_session.end_scenario(context, failed, scenario.name)
    if kept:                                                # trace.zip / .webm kept for failures
        context.store.info("Artifacts", ", ".join(a.name for a in kept))
    context.store.end_scenario(scenario.status.name)


def after_all(context):
    """Shut the browser down and write the standalone report + machine-readable JSON."""
    ui_session.shutdown()
    html = write_html_report(context.store, context.report_dir / "validation_report.html")
    context.store.write_json(context.report_dir / "validation_results.json")
    if not context.worker:
        print(f"\nValidation report : {html}")
