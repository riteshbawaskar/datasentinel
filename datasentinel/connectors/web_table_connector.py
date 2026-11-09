"""Web table connector: read an HTML <table> from a live page with Playwright.

This lets a UI grid be compared with a database using the SAME compare YAML as any other
source - the "recordset" is simply the table rows shown on screen:

    target:
      type: web_table
      url: https://app.example.com/customers      # or a local file, e.g. data/demo_site/index.html
      selector: "#customers"                       # CSS selector of the <table>
      actions:                                     # optional steps before reading (login etc.)
        - {fill: "#user", value: "qa"}
        - {fill: "#pwd",  value: "ENC(gAAAA...)"}  # ENC() values are decrypted automatically
        - {click: "#login"}
        - {wait_for: "#customers"}

The read uses its own isolated browser context on the shared Playwright browser (settings from
config/ui.yml), so it never disturbs a UI scenario's page and works inside UI scenarios too.
"""
from __future__ import annotations

import pandas as pd

from datasentinel.connectors.base import BaseConnector
from datasentinel.ui.browser import resolve_url
from datasentinel.ui.session import shared_manager
from datasentinel.ui.table_parser import parse_html_table


class WebTableConnector(BaseConnector):
    type_name = "web_table"

    def connect(self) -> None:
        # Shared per-process browser (a second Playwright driver cannot be started).
        self._mgr = shared_manager()

    def fetch_df(self, query: str | None) -> pd.DataFrame:
        ctx = self._mgr.scratch_context()          # isolated cookies/storage for this read
        try:
            page = ctx.new_page()
            page.goto(resolve_url(self.config["url"], self._mgr.settings.base_url))
            for action in self.config.get("actions", []):   # simple, declarative pre-steps
                if "fill" in action:
                    page.fill(action["fill"], str(action.get("value", "")))
                elif "click" in action:
                    page.click(action["click"])
                elif "wait_for" in action:
                    page.wait_for_selector(action["wait_for"])
            selector = self.config.get("selector", "table")
            page.wait_for_selector(selector)
            html = page.locator(selector).first.evaluate("el => el.outerHTML")
            return parse_html_table(html, header=self.config.get("header", True))
        finally:
            ctx.close()

    def close(self) -> None:
        # Nothing to do: the shared browser is closed once, at the end of the run.
        pass
