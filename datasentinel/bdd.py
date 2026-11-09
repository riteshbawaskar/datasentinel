"""Glue between behave steps and the result store."""
from __future__ import annotations

from typing import Any, List, Optional

from datasentinel.reporting.result_store import FAILED, PASSED, WARNING, Table


def checkpoint(context, name: str, passed: bool, expected: Any = "", actual: Any = "",
               message: str = "", tables: Optional[List[Table]] = None,
               severity: str = "error", raise_on_fail: bool = True) -> bool:
    """Record a checkpoint in the HTML report and (optionally) fail the step.

    Every `Then` step funnels through here so that the report lists each validation with its
    expected/actual values, even for steps that pass.

    * severity="warning" -> a failure is recorded as WARNING and never fails the scenario.
    * raise_on_fail=False -> record only; the caller decides (used by composite steps that want
      to record ALL checkpoints before failing once, because behave stops at the first failing
      step otherwise).

    Returns True when the checkpoint passed (or was only a warning).
    """
    status = PASSED if passed else (WARNING if severity == "warning" else FAILED)
    context.store.checkpoint(name, status, expected, actual, message, tables or [])
    if status == FAILED and raise_on_fail:
        raise AssertionError(f"{name}: expected {expected}; actual {actual}. {message}".strip())
    return status != FAILED
