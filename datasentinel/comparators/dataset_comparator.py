"""Primary-key based comparison of two recordsets (DataFrames).

Algorithm in one picture
------------------------
        source DF                         target DF
            |  normalise column names        |  (+ column_mapping rename)
            v                                v
   build composite key per row     build composite key per row
            |  (dedupe, remember duplicates)  |
            +----------------+----------------+
                             v
        key sets:  only-in-source | in-both | only-in-target
                             |
                     for each compared field, on the rows in BOTH:
                             v
              vectorised equality (_equal) -> mismatches table

Everything is vectorised with pandas (no row-by-row Python loops over the data), so it stays
fast for hundreds of thousands of rows.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, fields as dc_fields
from functools import reduce
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from datasentinel.config_loader import ConfigError

KEY_SEP = "|"            # separator when joining composite-key parts into one string
_NULL_KEY = "<NULL>"     # how a NULL key part is represented (so NULL == NULL when matching rows)
_INT_LIKE = re.compile(r"^-?\d+\.0+$")   # "101.0" / "101.00" -> treated as the integer 101


@dataclass
class CompareOptions:
    """Tunable comparison behaviour - the `options:` block of a compare YAML."""
    case_insensitive_columns: bool = True   # match column NAMES ignoring case (Oracle vs Snowflake)
    trim_strings: bool = True               # strip whitespace before comparing text values
    ignore_case: bool = False               # compare text VALUES ignoring case
    null_equals_empty: bool = True          # NULL == '' (Oracle stores '' as NULL)
    numeric_tolerance: float = 0.0          # absolute tolerance: |a-b| <= tol counts as equal
    coerce_numeric: bool = True             # "10" == 10 == 10.0 (Excel/UI text vs DB numbers)
    datetime_truncate: Optional[str] = None  # e.g. 's' or 'D' to drop sub-second / time precision
    max_report_rows: int = 200              # rows shown per evidence table in the HTML report

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompareOptions":
        known = {f.name for f in dc_fields(cls)}
        unknown = set(data) - known
        if unknown:   # fail loudly on typos like `numeric_tolerence`
            raise ConfigError(f"Unknown compare option(s): {sorted(unknown)}. Known: {sorted(known)}")
        return cls(**data)


@dataclass
class CompareResult:
    """Everything the steps/report need to know about one comparison."""
    name: str
    primary_key: List[str]
    compared_fields: List[str]
    source_count: int                    # raw row counts (before de-duplication)
    target_count: int
    matched_rows: int                    # rows in both datasets with NO field differences
    mismatched_rows: int                 # rows in both datasets with >= 1 differing field
    missing_in_target: pd.DataFrame      # keys (and source values) absent from the target
    missing_in_source: pd.DataFrame      # keys (and target values) absent from the source
    mismatches: pd.DataFrame             # long format: key cols + COLUMN, SOURCE_VALUE, TARGET_VALUE
    column_mismatch_counts: Dict[str, int]
    duplicates_source: pd.DataFrame
    duplicates_target: pd.DataFrame
    columns_only_in_source: List[str] = field(default_factory=list)
    columns_only_in_target: List[str] = field(default_factory=list)

    @property
    def common_rows(self) -> int:
        return self.matched_rows + self.mismatched_rows

    @property
    def mismatch_pct(self) -> float:
        """Share of COMMON rows that have at least one differing field."""
        return 100.0 * self.mismatched_rows / self.common_rows if self.common_rows else 0.0

    @property
    def passed(self) -> bool:
        return (self.source_count == self.target_count and self.missing_in_target.empty
                and self.missing_in_source.empty and self.mismatched_rows == 0
                and self.duplicates_source.empty and self.duplicates_target.empty)


class DatasetComparator:
    """Compare two DataFrames using the settings from a compare YAML file.

    Config keys used: name, primary_key, compare_fields ('all' | list), exclude_fields,
    column_mapping (target_col: source_col), options.
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.opts = CompareOptions.from_dict(config.get("options") or {})
        self.name = config.get("name", "Data comparison")
        self.pk = [self._col(c) for c in _as_list(config.get("primary_key"))]
        if not self.pk:
            raise ConfigError("'primary_key' is required in the compare config")
        self.fields_spec = config.get("compare_fields", "all")
        self.exclude = {self._col(c) for c in _as_list(config.get("exclude_fields"))}
        # YAML says  target_column: source_column ; we rename target columns to the source names.
        self.mapping = {self._col(t): self._col(s)
                        for t, s in (config.get("column_mapping") or {}).items()}

    # ------------------------------------------------------------------ public
    def compare(self, source: pd.DataFrame, target: pd.DataFrame) -> CompareResult:
        # 1) Normalise column names (upper-case) and apply the target->source rename.
        src = self._prepare(source)
        tgt = self._prepare(target, rename=self.mapping)
        self._require(src, self.pk, "source")
        self._require(tgt, self.pk, "target")

        # 2) Decide which fields to compare.
        if isinstance(self.fields_spec, str) and self.fields_spec.strip().lower() in ("all", "*"):
            # "all" = every column present on BOTH sides, except keys and excluded fields.
            fields = [c for c in src.columns
                      if c in tgt.columns and c not in self.pk and c not in self.exclude]
        else:
            fields = [self._col(f) for f in _as_list(self.fields_spec) if self._col(f) not in self.pk]
            self._require(src, fields, "source")   # explicit fields MUST exist on both sides
            self._require(tgt, fields, "target")

        # Columns that exist on one side only are reported (not silently ignored).
        only_src = [c for c in src.columns if c not in tgt.columns and c not in self.exclude]
        only_tgt = [c for c in tgt.columns if c not in src.columns and c not in self.exclude]

        # 3) Index both sides by composite key and collect duplicate keys.
        s_data, s_keys, s_dups = self._index(src, fields)
        t_data, t_keys, t_dups = self._index(tgt, fields)

        # 4) Set arithmetic on keys: rows in both, only in source, only in target.
        common = s_data.index.intersection(t_data.index, sort=False)
        miss_t = s_data.index.difference(t_data.index, sort=False)
        miss_s = t_data.index.difference(s_data.index, sort=False)

        # 5) Field-by-field comparison on the common rows. Both frames share the same index
        #    (the composite key), so the Series line up element for element.
        s_c, t_c = s_data.loc[common], t_data.loc[common]
        bad_any = pd.Series(False, index=common)        # row has >= 1 differing field
        diff_frames, counts = [], {}
        for f in fields:
            neq = ~_equal(s_c[f], t_c[f], self.opts)
            counts[f] = int(neq.sum())
            if counts[f]:
                bad_any |= neq
                # Long-format evidence rows: key columns + which column + both values.
                d = s_keys.loc[neq[neq].index].copy()
                d["COLUMN"] = f
                d["SOURCE_VALUE"] = s_c.loc[neq, f].values
                d["TARGET_VALUE"] = t_c.loc[neq, f].values
                diff_frames.append(d)

        key_cols = self.pk + ["COLUMN", "SOURCE_VALUE", "TARGET_VALUE"]
        mismatches = (pd.concat(diff_frames).reset_index(drop=True)
                      if diff_frames else pd.DataFrame(columns=key_cols))
        mismatched = int(bad_any.sum())

        return CompareResult(
            name=self.name, primary_key=self.pk, compared_fields=fields,
            source_count=len(source), target_count=len(target),
            matched_rows=len(common) - mismatched, mismatched_rows=mismatched,
            # "Missing" tables show the key parts followed by the available field values.
            missing_in_target=pd.concat([s_keys.loc[miss_t], s_data.loc[miss_t]], axis=1).reset_index(drop=True),
            missing_in_source=pd.concat([t_keys.loc[miss_s], t_data.loc[miss_s]], axis=1).reset_index(drop=True),
            mismatches=mismatches, column_mismatch_counts=counts,
            duplicates_source=s_dups, duplicates_target=t_dups,
            columns_only_in_source=only_src, columns_only_in_target=only_tgt,
        )

    # --------------------------------------------------------------- internals
    def _col(self, name: Any) -> str:
        """Canonical column name: stripped, and upper-cased when matching is case-insensitive."""
        name = str(name).strip()
        return name.upper() if self.opts.case_insensitive_columns else name

    def _prepare(self, df: pd.DataFrame, rename: Optional[Dict[str, str]] = None) -> pd.DataFrame:
        out = df.copy()                                  # never mutate the caller's data
        out.columns = [self._col(c) for c in out.columns]
        if rename:
            out = out.rename(columns=rename)
        return out

    @staticmethod
    def _require(df: pd.DataFrame, cols: List[str], side: str) -> None:
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise ConfigError(f"Column(s) {missing} not found in {side} dataset. "
                              f"Available: {list(df.columns)}")

    def _index(self, df: pd.DataFrame, fields: List[str]):
        """Return (data indexed by composite key, key-parts frame, duplicate-keys frame).

        * Each key part is normalised by `_key_part` so 101, 101.0, "101" and " 101 " all match.
        * Parts are joined with KEY_SEP into one string used as the row index.
        * If a key occurs more than once, ALL occurrences are reported as duplicates and only the
          first is kept for comparison (so one duplicate cannot explode into many false diffs).
        """
        keys = pd.DataFrame({k: df[k].map(_key_part) for k in self.pk})
        comp = reduce(lambda a, b: a + KEY_SEP + b, [keys[k] for k in self.pk])

        dup_mask = comp.duplicated(keep=False)           # True for every row of a duplicated key
        dups = keys[dup_mask].drop_duplicates()
        if not dups.empty:
            counts = comp[dup_mask].value_counts()
            dups = dups.assign(OCCURRENCES=comp[dup_mask].loc[dups.index].map(counts))
        dups = dups.reset_index(drop=True)

        keep = ~comp.duplicated(keep="first")            # first occurrence only
        data = df.loc[keep, fields].copy()
        data.index = comp[keep].values
        keys = keys[keep].copy()
        keys.index = comp[keep].values
        return data, keys, dups


# ------------------------------------------------------------------- helpers
def _as_list(value: Any) -> list:
    """None -> [], scalar -> [scalar], list/tuple -> list."""
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _key_part(value: Any) -> str:
    """Normalise one primary-key value to a comparable string."""
    try:
        if pd.isna(value):
            return _NULL_KEY
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    # Excel/pandas often turn integer keys into floats ("101.0"); make them match "101".
    return text.split(".")[0] if _INT_LIKE.match(text) else text


def _blank_mask(s: pd.Series, opts: CompareOptions) -> pd.Series:
    """True where a value counts as 'empty': NULL/NaN, or '' / whitespace when null_equals_empty."""
    mask = s.isna()
    if opts.null_equals_empty and (s.dtype == object or str(s.dtype).startswith("str")):
        mask = mask | s.map(lambda v: isinstance(v, str) and v.strip() == "")
    return mask.astype(bool)


def _equal(a: pd.Series, b: pd.Series, opts: CompareOptions) -> pd.Series:
    """Element-wise equality of two aligned Series, honouring the options.

    Truth table:  both empty -> equal | exactly one empty -> different | else compare values.
    """
    a_null, b_null = _blank_mask(a, opts), _blank_mask(b, opts)
    result = pd.Series(False, index=a.index)
    valid = ~(a_null | b_null)                      # rows where both sides hold a value
    if valid.any():
        result[valid] = _equal_non_null(a[valid], b[valid], opts)
    result[a_null & b_null] = True                  # NULL vs NULL is a match
    return result


def _equal_non_null(a: pd.Series, b: pd.Series, o: CompareOptions) -> pd.Series:
    """Compare two non-empty Series. Tries, in order: datetime -> numeric -> text.

    Each stage only applies if EVERY value converts cleanly; otherwise we fall through to the
    next, more permissive stage (text), so a mixed column never raises or silently mis-compares.
    """
    # Stage 1 - datetimes: used when either side is a real datetime column.
    if pd.api.types.is_datetime64_any_dtype(a) or pd.api.types.is_datetime64_any_dtype(b):
        x = pd.to_datetime(a, errors="coerce", utc=True)   # utc=True puts tz-aware/naive on one scale
        y = pd.to_datetime(b, errors="coerce", utc=True)
        if x.notna().all() and y.notna().all():
            if o.datetime_truncate:                       # e.g. ignore milliseconds
                x, y = x.dt.floor(o.datetime_truncate), y.dt.floor(o.datetime_truncate)
            return x == y

    # Stage 2 - numbers (also handles Decimal objects and numeric text like "12.50").
    if o.coerce_numeric:
        x, y = pd.to_numeric(a, errors="coerce"), pd.to_numeric(b, errors="coerce")
        if x.notna().all() and y.notna().all():
            if o.numeric_tolerance:
                return pd.Series(np.isclose(x.astype(float), y.astype(float),
                                            rtol=0, atol=o.numeric_tolerance), index=a.index)
            return x == y

    # Stage 3 - text, optionally trimmed / case-folded.
    xs, ys = a.astype(str), b.astype(str)
    if o.trim_strings:
        xs, ys = xs.str.strip(), ys.str.strip()
    if o.ignore_case:
        xs, ys = xs.str.lower(), ys.str.lower()
    return xs == ys
