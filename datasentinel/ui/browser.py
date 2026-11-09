"""Playwright settings and browser lifecycle.

One *browser* is launched per process (expensive) and one fresh *context + page* per scenario
(cheap, fully isolated cookies/storage), which is the pattern Playwright recommends and what
keeps parallel workers independent.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from datasentinel.config_loader import ConfigError, load_yaml, resolve_path

UI_CONFIG_FILE = "config/ui.yml"
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class UiSettings:
    browser: str = "chromium"
    headless: bool = True
    base_url: str = ""
    timeout_ms: int = 10000
    viewport_width: int = 1366
    viewport_height: int = 768
    slow_mo_ms: int = 0
    screenshot_on_failure: bool = True
    trace_on_failure: bool = False
    record_video: bool = False

    @classmethod
    def load(cls) -> "UiSettings":
        """Defaults < config/ui.yml < environment (DATASENTINEL_BROWSER / DATASENTINEL_HEADLESS).

        features/environment.py copies `-D browser=...` / `-D headless=...` into those env vars,
        so command-line overrides also reach code that runs outside a behave step.
        """
        s = cls()
        path = resolve_path(UI_CONFIG_FILE)
        if path.exists():
            cfg = load_yaml(UI_CONFIG_FILE)
            vp = cfg.pop("viewport", {}) or {}
            s.viewport_width = int(vp.get("width", s.viewport_width))
            s.viewport_height = int(vp.get("height", s.viewport_height))
            for key, value in cfg.items():
                if hasattr(s, key):
                    setattr(s, key, value)
        if os.environ.get("DATASENTINEL_BROWSER"):
            s.browser = os.environ["DATASENTINEL_BROWSER"]
        if os.environ.get("DATASENTINEL_HEADLESS"):
            s.headless = _as_bool(os.environ["DATASENTINEL_HEADLESS"])
        if s.browser not in ("chromium", "firefox", "webkit"):
            raise ConfigError(f"Unknown browser '{s.browser}' (use chromium, firefox or webkit)")
        return s


def resolve_url(url: str, base_url: str = "") -> str:
    """Make *url* navigable.

    * http://, https://, file:// ... -> unchanged
    * a path that exists in the project (data/demo_site/index.html) -> file:// URL
    * anything else -> appended to base_url (config/ui.yml)
    """
    if _SCHEME.match(url) or url.startswith("about:"):
        return url
    local = resolve_path(url)
    if local.exists():
        return local.as_uri()
    if base_url:
        return base_url.rstrip("/") + "/" + url.lstrip("/")
    return url


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:80]


class BrowserManager:
    """Owns the Playwright driver, one browser and the current scenario's page."""

    def __init__(self, settings: UiSettings, artifacts_dir: Optional[Path]):
        self.settings = settings
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else None
        self._pw = None
        self._browser = None
        self._context = None
        self.page = None
        self._video_ref = None

    # ---- lifecycle ---------------------------------------------------------------
    def _ensure_browser(self) -> None:
        if self._browser:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # friendly, actionable message
            raise ConfigError("Playwright is not installed. Run:\n"
                              "    pip install playwright\n    playwright install chromium") from exc
        self._pw = sync_playwright().start()
        launcher = getattr(self._pw, self.settings.browser)
        self._browser = launcher.launch(headless=self.settings.headless,
                                        slow_mo=self.settings.slow_mo_ms or 0)

    def new_page(self, scenario_name: str):
        """Open an isolated context + page for one scenario (closes any previous one)."""
        self._ensure_browser()
        self.close_page(failed=False)
        opts = {"viewport": {"width": self.settings.viewport_width,
                             "height": self.settings.viewport_height}}
        if self.settings.record_video and self.artifacts_dir:
            self.artifacts_dir.mkdir(parents=True, exist_ok=True)
            opts["record_video_dir"] = str(self.artifacts_dir / "videos_tmp")
        self._context = self._browser.new_context(**opts)
        self._context.set_default_timeout(self.settings.timeout_ms)
        if self.settings.trace_on_failure and self.artifacts_dir:
            self._context.tracing.start(screenshots=True, snapshots=True)
        self.page = self._context.new_page()
        self._video_ref = self.page.video if self.settings.record_video else None
        return self.page

    def scratch_context(self):
        """An extra, isolated browser context for data reads (e.g. the web_table connector).

        Shares the already-running driver/browser - Playwright's sync API cannot start a second
        driver in the same process - but never touches the scenario's own page. The caller must
        close the returned context.
        """
        self._ensure_browser()
        ctx = self._browser.new_context(viewport={"width": self.settings.viewport_width,
                                                  "height": self.settings.viewport_height})
        ctx.set_default_timeout(self.settings.timeout_ms)
        return ctx

    def screenshot(self) -> Optional[bytes]:
        """Full-page PNG of the current page, or None if there is no page."""
        if not self.page:
            return None
        try:
            return self.page.screenshot(full_page=True)
        except Exception:      # page may already be closed/crashed - never mask the real failure
            return None

    def close_page(self, failed: bool, name: str = "scenario") -> List[Path]:
        """Close the scenario's context. On failure keep trace/video; otherwise discard them."""
        kept: List[Path] = []
        if not self._context:
            return kept
        if self.settings.trace_on_failure and self.artifacts_dir:
            if failed:
                self.artifacts_dir.mkdir(parents=True, exist_ok=True)
                trace = self.artifacts_dir / f"{_safe(name)}_trace.zip"
                self._context.tracing.stop(path=str(trace))
                kept.append(trace)
            else:
                self._context.tracing.stop()          # discard
        video_path = None
        if self._video_ref:
            try:
                video_path = Path(self._video_ref.path())
            except Exception:
                video_path = None
        self._context.close()                         # videos are finalised on close
        if video_path and video_path.exists():
            if failed:
                dest = self.artifacts_dir / f"{_safe(name)}.webm"
                video_path.replace(dest)
                kept.append(dest)
            else:
                video_path.unlink(missing_ok=True)
        self._context, self.page, self._video_ref = None, None, None
        return kept

    def shutdown(self) -> None:
        """Close everything. Safe to call more than once."""
        self.close_page(failed=False)
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._pw:
            self._pw.stop()
            self._pw = None
