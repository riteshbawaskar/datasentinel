"""In-memory collector for everything the HTML/JSON reports show.

Data model (one run):

    ResultStore
      +-- ScenarioRecord  (one per behave scenario / outline example)
            +-- info          facts shown as "key value" chips (row counts, config path ...)
            +-- checkpoints   the individual validations, each PASSED / FAILED / WARNING
            |     +-- tables  evidence, e.g. sample mismatching rows
            +-- images        screenshots (UI failures) stored as base64 PNG
            +-- errors        step exception summaries

Because the whole store round-trips through JSON (`to_dict` / `load_dicts`), parallel workers
can each write their own JSON and the runner merges them into one report afterwards.
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

from datasentinel.branding import NAME, TAGLINE, VERSION

# Checkpoint statuses (WARNING never fails a scenario).
PASSED, FAILED, WARNING = "PASSED", "FAILED", "WARNING"


def _fmt(value: Any, limit: int = 200) -> str:
    """Stringify a cell for display: NULL for missing values, truncate very long text."""
    try:
        if pd.isna(value):
            return "NULL"
    except (TypeError, ValueError):   # pd.isna raises for list-like values
        pass
    text = str(value)
    return text if len(text) <= limit else text[:limit - 1] + "\u2026"


@dataclass
class Table:
    """A small evidence table attached to a checkpoint."""
    title: str
    columns: List[str]
    rows: List[List[str]]
    total_rows: int          # rows that exist; `rows` may be truncated to keep reports compact

    @classmethod
    def from_df(cls, title: str, df: pd.DataFrame, max_rows: int = 200) -> "Table":
        shown = df.head(max_rows)
        return cls(title, [str(c) for c in df.columns],
                   [[_fmt(v) for v in row] for row in shown.itertuples(index=False, name=None)],
                   len(df))


@dataclass
class Checkpoint:
    name: str
    status: str
    expected: str = ""
    actual: str = ""
    message: str = ""
    tables: List[Table] = field(default_factory=list)


@dataclass
class Image:
    """Screenshot kept inline (base64) so the HTML report stays a single standalone file."""
    title: str
    png_b64: str


@dataclass
class ScenarioRecord:
    feature: str
    name: str
    tags: List[str]
    status: str = "running"
    duration: float = 0.0
    info: Dict[str, str] = field(default_factory=dict)
    checkpoints: List[Checkpoint] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    images: List[Image] = field(default_factory=list)
    _t0: float = field(default_factory=time.time, repr=False)   # start time (not exported)

    def count(self, status: str) -> int:
        return sum(1 for c in self.checkpoints if c.status == status)


class ResultStore:
    """Collects results during a run. All recording methods are no-ops outside a scenario."""

    def __init__(self, title: str = "Test Report", environment: str = ""):
        self.title = title
        self.environment = environment
        self.run_info: Dict[str, str] = {}      # e.g. workers / scheme, shown in the header
        self.started = datetime.now()
        self.scenarios: List[ScenarioRecord] = []
        self.current: Optional[ScenarioRecord] = None

    # ---- lifecycle (called from behave hooks) ------------------------------------
    def start_scenario(self, feature: str, name: str, tags: List[str]) -> None:
        self.current = ScenarioRecord(feature, name, tags)
        self.scenarios.append(self.current)

    def end_scenario(self, status: str) -> None:
        if self.current:
            self.current.status = status
            self.current.duration = time.time() - self.current._t0
            self.current = None

    # ---- recording (called from steps) ---------------------------------------------
    def info(self, key: str, value: Any) -> None:
        if self.current:
            self.current.info[key] = str(value)

    def error(self, message: str) -> None:
        if self.current:
            self.current.errors.append(message)

    def attach_image(self, title: str, png: bytes) -> None:
        if self.current and png:
            self.current.images.append(Image(title, base64.b64encode(png).decode()))

    def checkpoint(self, name: str, status: str, expected: Any = "", actual: Any = "",
                   message: str = "", tables: Optional[List[Table]] = None) -> Optional[Checkpoint]:
        if not self.current:
            return None
        cp = Checkpoint(name, status, str(expected), str(actual), message, tables or [])
        self.current.checkpoints.append(cp)
        return cp

    # ---- summaries / export ---------------------------------------------------------
    def totals(self) -> Dict[str, int]:
        scen = [s.status for s in self.scenarios]
        cps = [c.status for s in self.scenarios for c in s.checkpoints]
        return {
            "scenarios": len(scen), "scenarios_passed": scen.count("passed"),
            "scenarios_failed": sum(1 for s in scen if s in ("failed", "error")),
            "scenarios_skipped": scen.count("skipped"),
            "checkpoints": len(cps), "checkpoints_passed": cps.count(PASSED),
            "checkpoints_failed": cps.count(FAILED), "checkpoints_warning": cps.count(WARNING),
        }

    def to_dict(self) -> Dict[str, Any]:
        def clean(s: ScenarioRecord) -> Dict[str, Any]:
            d = asdict(s)
            d.pop("_t0", None)          # internal timer, meaningless once exported
            return d
        return {"framework": NAME, "version": VERSION, "tagline": TAGLINE,
                "title": self.title, "environment": self.environment, "run_info": self.run_info,
                "started": self.started.isoformat(timespec="seconds"),
                "totals": self.totals(), "scenarios": [clean(s) for s in self.scenarios]}

    def write_json(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")

    # ---- merging (parallel runs) ----------------------------------------------------
    @classmethod
    def merge(cls, json_paths: Iterable[Path], title: str, environment: str = "",
              run_info: Optional[Dict[str, str]] = None) -> "ResultStore":
        """Combine the JSON files written by several workers into a single store."""
        store = cls(title, environment)
        store.run_info = dict(run_info or {})
        for path in json_paths:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            for s in data.get("scenarios", []):
                s["checkpoints"] = [
                    Checkpoint(**{**c, "tables": [Table(**t) for t in c.get("tables", [])]})
                    for c in s.get("checkpoints", [])]
                s["images"] = [Image(**i) for i in s.get("images", [])]
                store.scenarios.append(ScenarioRecord(**s))
        return store
