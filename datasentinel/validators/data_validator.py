"""Data sanity checks on a single recordset, driven by a validation YAML file.

Design
------
* A *check* is a function `fn(validator, df, spec) -> list[ValidationOutcome]` registered under
  a type name with `@register("name")`; the YAML `type:` key selects it.
* Most checks compute a boolean "bad row" mask and hand it to `DataValidator.bad_rows`, which
  turns it into an outcome (pass/fail, counts and a sample of the offending rows).
* A check can emit several outcomes (e.g. `not_null` on 5 columns -> 5 outcomes), so the report
  pinpoints exactly which column failed.

Add a new check type:

    @register("my_check")
    def _my_check(v, df, spec):
        bad = ...                         # boolean Series, True = invalid row
        return [v.bad_rows(spec, "my_check", spec.get("name", "x"), df, bad, "expected text")]
"""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

_HANDLERS: Dict[str, Callable] = {}


def register(name: str):
    def deco(fn):
        _HANDLERS[name] = fn
        return fn
    return deco


def supported_checks() -> List[str]:
    return sorted(_HANDLERS)


@dataclass
class ValidationOutcome:
    check_type: str
    name: str
    passed: bool
    severity: str            # 'error' | 'warning'
    expected: str
    actual: str
    message: str = ""
    total_rows: int = 0
    failed_rows: int = 0
    sample: Optional[pd.DataFrame] = None

    @property
    def label(self) -> str:
        return f"{self.check_type}: {self.name}"


class DataValidator:
    """Run the `checks:` list of a validation config against a DataFrame."""

    def __init__(self, config: Dict[str, Any], sql_runner: Optional[Callable[[Dict], pd.DataFrame]] = None,
                 max_sample_rows: int = 200):
        self.config = config
        self.sql_runner = sql_runner
        self.max_sample_rows = max_sample_rows

    def run(self, df: pd.DataFrame) -> List[ValidationOutcome]:
        # Work on an upper-cased copy so YAML column names match regardless of DB casing.
        df = df.copy()
        df.columns = [str(c).strip().upper() for c in df.columns]
        outcomes: List[ValidationOutcome] = []
        for spec in self.config.get("checks", []):
            ctype = spec.get("type", "")
            handler = _HANDLERS.get(ctype)
            if handler is None:
                outcomes.append(self._fail(spec, ctype or "?", "-", f"Unknown check type '{ctype}'. "
                                           f"Supported: {supported_checks()}"))
                continue
            try:
                outcomes.extend(handler(self, df, spec))
            except Exception as exc:  # a broken check (bad column, bad regex ...) is REPORTED as a failure,
                                      # never swallowed and never allowed to abort the other checks
                outcomes.append(self._fail(spec, ctype, str(spec.get("name") or spec.get("column") or spec.get("columns") or "-"),
                                           f"{type(exc).__name__}: {exc}"))
        return outcomes

    # --------------------------------------------------------------- helpers
    def _fail(self, spec, ctype, name, message) -> ValidationOutcome:
        return ValidationOutcome(ctype, name, False, spec.get("severity", "error"),
                                 "check executes", "error", message)

    def cols(self, df: pd.DataFrame, spec: Dict[str, Any]) -> List[str]:
        raw = spec.get("columns", spec.get("column"))
        if raw is None:
            raise ValueError("'column' or 'columns' is required")
        if isinstance(raw, str) and raw.strip() in ("all", "*"):
            return list(df.columns)
        cols = [str(c).strip().upper() for c in (raw if isinstance(raw, list) else [raw])]
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise ValueError(f"column(s) not found: {missing}. Available: {list(df.columns)}")
        return cols

    def bad_rows(self, spec, ctype, name, df, bad: pd.Series, expected: str) -> ValidationOutcome:
        """Build an outcome from a boolean mask where True marks an INVALID row."""
        bad = bad.fillna(False).astype(bool)
        n = int(bad.sum())
        return ValidationOutcome(
            ctype, name, n == 0, spec.get("severity", "error"), expected,
            f"{n} of {len(df)} rows invalid", spec.get("message", ""),
            len(df), n, df[bad].head(self.max_sample_rows) if n else None)


def _null_mask(s: pd.Series, treat_empty: bool = True) -> pd.Series:
    """True where a value is NULL/NaN (and, optionally, blank text)."""
    mask = s.isna()
    if treat_empty and (s.dtype == object or str(s.dtype).startswith("str")):
        mask = mask | s.map(lambda v: isinstance(v, str) and v.strip() == "")
    return mask.astype(bool)


def _label(spec, col):
    return spec.get("name") or col


# ------------------------------------------------------------------- checks
@register("row_count")
def _row_count(v, df, spec):
    n, parts, ok = len(df), [], True
    if "equals" in spec:
        parts.append(f"= {spec['equals']}"); ok &= n == spec["equals"]
    if "min" in spec:
        parts.append(f">= {spec['min']}"); ok &= n >= spec["min"]
    if "max" in spec:
        parts.append(f"<= {spec['max']}"); ok &= n <= spec["max"]
    return [ValidationOutcome("row_count", spec.get("name", "table"), bool(ok), spec.get("severity", "error"),
                              " and ".join(parts) or "any", str(n), spec.get("message", ""), n, 0 if ok else n)]


@register("columns_exist")
def _columns_exist(v, df, spec):
    wanted = [str(c).strip().upper() for c in spec["columns"]]
    missing = [c for c in wanted if c not in df.columns]
    return [ValidationOutcome("columns_exist", spec.get("name", "schema"), not missing, spec.get("severity", "error"),
                              f"columns present: {wanted}", "missing: " + (", ".join(missing) or "none"),
                              spec.get("message", ""), len(df), len(missing))]


@register("not_null")
def _not_null(v, df, spec):
    treat_empty = spec.get("treat_empty_as_null", True)
    return [v.bad_rows(spec, "not_null", _label(spec, c), df, _null_mask(df[c], treat_empty),
                       f"{c} has no NULL/blank values") for c in v.cols(df, spec)]


@register("unique")
def _unique(v, df, spec):
    cols = v.cols(df, spec)
    return [v.bad_rows(spec, "unique", _label(spec, "+".join(cols)), df, df.duplicated(subset=cols, keep=False),
                       f"({', '.join(cols)}) is unique")]


@register("numeric")
def _numeric(v, df, spec):
    out = []
    for c in v.cols(df, spec):
        conv = pd.to_numeric(df[c], errors="coerce")
        bad = ~_null_mask(df[c]) & conv.isna()
        if spec.get("integer"):
            bad |= conv.notna() & (conv % 1 != 0)
        out.append(v.bad_rows(spec, "numeric", _label(spec, c), df, bad,
                              f"{c} is {'an integer' if spec.get('integer') else 'numeric'}"))
    return out


@register("date")
def _date(v, df, spec):
    out = []
    for c in v.cols(df, spec):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if spec.get("format"):
                parsed = pd.to_datetime(df[c].astype(str).str.strip(), format=spec["format"], errors="coerce")
            else:
                parsed = pd.to_datetime(df[c], errors="coerce")
        bad = ~_null_mask(df[c]) & parsed.isna()
        exp = f"{c} is a valid date" + (f" ({spec['format']})" if spec.get("format") else "")
        if "min" in spec:
            bad |= parsed < pd.Timestamp(spec["min"]); exp += f", >= {spec['min']}"
        if "max" in spec:
            bad |= parsed > pd.Timestamp(spec["max"]); exp += f", <= {spec['max']}"
        out.append(v.bad_rows(spec, "date", _label(spec, c), df, bad, exp))
    return out


@register("range")
def _range(v, df, spec):
    out = []
    for c in v.cols(df, spec):
        conv = pd.to_numeric(df[c], errors="coerce")
        bad = ~_null_mask(df[c]) & conv.isna()
        parts = []
        if "min" in spec:
            bad |= conv < spec["min"]; parts.append(f">= {spec['min']}")
        if "max" in spec:
            bad |= conv > spec["max"]; parts.append(f"<= {spec['max']}")
        out.append(v.bad_rows(spec, "range", _label(spec, c), df, bad, f"{c} " + " and ".join(parts)))
    return out


@register("allowed_values")
def _allowed(v, df, spec):
    allowed = [str(x).strip() for x in spec["values"]]
    out = []
    for c in v.cols(df, spec):
        s = df[c].astype(str).str.strip()
        if not spec.get("case_sensitive", True):
            s, allowed_cmp = s.str.lower(), [a.lower() for a in allowed]
        else:
            allowed_cmp = allowed
        out.append(v.bad_rows(spec, "allowed_values", _label(spec, c), df, ~_null_mask(df[c]) & ~s.isin(allowed_cmp),
                              f"{c} in {allowed}"))
    return out


@register("regex")
def _regex(v, df, spec):
    pattern = re.compile(spec["pattern"])
    out = []
    for c in v.cols(df, spec):
        matcher = pattern.fullmatch if spec.get("full_match", True) else pattern.search
        ok = df[c].map(lambda x: True if pd.isna(x) else matcher(str(x)) is not None)
        out.append(v.bad_rows(spec, "regex", _label(spec, c), df, ~_null_mask(df[c]) & ~ok,
                              f"{c} matches /{spec['pattern']}/"))
    return out


@register("length")
def _length(v, df, spec):
    out = []
    for c in v.cols(df, spec):
        n = df[c].astype(str).str.len()
        bad, parts = pd.Series(False, index=df.index), []
        if "min" in spec:
            bad |= n < spec["min"]; parts.append(f">= {spec['min']}")
        if "max" in spec:
            bad |= n > spec["max"]; parts.append(f"<= {spec['max']}")
        out.append(v.bad_rows(spec, "length", _label(spec, c), df, ~_null_mask(df[c]) & bad,
                              f"length of {c} " + " and ".join(parts)))
    return out


@register("expression")
def _expression(v, df, spec):
    """Every row must satisfy a pandas expression, e.g. "SHIP_DATE >= ORDER_DATE"."""
    expr = spec["expression"]
    ok = df.eval(expr)
    return [v.bad_rows(spec, "expression", spec.get("name", expr), df, ~ok.fillna(False).astype(bool),
                       f"all rows satisfy: {expr}")]


@register("sql")
def _sql(v, df, spec):
    """Run a custom query; its first cell (a number) is compared with expect / min / max."""
    if v.sql_runner is None:
        raise RuntimeError("no sql_runner configured")
    value = v.sql_runner(spec).iloc[0, 0]
    value = float(value) if value is not None else 0.0
    checks, parts = [], []
    if "min" in spec or "max" in spec:
        if "min" in spec:
            checks.append(value >= spec["min"]); parts.append(f">= {spec['min']}")
        if "max" in spec:
            checks.append(value <= spec["max"]); parts.append(f"<= {spec['max']}")
    else:
        expect = spec.get("expect", 0)
        checks.append(value == expect); parts.append(f"= {expect}")
    ok = all(checks)
    return [ValidationOutcome("sql", spec.get("name", "custom query"), ok, spec.get("severity", "error"),
                              "result " + " and ".join(parts), f"{value:g}", spec.get("message", ""),
                              len(df), 0 if ok else int(value))]
