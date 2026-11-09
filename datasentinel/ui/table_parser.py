"""Turn the HTML of a <table> into a DataFrame - pure Python (stdlib), no browser needed.

Kept separate from Playwright so it can be unit-tested offline and reused for any HTML string.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import List

import pandas as pd


class _TableCollector(HTMLParser):
    """Collects cell text row by row. Nested tables are ignored (only the outer table is read)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: List[List[str]] = []
        self._row: List[str] | None = None
        self._cell: List[str] | None = None
        self._depth = 0                      # table nesting depth

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
        elif self._depth == 1:               # only react inside the outermost table
            if tag == "tr":
                self._row = []
            elif tag in ("td", "th"):
                self._cell = []

    def handle_endtag(self, tag):
        if tag == "table":
            self._depth -= 1
        elif self._depth == 1:
            if tag in ("td", "th") and self._cell is not None and self._row is not None:
                # Collapse all whitespace (newlines, nbsp, indentation) into single spaces.
                self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
                self._cell = None
            elif tag == "tr" and self._row is not None:
                if self._row:
                    self.rows.append(self._row)
                self._row = None

    def handle_data(self, data):
        if self._cell is not None and self._depth == 1:   # skip text of nested tables
            self._cell.append(data)


def parse_html_table(html: str, header: bool = True) -> pd.DataFrame:
    """Parse *html* (containing one <table>) into a DataFrame of strings.

    header=True  -> the first row supplies the column names
    header=False -> columns are named COL_1, COL_2, ...
    Ragged rows are padded with empty strings.
    """
    parser = _TableCollector()
    parser.feed(html)
    rows = parser.rows
    if not rows:
        return pd.DataFrame()
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    if header:
        return pd.DataFrame(rows[1:], columns=rows[0])
    return pd.DataFrame(rows, columns=[f"COL_{i}" for i in range(1, width + 1)])
