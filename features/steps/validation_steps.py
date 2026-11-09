"""Step definitions: single-dataset data sanity validation.

    Given the validation config "validation_configs/orders.yml"
    When I run the data validations          # fetch the data once, run every configured check
    Then all validations should pass         # record each check as a checkpoint
"""
from behave import given, then, when

from datasentinel.bdd import checkpoint
from datasentinel.config_loader import load_yaml
from datasentinel.connectors import fetch_dataset
from datasentinel.reporting.result_store import Table
from datasentinel.validators.data_validator import DataValidator

# Keys of a validation config that describe the checks, not the connection.
_NON_CONN = {"query", "query_file", "table", "checks", "name", "description"}


def _record(context, outcomes):
    """Write outcomes as checkpoints; fail the step if any error-severity check failed.

    All outcomes are recorded BEFORE failing, so the report shows every problem at once.
    Warning-severity outcomes are recorded but never make the step fail.
    """
    flags = []
    for o in outcomes:
        tables = ([Table.from_df("Sample of invalid rows", o.sample, context.validator.max_sample_rows)]
                  if o.sample is not None else [])
        flags.append(checkpoint(context, o.label, o.passed, o.expected, o.actual, o.message, tables,
                                severity=o.severity, raise_on_fail=False))
    assert all(flags), f"{flags.count(False)} validation(s) failed - see report"


@given('the validation config "{path}"')
def step_load_validation_config(context, path):
    context.validation_cfg = load_yaml(path)
    context.store.info("Validation", context.validation_cfg.get("name", path))
    context.store.info("Config", path)


@when("I run the data validations")
def step_run_validations(context):
    cfg = context.validation_cfg
    df = fetch_dataset(cfg)                      # the config's top level IS the endpoint

    def sql_runner(spec):
        """Lets a `type: sql` check run its own query on the same (or an overridden) connection."""
        endpoint = {k: v for k, v in cfg.items() if k not in _NON_CONN}
        if spec.get("connection"):
            endpoint["connection"] = spec["connection"]
        endpoint["query"] = spec["query"]
        return fetch_dataset(endpoint)

    context.validator = DataValidator(cfg, sql_runner, cfg.get("max_report_rows", 200))
    context.outcomes = context.validator.run(df)
    context.store.info("Rows validated", len(df))
    context.store.info("Checks executed", len(context.outcomes))


@then("all validations should pass")
def step_all_pass(context):
    _record(context, context.outcomes)


@then('all "{check_type}" validations should pass')
def step_type_pass(context, check_type):
    selected = [o for o in context.outcomes if o.check_type == check_type]
    assert selected, f"No '{check_type}' checks are defined in the validation config"
    _record(context, selected)


@then('the validation "{name}" should pass')
def step_named_pass(context, name):
    # Matches either the check's name ("no_orphan_orders") or its full label ("sql: no_orphan_orders").
    selected = [o for o in context.outcomes if name in (o.name, o.label)]
    assert selected, f"No validation named '{name}' found"
    _record(context, selected)
