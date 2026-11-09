"""Parallel test runner:  python run_tests.py --workers 4     (or the `datasentinel-run` command)

Why a runner?  behave is single-process. To go parallel we start several *independent behave
processes* and give each its own output folder, then merge their results afterwards:

    discover units  ->  worker pool (N behave subprocesses)  ->  per-worker reports
                                                             ->  merge  ->  ONE standalone report

Parallel schemes
  feature   one unit per .feature file       (default; fewest browser/DB start-ups)
  scenario  one unit per runnable scenario   (best balance when a feature has many slow scenarios)

Why processes and not threads?  Each behave run keeps global state (context, result store,
Playwright driver), and Playwright's sync API allows only one driver per process. Separate
processes give perfect isolation with no locking.

Outputs (under <report-dir>/runs/<timestamp>/, latest copies also in <report-dir>/):
    validation_report.html   merged standalone report (all scenarios, checkpoints, screenshots)
    validation_results.json  merged machine-readable results
    bdd_index.html           index linking the standard BDD report of every unit
    junit/                   JUnit XML of every unit (for CI)
    run_summary.json         per-unit status/duration
    workers/<unit>/          that unit's own reports and behave.log
Exit code: 0 = every unit passed, 1 = at least one failed, 2 = nothing to run / bad usage.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from html import escape as e
from pathlib import Path
from typing import Dict, List, Optional

from datasentinel.branding import BANNER, NAME, TAGLINE, VERSION
from datasentinel.config_loader import BASE_DIR
from datasentinel.reporting.html_report import write_html_report
from datasentinel.reporting.result_store import ResultStore, ScenarioRecord

BDD_FORMATTER = "datasentinel.reporting.bdd_html:BrandedHTMLFormatter"


# ---------------------------------------------------------------------------- data model
@dataclass
class Unit:
    """One schedulable piece of work = one behave invocation."""
    id: str            # unique, filesystem-safe (used as the worker folder name)
    target: str        # what we hand to behave: "features/a.feature" or "features/a.feature:14"
    label: str         # human-readable (scenario name or feature file)


@dataclass
class UnitResult:
    unit: Unit
    status: str = "pending"        # passed | failed | timeout
    returncode: int = 0
    duration: float = 0.0
    attempts: int = 1
    worker_dir: str = ""
    has_results: bool = False      # did the worker manage to write validation_results.json?
    log_tail: List[str] = field(default_factory=list)


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-")[:70] or "unit"


# ------------------------------------------------------------------------------ discovery
def _feature_files(paths: List[str]) -> List[Path]:
    """Expand directories into their .feature files; keep explicit files; preserve order."""
    files: List[Path] = []
    for p in paths:
        path = (BASE_DIR / p) if not os.path.isabs(p) else Path(p)
        if path.is_dir():
            files += sorted(path.rglob("*.feature"))
        elif path.suffix == ".feature":
            files.append(path)
        else:
            raise SystemExit(f"Not a feature file or directory: {p}")
    return files


def discover_units(paths: List[str], scheme: str, tag_args: List[str]) -> List[Unit]:
    """Find what to run, honouring the same tag rules behave itself would apply.

    behave's Configuration reads behave.ini (including `default_tags`), and `--tags` given here
    overrides it - so the runner and a plain `behave` run always select the same scenarios.
    """
    from behave.configuration import Configuration
    from behave.parser import parse_file
    from behave.tag_expression import make_tag_expression

    expr = make_tag_expression(Configuration(["--no-color", *tag_args]).tags)
    units: List[Unit] = []
    for f in _feature_files(paths):
        feature = parse_file(str(f))
        rel = os.path.relpath(f, BASE_DIR)
        runnable = [s for s in feature.walk_scenarios() if s.should_run_with_tags(expr)]
        if not runnable:
            continue                                   # everything filtered out by tags
        if scheme == "feature":
            units.append(Unit(_slug(f.stem), rel, rel))
        else:                                          # one unit per scenario / outline example
            for s in runnable:
                units.append(Unit(f"{_slug(f.stem)}-L{s.line}", f"{rel}:{s.line}", f"{rel}: {s.name}"))
    return units


# ------------------------------------------------------------------------------ execution
def _run_unit(unit: Unit, run_dir: Path, tag_args: List[str], defines: List[str],
              timeout: Optional[int], retries: int) -> UnitResult:
    """Run one behave subprocess (with optional retries) and describe the outcome."""
    wdir = run_dir / "workers" / unit.id
    wdir.mkdir(parents=True, exist_ok=True)
    result = UnitResult(unit, worker_dir=str(wdir))
    cmd = [
        sys.executable, "-m", "behave", unit.target, "--no-color",
        "-f", BDD_FORMATTER, "-o", str(wdir / "behave_report.html"),   # standard BDD report
        "-f", "plain",                                                 # console text -> behave.log
        "--junit", "--junit-directory", str(wdir / "junit"),
        "-D", f"report_dir={wdir}",       # isolate every output of this worker
        "-D", f"worker={unit.id}",        # shown in the report, silences the per-run banner
        *[a for d in defines for a in ("-D", d)], *tag_args,
    ]
    t0 = time.time()
    for attempt in range(1, retries + 2):                 # 1 try + N retries
        result.attempts = attempt
        try:
            with open(wdir / "behave.log", "w", encoding="utf-8") as log:
                proc = subprocess.run(cmd, cwd=BASE_DIR, stdout=log, stderr=subprocess.STDOUT,
                                      timeout=timeout, env={**os.environ, "PYTHONPATH": str(BASE_DIR)})
            result.returncode = proc.returncode
            result.status = "passed" if proc.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            result.returncode, result.status = -1, "timeout"
        if result.status == "passed":
            break                                          # only retry failures
    result.duration = time.time() - t0
    result.has_results = (wdir / "validation_results.json").exists()
    if result.status != "passed":                          # keep a few log lines for the report
        lines = (wdir / "behave.log").read_text(encoding="utf-8", errors="replace").splitlines()
        result.log_tail = lines[-15:]
    return result


def _merge(run_dir: Path, results: List[UnitResult], title: str, env: str, info: Dict[str, str]) -> ResultStore:
    """Combine every worker's JSON; units that crashed before reporting become error scenarios."""
    jsons = [Path(r.worker_dir) / "validation_results.json" for r in results if r.has_results]
    store = ResultStore.merge(jsons, title, env, info)
    for r in results:
        if not r.has_results:      # e.g. import error / hard crash: make it visible, not silent
            rec = ScenarioRecord("(worker crashed)", r.unit.label, [], status="error")
            rec.errors = ["Worker produced no results. Last log lines:\n" + "\n".join(r.log_tail)]
            store.scenarios.append(rec)
    return store


def _bdd_index(results: List[UnitResult], base: Path, index_dir: Path, info: Dict[str, str]) -> str:
    """Index page linking each unit's standard BDD report (merging those HTMLs isn't possible)."""
    rows = []
    for r in sorted(results, key=lambda x: x.unit.id):
        link = os.path.relpath(Path(r.worker_dir) / "behave_report.html", index_dir).replace(os.sep, "/")
        cls = "ok" if r.status == "passed" else "bad"
        rows.append(f'<tr><td class="{cls}">{r.status.upper()}</td><td><a href="{e(link)}">{e(r.unit.label)}</a></td>'
                    f'<td>{r.duration:.1f}s</td><td>{r.attempts}</td></tr>')
    meta = " &middot; ".join(f"{e(k)}: {e(v)}" for k, v in info.items())
    return (f'<!doctype html><meta charset="utf-8"><title>{e(NAME)} - BDD reports</title>'
            '<style>body{font:13px system-ui;margin:16px}td,th{padding:3px 12px;text-align:left;'
            'border-bottom:1px solid #ddd}.ok{color:#15803d;font-weight:600}.bad{color:#b91c1c;font-weight:600}</style>'
            f'<h2>Data<b style="color:#15803d">Sentinel</b> v{e(VERSION)} &mdash; standard BDD reports</h2>'
            f'<p>{e(TAGLINE)}<br>{meta}</p><table><tr><th>Status</th><th>Unit (click to open its BDD report)</th>'
            f'<th>Time</th><th>Attempts</th></tr>{"".join(rows)}</table>')


# ------------------------------------------------------------------------------------ CLI
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="run_tests.py", description=f"{NAME} parallel test runner",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=(
        "examples:\n"
        "  python run_tests.py                          # 4 workers (auto), one per feature file\n"
        "  python run_tests.py -w 8 --scheme scenario   # one worker slot per scenario\n"
        "  python run_tests.py -t @snowflake -t ~@wip   # tag filters (same syntax as behave --tags)\n"
        "  python run_tests.py features/ui_automation.feature -t @ui -D browser=firefox --retries 1\n"
        "  python run_tests.py --list                   # show what would run\n"))
    p.add_argument("paths", nargs="*", default=["features"], help="feature files or folders (default: features)")
    p.add_argument("-w", "--workers", default="auto", help="parallel processes, or 'auto' (= min(4, CPUs))")
    p.add_argument("--scheme", choices=["feature", "scenario"], default="feature", help="unit of parallelism")
    p.add_argument("-t", "--tags", action="append", default=[], help="behave tag expression (repeatable)")
    p.add_argument("-D", "--define", action="append", default=[], metavar="KEY=VALUE", help="behave userdata")
    p.add_argument("--report-dir", default="reports", help="output folder (default: reports)")
    p.add_argument("--title", default="Data Validation Report", help="title shown in the merged report")
    p.add_argument("--env", default="", help="environment label shown in the report (e.g. QA)")
    p.add_argument("--retries", type=int, default=0, help="re-run a failed unit up to N times (flaky UI tests)")
    p.add_argument("--timeout", type=int, default=None, help="kill a unit after N seconds")
    p.add_argument("--fail-fast", action="store_true", help="don't start new units after a failure")
    p.add_argument("--list", action="store_true", help="list the units and exit")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    os.chdir(BASE_DIR)                                     # behave.ini is read from the project root
    tag_args = [f"--tags={t}" for t in args.tags]
    workers = max(1, min(4, os.cpu_count() or 1)) if args.workers == "auto" else max(1, int(args.workers))

    units = discover_units(args.paths, args.scheme, tag_args)
    if not units:
        print("No scenarios selected (check paths and --tags).", file=sys.stderr)
        return 2
    if args.list:
        print(f"{len(units)} unit(s) [{args.scheme} scheme]:")
        for u in units:
            print(f"  {u.id:45s} {u.label}")
        return 0

    report_root = BASE_DIR / args.report_dir
    run_dir = report_root / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    # Schedule the historically slowest units first (longest-processing-time-first balances load).
    hist_file = report_root / ".durations.json"
    hist: Dict[str, float] = json.loads(hist_file.read_text()) if hist_file.exists() else {}
    units.sort(key=lambda u: -hist.get(u.id, 0))

    workers = min(workers, len(units))                     # no point in idle workers
    print(BANNER)
    print(f"Running {len(units)} unit(s) on {workers} worker(s) [{args.scheme} scheme] -> {run_dir}\n")

    lock, done, stop = threading.Lock(), [0], threading.Event()
    results: List[UnitResult] = []

    def job(unit: Unit) -> Optional[UnitResult]:
        if stop.is_set():                                  # --fail-fast: skip units not yet started
            return None
        r = _run_unit(unit, run_dir, tag_args, args.define + [f"report_title={args.title}", f"env={args.env}"],
                      args.timeout, args.retries)
        with lock:                                         # keep progress lines un-interleaved
            done[0] += 1
            retry = f" (attempt {r.attempts})" if r.attempts > 1 else ""
            print(f"[{done[0]}/{len(units)}] {r.status.upper():7s} {r.unit.label}  ({r.duration:.1f}s){retry}")
        if r.status != "passed" and args.fail_fast:
            stop.set()
        return r

    wall0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:  # threads only supervise the subprocesses
        results = [r for r in pool.map(job, units) if r is not None]
    wall = time.time() - wall0

    # ---- merge and write outputs
    info = {"workers": str(workers), "scheme": args.scheme, "wall time": f"{wall:.1f}s"}
    store = _merge(run_dir, results, args.title, args.env, info)
    write_html_report(store, run_dir / "validation_report.html")
    store.write_json(run_dir / "validation_results.json")
    (run_dir / "bdd_index.html").write_text(_bdd_index(results, run_dir, run_dir, info), encoding="utf-8")
    (run_dir / "run_summary.json").write_text(json.dumps(
        {"framework": NAME, "version": VERSION, "workers": workers, "scheme": args.scheme, "wall_seconds": wall,
         "units": [{**asdict(r), "unit": asdict(r.unit)} for r in results]}, indent=2), encoding="utf-8")
    junit_dir = run_dir / "junit"
    junit_dir.mkdir(exist_ok=True)
    for r in results:                                      # flatten all JUnit files into one folder
        for x in (Path(r.worker_dir) / "junit").glob("*.xml"):
            shutil.copy(x, junit_dir / f"{r.unit.id}__{x.name}")

    # Latest-run convenience copies at stable paths in <report-dir>/
    shutil.copy(run_dir / "validation_report.html", report_root / "validation_report.html")
    shutil.copy(run_dir / "validation_results.json", report_root / "validation_results.json")
    (report_root / "bdd_index.html").write_text(_bdd_index(results, report_root, report_root, info), encoding="utf-8")
    hist_file.write_text(json.dumps({**hist, **{r.unit.id: r.duration for r in results}}))

    # ---- console summary
    t = store.totals()
    serial = sum(r.duration for r in results)
    failed = [r for r in results if r.status != "passed"]
    print(f"\n{'=' * 70}\n{NAME}: {t['scenarios_passed']} scenario(s) passed, {t['scenarios_failed']} failed | "
          f"checkpoints {t['checkpoints_passed']} passed, {t['checkpoints_failed']} failed, "
          f"{t['checkpoints_warning']} warning\nWall time {wall:.1f}s (sum of units {serial:.1f}s, "
          f"~{serial / wall:.1f}x parallel speed-up)" if wall else "")
    print(f"Merged report : {report_root / 'validation_report.html'}\nBDD reports   : {report_root / 'bdd_index.html'}")
    if failed:
        print("Failed units  : " + ", ".join(r.unit.id for r in failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
