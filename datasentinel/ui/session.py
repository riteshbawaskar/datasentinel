"""Glue between behave's `context` and the BrowserManager.

behave deletes attributes that steps set on `context` when the scenario ends, so the
(expensive) browser lives in a module-level singleton instead, and only the page handle is
kept on `context.page` (scenario scoped, which is what we want).
"""
from __future__ import annotations

import atexit
from pathlib import Path
from typing import List, Optional

from datasentinel.ui.browser import BrowserManager, UiSettings

_MANAGER: Optional[BrowserManager] = None


def shared_manager(artifacts_dir: Optional[Path] = None) -> BrowserManager:
    """The ONE BrowserManager of this process (created lazily, the browser itself starts on use).

    Playwright's sync API allows a single driver per process, so everything - scenario pages and
    the web_table connector - must share this manager. Works without behave's `context`.
    """
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = BrowserManager(UiSettings.load(), artifacts_dir)
        atexit.register(shutdown)          # safety net for use outside behave
    return _MANAGER


def get_manager(context) -> BrowserManager:
    """Shared manager, with artifacts (trace/video) going to this run's report folder."""
    return shared_manager(Path(context.report_dir) / "ui_artifacts")


def get_page(context):
    """Return the current scenario's Playwright page, opening one on first use."""
    if getattr(context, "page", None) is None:
        name = context.scenario.name if hasattr(context, "scenario") else "scenario"
        context.page = get_manager(context).new_page(name)
    return context.page


def capture_failure_screenshot(context) -> Optional[bytes]:
    """PNG of the page if this scenario opened one (used by the after_step hook)."""
    # Honour `screenshot_on_failure` from config/ui.yml.
    if (_MANAGER and _MANAGER.settings.screenshot_on_failure
            and getattr(context, "page", None) is not None):
        return _MANAGER.screenshot()
    return None


def end_scenario(context, failed: bool, name: str) -> List[Path]:
    """Close the scenario's page, keeping trace/video artifacts when it failed."""
    if _MANAGER:
        return _MANAGER.close_page(failed=failed, name=name)
    return []


def shutdown() -> None:
    """Close the browser at the end of the run."""
    global _MANAGER
    if _MANAGER:
        _MANAGER.shutdown()
        _MANAGER = None
