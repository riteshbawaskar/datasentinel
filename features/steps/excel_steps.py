"""Step definitions: Excel cell-to-cell comparison of two workbooks."""
import time

from behave import given, then, when

from datasentinel.bdd import checkpoint
from datasentinel.comparators.excel_cell_comparator import ExcelCellComparator
from datasentinel.config_loader import load_yaml
from datasentinel.reporting.result_store import Table


def _diff_table(context, title, diffs):
    """Evidence table (sheet, cell, source value, target value), capped for report size."""
    if not diffs:
        return []
    limit = context.comparator.opts.max_report_rows
    rows = [[d["sheet"], d["cell"], d["source"], d["target"]] for d in diffs]
    return [Table(title, ["SHEET", "CELL", "SOURCE", "TARGET"],
                  [[("NULL" if v is None else str(v)) for v in r] for r in rows[:limit]], len(rows))]


@given('the excel compare config "{path}"')
def step_load(context, path):
    context.cell_cfg = load_yaml(path)
    context.store.info("Comparison", context.cell_cfg.get("name", path))
    context.store.info("Source", context.cell_cfg["source"]["path"])
    context.store.info("Target", context.cell_cfg["target"]["path"])


@when("I run the excel cell comparison")
def step_run(context):
    t0 = time.time()
    context.comparator = ExcelCellComparator(context.cell_cfg)
    context.cell_result = context.comparator.compare()
    r = context.cell_result
    context.store.info("Sheets compared", ", ".join(s.label for s in r.sheets) or "none")
    context.store.info("Cells compared", r.cells_compared)
    context.store.info("Cells different", r.total_diffs)
    context.store.info("Compare time", f"{time.time() - t0:.2f}s")


@then("both workbooks should contain the same sheets")
def step_same_sheets(context):
    r = context.cell_result
    problems = [f"missing in target: {r.missing_in_target}"] if r.missing_in_target else []
    problems += [f"missing in source: {r.missing_in_source}"] if r.missing_in_source else []
    checkpoint(context, "Same sheets in both workbooks", not problems, "identical sheet set",
               "; ".join(problems) or "identical sheet set")


@then("there should be no cell differences")
def step_no_diffs(context):
    r = context.cell_result
    all_diffs = [d for s in r.sheets for d in s.diffs]
    checkpoint(context, "No cell differences", r.total_diffs == 0, "0 cells different",
               f"{r.total_diffs} of {r.cells_compared} cells",
               tables=_diff_table(context, "Cell differences", all_diffs))


@then('the sheet "{sheet}" should have no cell differences')
def step_sheet_no_diffs(context, sheet):
    s = context.cell_result.sheet(sheet)
    if s is None:   # the sheet was not part of the comparison (missing or filtered out)
        checkpoint(context, f"Sheet {sheet} has no cell differences", False, "sheet compared", "sheet not compared")
        return
    checkpoint(context, f"Sheet {sheet} has no cell differences", s.diff_count == 0, "0",
               f"{s.diff_count} of {s.cells_compared} cells",
               tables=_diff_table(context, f"{sheet} differences", s.diffs))


@then('the cell "{cell}" in sheet "{sheet}" should match')
def step_cell_match(context, cell, sheet):
    s = context.cell_result.sheet(sheet)
    assert s is not None, f"Sheet '{sheet}' was not compared"
    hit = [d for d in s.diffs if d["cell"].upper() == cell.upper()]
    checkpoint(context, f"{sheet}!{cell.upper()} matches", not hit, "source == target",
               f"{hit[0]['source']!r} vs {hit[0]['target']!r}" if hit else "equal")
