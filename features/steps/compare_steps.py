"""Step definitions: primary-key based dataset comparison.

Typical scenario:
    Given the compare config "compare_configs/customers.yml"   # load YAML
    When I run the data comparison                             # fetch both sides + compare
    Then there should be no field mismatches                   # assert (and record a checkpoint)

The `When` step stores the CompareResult on `context.result`; every `Then` step is a thin
assertion over that object, written through `checkpoint()` so it shows up in the HTML report.
"""
import time

from behave import given, then, when

from datasentinel.bdd import checkpoint
from datasentinel.comparators.dataset_comparator import DatasetComparator
from datasentinel.config_loader import load_yaml
from datasentinel.connectors import fetch_dataset
from datasentinel.reporting.result_store import Table


def _tbl(context, title, df):
    """Evidence table for the report (empty list when there is nothing to show)."""
    limit = context.comparator.opts.max_report_rows
    return [Table.from_df(title, df, limit)] if not df.empty else []


# ------------------------------------------------------------------------- Given / When
@given('the compare config "{path}"')
def step_load_compare_config(context, path):
    context.compare_cfg = load_yaml(path)
    context.store.info("Comparison", context.compare_cfg.get("name", path))
    context.store.info("Config", path)


@when("I run the data comparison")
def step_run_comparison(context):
    cfg = context.compare_cfg
    t0 = time.time()
    # Each endpoint can be any connector type (snowflake, oracle, databricks, excel, web_table ...)
    source = fetch_dataset(cfg["source"])
    target = fetch_dataset(cfg["target"])
    context.comparator = DatasetComparator(cfg)
    context.result = context.comparator.compare(source, target)

    # "Facts" shown at the top of the scenario in the report.
    r = context.result
    for key, value in (("Primary key", ", ".join(r.primary_key)),
                       ("Fields compared", f"{len(r.compared_fields)}"),
                       ("Source rows", r.source_count), ("Target rows", r.target_count),
                       ("Matched rows", r.matched_rows), ("Rows with differences", r.mismatched_rows),
                       ("Fetch+compare time", f"{time.time() - t0:.2f}s")):
        context.store.info(key, value)


# ------------------------------------------------------------------------------- Then
@then("the source and target row counts should match")
def step_counts(context):
    r = context.result
    checkpoint(context, "Row counts match", r.source_count == r.target_count,
               f"{r.source_count} (source)", f"{r.target_count} (target)")


@then("there should be no records missing in the target")
def step_missing_target(context):
    df = context.result.missing_in_target
    checkpoint(context, "No records missing in target", df.empty, "0", len(df),
               "Keys present in source but absent in target", _tbl(context, "Missing in target", df))


@then("there should be no records missing in the source")
def step_missing_source(context):
    df = context.result.missing_in_source
    checkpoint(context, "No records missing in source", df.empty, "0", len(df),
               "Keys present in target but absent in source", _tbl(context, "Missing in source", df))


@then("there should be no duplicate primary keys in the {side}")
def step_duplicates(context, side):
    # {side} is "source" or "target"
    df = context.result.duplicates_source if side == "source" else context.result.duplicates_target
    checkpoint(context, f"No duplicate primary keys in {side}", df.empty, "0", len(df),
               tables=_tbl(context, f"Duplicate keys in {side}", df))


@then("the source and target should have the same columns")
def step_same_columns(context):
    r = context.result
    only = {"only in source": r.columns_only_in_source, "only in target": r.columns_only_in_target}
    checkpoint(context, "Same column set", not (r.columns_only_in_source or r.columns_only_in_target),
               "identical columns", "; ".join(f"{k}: {v}" for k, v in only.items() if v) or "identical")


@then("there should be no field mismatches")
def step_no_mismatches(context):
    r = context.result
    tables = []
    if r.mismatched_rows:
        # First a per-column summary, then the individual differing values.
        counts = [[c, str(n)] for c, n in r.column_mismatch_counts.items() if n]
        tables = [Table("Mismatches per column", ["COLUMN", "MISMATCHES"], counts, len(counts))]
        tables += _tbl(context, "Field mismatches", r.mismatches)
    checkpoint(context, "No field mismatches", r.mismatched_rows == 0, "0 rows with differences",
               f"{r.mismatched_rows} of {r.common_rows} rows", tables=tables)


@then('the field "{field}" should have no mismatches')
def step_field_no_mismatch(context, field):
    r, col = context.result, field.strip().upper()
    if col not in r.column_mismatch_counts:      # field was not part of the comparison
        checkpoint(context, f"Field {col} has no mismatches", False, "field compared",
                   "field not compared", f"Compared fields: {r.compared_fields}")
        return
    n = r.column_mismatch_counts[col]
    sub = r.mismatches[r.mismatches["COLUMN"] == col]
    checkpoint(context, f"Field {col} has no mismatches", n == 0, "0", n,
               tables=_tbl(context, f"{col} mismatches", sub))


@then("the mismatch percentage should be at most {pct:g}")
def step_mismatch_pct(context, pct):
    # Percentage of COMMON rows that have at least one differing field.
    r = context.result
    checkpoint(context, f"Mismatch rate <= {pct:g}%", r.mismatch_pct <= pct, f"<= {pct:g}%",
               f"{r.mismatch_pct:.2f}%", tables=_tbl(context, "Field mismatches", r.mismatches))


@then("the data comparison should pass")
def step_overall(context):
    """Composite assertion: records EVERY checkpoint, then fails once if any failed.

    behave stops a scenario at the first failing step, so a chain of Then/And steps reports only
    the first problem. This single step reports them all in one run.
    """
    r, ok = context.result, []
    ok.append(checkpoint(context, "Row counts match", r.source_count == r.target_count,
                         r.source_count, r.target_count, raise_on_fail=False))
    ok.append(checkpoint(context, "No records missing in target", r.missing_in_target.empty, "0",
                         len(r.missing_in_target), tables=_tbl(context, "Missing in target", r.missing_in_target),
                         raise_on_fail=False))
    ok.append(checkpoint(context, "No records missing in source", r.missing_in_source.empty, "0",
                         len(r.missing_in_source), tables=_tbl(context, "Missing in source", r.missing_in_source),
                         raise_on_fail=False))
    dups = len(r.duplicates_source) + len(r.duplicates_target)
    ok.append(checkpoint(context, "No duplicate primary keys", dups == 0, "0", dups, raise_on_fail=False))
    ok.append(checkpoint(context, "No field mismatches", r.mismatched_rows == 0, "0 rows with differences",
                         f"{r.mismatched_rows} of {r.common_rows} rows",
                         tables=_tbl(context, "Field mismatches", r.mismatches), raise_on_fail=False))
    assert all(ok), "One or more comparison checkpoints failed - see report"
