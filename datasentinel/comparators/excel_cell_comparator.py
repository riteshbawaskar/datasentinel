"""Cell-to-cell comparison of two Excel workbooks (sheet by sheet, coordinate by coordinate).

Flow:  load both workbooks (openpyxl) -> pair up sheets -> read each sheet into a grid of
values -> walk every (row, column) -> normalise both values -> record a diff with its A1-style
coordinate when they differ.  Cells that are empty on BOTH sides are skipped (not counted).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, fields as dc_fields
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import range_boundaries

from datasentinel.config_loader import ConfigError, resolve_path


@dataclass
class CellOptions:
    trim_strings: bool = True
    ignore_case: bool = False
    empty_equals_none: bool = True         # '' == empty cell
    numeric_tolerance: float = 0.0
    compare_formulas: bool = False         # False = compare cached values, True = formula text
    range: Optional[str] = None            # e.g. "A1:H200" - limit the compared area
    ignore_ranges: List[str] = field(default_factory=list)   # e.g. ["H1:H500", "A1"]
    max_diffs_stored: int = 5000
    max_report_rows: int = 200

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CellOptions":
        known = {f.name for f in dc_fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ConfigError(f"Unknown cell-compare option(s): {sorted(unknown)}. Known: {sorted(known)}")
        return cls(**data)


@dataclass
class SheetResult:
    source_sheet: str
    target_sheet: str
    source_dims: str
    target_dims: str
    cells_compared: int = 0
    diff_count: int = 0
    diffs: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.source_sheet if self.source_sheet == self.target_sheet \
            else f"{self.source_sheet} \u2192 {self.target_sheet}"


@dataclass
class CellCompareResult:
    name: str
    sheets: List[SheetResult]
    missing_in_target: List[str]
    missing_in_source: List[str]

    @property
    def total_diffs(self) -> int:
        return sum(s.diff_count for s in self.sheets)

    @property
    def cells_compared(self) -> int:
        return sum(s.cells_compared for s in self.sheets)

    @property
    def passed(self) -> bool:
        return not (self.total_diffs or self.missing_in_target or self.missing_in_source)

    def sheet(self, name: str) -> Optional[SheetResult]:
        return next((s for s in self.sheets if name in (s.source_sheet, s.target_sheet)), None)


class ExcelCellComparator:
    """Config keys: name, source.path, target.path, sheets ('all' | [names] |
    [{source:, target:}]), options."""

    def __init__(self, config: Dict[str, Any]):
        self.cfg = config
        self.opts = CellOptions.from_dict(config.get("options") or {})
        self._ignored = [range_boundaries(r) for r in self.opts.ignore_ranges]
        self._area = range_boundaries(self.opts.range) if self.opts.range else None

    def compare(self) -> CellCompareResult:
        # data_only=True returns the values Excel last calculated; False returns formula text (=SUM(...)).
        data_only = not self.opts.compare_formulas
        wb_s = load_workbook(resolve_path(self.cfg["source"]["path"]), data_only=data_only)
        wb_t = load_workbook(resolve_path(self.cfg["target"]["path"]), data_only=data_only)
        # Which sheets to compare, and which exist on only one side (reported as problems).
        pairs, miss_t, miss_s = self._sheet_pairs(wb_s.sheetnames, wb_t.sheetnames)
        results = [self._compare_sheet(wb_s[s], wb_t[t]) for s, t in pairs]
        return CellCompareResult(self.cfg.get("name", "Excel cell comparison"),
                                 results, miss_t, miss_s)

    # ----------------------------------------------------------------- sheets
    def _sheet_pairs(self, src: List[str], tgt: List[str]) -> Tuple[List[Tuple[str, str]], List[str], List[str]]:
        spec = self.cfg.get("sheets", "all")
        if isinstance(spec, str) and spec.lower() == "all":
            pairs = [(n, n) for n in src if n in tgt]
            return pairs, [n for n in src if n not in tgt], [n for n in tgt if n not in src]
        pairs, miss_t, miss_s = [], [], []
        for item in (spec if isinstance(spec, list) else [spec]):
            s, t = (item["source"], item["target"]) if isinstance(item, dict) else (item, item)
            if s not in src:
                miss_s.append(s)
            elif t not in tgt:
                miss_t.append(t)
            else:
                pairs.append((s, t))
        return pairs, miss_t, miss_s

    def _grid(self, ws) -> Tuple[List[tuple], int, int]:
        if self._area:                       # user restricted the compared range (options.range)
            c1, r1, c2, r2 = self._area
        else:                                # default: the sheet's whole used area, from A1
            c1, r1, c2, r2 = 1, 1, max(ws.max_column, 1), max(ws.max_row, 1)
        rows = list(ws.iter_rows(min_row=r1, max_row=r2, min_col=c1, max_col=c2, values_only=True))
        return rows, r1, c1

    def _compare_sheet(self, ws_s, ws_t) -> SheetResult:
        g_s, r0, c0 = self._grid(ws_s)
        g_t, _, _ = self._grid(ws_t)
        res = SheetResult(ws_s.title, ws_t.title,
                          f"{ws_s.max_row}x{ws_s.max_column}", f"{ws_t.max_row}x{ws_t.max_column}")
        # Sheets can differ in size: iterate over the larger area; missing cells read as None.
        n_rows = max(len(g_s), len(g_t))
        n_cols = max((len(r) for r in g_s + g_t), default=0)
        for r in range(n_rows):
            row_s = g_s[r] if r < len(g_s) else ()
            row_t = g_t[r] if r < len(g_t) else ()
            for c in range(n_cols):
                excel_row, excel_col = r0 + r, c0 + c      # translate grid index -> real Excel position
                if self._is_ignored(excel_row, excel_col):
                    continue
                a = row_s[c] if c < len(row_s) else None
                b = row_t[c] if c < len(row_t) else None
                if a is None and b is None:
                    continue
                res.cells_compared += 1
                if not self._equal(a, b):
                    res.diff_count += 1
                    if len(res.diffs) < self.opts.max_diffs_stored:
                        res.diffs.append({"sheet": res.label,
                                          "cell": f"{get_column_letter(excel_col)}{excel_row}",
                                          "source": a, "target": b})
        return res

    # ------------------------------------------------------------------ cells
    def _is_ignored(self, row: int, col: int) -> bool:
        return any(c1 <= col <= c2 and r1 <= row <= r2 for c1, r1, c2, r2 in self._ignored)

    def _norm(self, v: Any) -> Any:
        """Apply trim / case / empty-string rules to text before comparing."""
        if isinstance(v, str):
            if self.opts.trim_strings:
                v = v.strip()
            if v == "" and self.opts.empty_equals_none:
                return None
            if self.opts.ignore_case:
                v = v.lower()
        return v

    def _equal(self, a: Any, b: Any) -> bool:
        """Type-aware equality: empty, numbers (with tolerance), dates, then text fallback."""
        a, b = self._norm(a), self._norm(b)
        if a is None or b is None:
            return a is None and b is None
        num = (int, float, Decimal)
        if isinstance(a, num) and isinstance(b, num) and not isinstance(a, bool) and not isinstance(b, bool):
            tol = self.opts.numeric_tolerance
            return abs(float(a) - float(b)) <= tol if tol else a == b
        if isinstance(a, (dt.datetime, dt.date)) and type(a) is type(b):
            return a == b
        return str(a) == str(b)
