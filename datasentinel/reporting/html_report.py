"""Compact, standalone (no external assets) HTML report of scenarios and checkpoints.

Everything - CSS, the tiny filter script and any screenshots - is inlined into ONE file, so the
report can be e-mailed, attached to a ticket or archived as a CI artifact without extras.
Dark mode follows the viewer's OS setting (prefers-color-scheme).
"""
from __future__ import annotations

from html import escape as e
from pathlib import Path
from typing import List

from datasentinel.branding import NAME, TAGLINE, VERSION
from datasentinel.reporting.result_store import (FAILED, Checkpoint, ResultStore,
                                              ScenarioRecord, Table)

_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--fg:#1f2937;--mut:#6b7280;--bd:#e5e7eb;--ok:#15803d;--bad:#b91c1c;--warn:#b45309;
--okbg:#dcfce7;--badbg:#fee2e2;--warnbg:#fef3c7;--skbg:#e5e7eb}
@media(prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--fg:#e5e7eb;--mut:#9ca3af;--bd:#2a2f3a;
--ok:#4ade80;--bad:#f87171;--warn:#fbbf24;--okbg:#14301f;--badbg:#3b1717;--warnbg:#3a2c0e;--skbg:#2a2f3a}}
*{box-sizing:border-box}body{margin:0;padding:16px;background:var(--bg);color:var(--fg);
font:13px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
h1{font-size:19px;margin:0 0 2px}.brand b{color:var(--ok)}.sub{font-size:12px}.mut{color:var(--mut)}.top{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-bottom:12px}
.cards{display:flex;gap:8px;flex-wrap:wrap}.card{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:6px 12px;min-width:92px}
.card b{display:block;font-size:18px}.card.ok b{color:var(--ok)}.card.bad b{color:var(--bad)}.card.warn b{color:var(--warn)}
.bar{display:flex;gap:6px;margin:0 0 10px;flex-wrap:wrap}.bar button{border:1px solid var(--bd);background:var(--card);color:var(--fg);
border-radius:6px;padding:3px 10px;cursor:pointer;font:inherit}.bar button.on{outline:2px solid var(--mut)}
body[data-f=failed] .sc.passed,body[data-f=failed] .sc.skipped{display:none}
details.sc{background:var(--card);border:1px solid var(--bd);border-left:4px solid var(--bd);border-radius:6px;margin:6px 0}
details.sc.passed{border-left-color:var(--ok)}details.sc.failed,details.sc.error{border-left-color:var(--bad)}
details.sc>summary{padding:7px 10px;cursor:pointer;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.sc .body{padding:2px 12px 10px}.b{display:inline-block;border-radius:4px;padding:0 6px;font-size:11px;font-weight:600;line-height:18px;
background:var(--skbg);color:var(--mut);text-transform:uppercase}
.b.PASSED,.b.passed{background:var(--okbg);color:var(--ok)}.b.FAILED,.b.failed,.b.error{background:var(--badbg);color:var(--bad)}
.b.WARNING{background:var(--warnbg);color:var(--warn)}.tag{color:var(--mut);font-size:11px}
.kv{display:inline-block;margin:0 14px 2px 0}.kv b{color:var(--mut);font-weight:600}
.ck{margin:3px 0;border:1px solid var(--bd);border-radius:5px;padding:3px 8px}.ck>summary{cursor:pointer}
.ck.FAILED{border-color:var(--bad)}.ck .ea{color:var(--mut);margin-left:6px}
.msg{margin:4px 0;color:var(--warn)}pre{background:var(--badbg);color:var(--bad);padding:6px;border-radius:5px;white-space:pre-wrap;margin:6px 0}
.tw{overflow:auto;max-height:280px;margin:6px 0;border:1px solid var(--bd);border-radius:5px}
table{border-collapse:collapse;width:100%;font-size:12px}th,td{padding:2px 8px;border-bottom:1px solid var(--bd);text-align:left;white-space:nowrap}
th{position:sticky;top:0;background:var(--card)}.cap{font-weight:600;margin-top:6px}
"""

_JS = """
const F=document.querySelectorAll('.bar [data-f]');
F.forEach(b=>b.onclick=()=>{document.body.dataset.f=b.dataset.f;F.forEach(x=>x.classList.toggle('on',x===b))});
document.querySelectorAll('.bar [data-o]').forEach(b=>b.onclick=()=>
  document.querySelectorAll('details.sc').forEach(d=>d.open=b.dataset.o==='1'));
"""


def _table(t: Table) -> str:
    head = "".join(f"<th>{e(c)}</th>" for c in t.columns)
    body = "".join("<tr>" + "".join(f"<td>{e(v)}</td>" for v in r) + "</tr>" for r in t.rows)
    note = f" (showing {len(t.rows)} of {t.total_rows})" if t.total_rows > len(t.rows) else f" ({t.total_rows})"
    return f'<div class="cap">{e(t.title)}{note}</div><div class="tw"><table><tr>{head}</tr>{body}</table></div>'


def _checkpoint(c: Checkpoint) -> str:
    ea = ""
    if c.expected or c.actual:
        ea = f'<span class="ea">expected: {e(c.expected)} &middot; actual: {e(c.actual)}</span>'
    head = f'<span class="b {c.status}">{c.status}</span> {e(c.name)}{ea}'
    if not (c.message or c.tables):
        return f'<div class="ck {c.status}">{head}</div>'
    msg = f'<div class="msg">{e(c.message)}</div>' if c.message else ""
    tables = "".join(_table(t) for t in c.tables)
    return f'<details class="ck {c.status}"{" open" if c.status == FAILED else ""}><summary>{head}</summary>{msg}{tables}</details>'


def _scenario(s: ScenarioRecord) -> str:
    n, bad = len(s.checkpoints), s.count(FAILED)
    tags = " ".join(f"@{e(t)}" for t in s.tags)
    kv = "".join(f'<span class="kv"><b>{e(k)}</b> {e(v)}</span>' for k, v in s.info.items())
    errors = "".join(f"<pre>{e(x)}</pre>" for x in s.errors)
    # Screenshots (UI failures) are embedded as data URIs and kept collapsed to stay compact.
    shots = "".join(f'<details class="ck"><summary>Screenshot: {e(i.title)}</summary>'
                    f'<img alt="{e(i.title)}" style="max-width:100%;margin:6px 0" '
                    f'src="data:image/png;base64,{i.png_b64}"></details>' for i in s.images)
    open_attr = " open" if s.status in ("failed", "error") else ""
    return (f'<details class="sc {s.status}"{open_attr}><summary><span class="b {s.status}">{s.status}</span>'
            f'<b>{e(s.name)}</b><span class="mut">{e(s.feature)}</span><span class="tag">{tags}</span>'
            f'<span class="mut" style="margin-left:auto">{n - bad}/{n} checkpoints &middot; {s.duration:.2f}s</span></summary>'
            f'<div class="body">{kv}{errors}{"".join(_checkpoint(c) for c in s.checkpoints)}{shots}</div></details>')


def render_html(store: ResultStore) -> str:
    t = store.totals()

    def card(label: str, value: int, cls: str = "") -> str:
        return f'<div class="card {cls}"><span class="mut">{label}</span><b>{value}</b></div>'

    cards = "".join([
        card("Scenarios", t["scenarios"]), card("Passed", t["scenarios_passed"], "ok"),
        card("Failed", t["scenarios_failed"], "bad" if t["scenarios_failed"] else ""),
        card("Checkpoints", t["checkpoints"]), card("Passed", t["checkpoints_passed"], "ok"),
        card("Failed", t["checkpoints_failed"], "bad" if t["checkpoints_failed"] else ""),
        card("Warnings", t["checkpoints_warning"], "warn" if t["checkpoints_warning"] else ""),
    ])
    by_feature: dict = {}
    for s in store.scenarios:
        by_feature.setdefault(s.feature, []).append(s)
    body = "".join(f'<h3 style="margin:14px 0 2px">{e(f)}</h3>' + "".join(_scenario(s) for s in sc)
                   for f, sc in by_feature.items())
    env = f" &middot; {e(store.environment)}" if store.environment else ""
    run = "".join(f" &middot; {e(k)}: {e(v)}" for k, v in store.run_info.items())
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(NAME)} - {e(store.title)}</title><style>{_CSS}</style></head>'
            f'<body data-f="all"><div class="top"><div>'
            # Branding: framework name + version + tagline, then the report title and run facts.
            f'<h1><span class="brand">Data<b>Sentinel</b></span> <span class="mut">v{e(VERSION)}</span></h1>'
            f'<div class="sub mut">{e(TAGLINE)}</div>'
            f'<div style="margin-top:4px"><b>{e(store.title)}</b> <span class="mut">'
            f'{store.started:%Y-%m-%d %H:%M:%S}{env}{run}</span></div></div>'
            f'<div class="cards">{cards}</div></div>'
            f'<div class="bar"><button data-f="all" class="on">All</button><button data-f="failed">Failures only</button>'
            f'<button data-o="1">Expand all</button><button data-o="0">Collapse all</button></div>'
            f'{body}<script>{_JS}</script></body></html>')


def write_html_report(store: ResultStore, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(store), encoding="utf-8")
    return path
