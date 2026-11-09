"""Create local demo data (SQLite DB + Excel files) so the sample features run without cloud access."""
import copy
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from openpyxl import Workbook

DATA = Path(__file__).resolve().parent.parent / "data"
DATA.mkdir(exist_ok=True)
random.seed(7)

# ---------------------------------------------------------------- customers
countries = ["IN", "US", "UK", "DE", "SG"]
customers = pd.DataFrame({
    "CUSTOMER_ID": range(1001, 1031),
    "NAME": [f"Customer {i}" for i in range(1, 31)],
    "EMAIL": [f"user{i}@example.com" for i in range(1, 31)],
    "COUNTRY": [random.choice(countries) for _ in range(30)],
    "CREDIT_LIMIT": [round(random.uniform(1000, 9000), 2) for _ in range(30)],
    "STATUS": [random.choice(["ACTIVE", "INACTIVE"]) for _ in range(30)],
})

# identical copy as Excel (target of the "ok" comparison); IDs stored as ints, floats as floats
with pd.ExcelWriter(DATA / "customers_expected.xlsx") as xw:
    customers.to_excel(xw, sheet_name="Customers", index=False)

# copy with deliberate differences
diff = customers.copy()
diff = diff[diff.CUSTOMER_ID != 1005]                                   # missing in target
diff.loc[diff.CUSTOMER_ID == 1010, "EMAIL"] = "changed@example.com"     # text mismatch
diff.loc[diff.CUSTOMER_ID == 1011, "CREDIT_LIMIT"] += 0.0004            # within tolerance
diff.loc[diff.CUSTOMER_ID == 1012, "CREDIT_LIMIT"] += 50               # real numeric mismatch
orig = diff.loc[diff.CUSTOMER_ID == 1013, "STATUS"].iloc[0]
diff.loc[diff.CUSTOMER_ID == 1013, "STATUS"] = f"  {orig.lower()} "     # trim + ignore_case -> ok
diff.loc[diff.CUSTOMER_ID == 1014, "COUNTRY"] = "FR"
diff = pd.concat([diff, pd.DataFrame([{"CUSTOMER_ID": 2001, "NAME": "Extra", "EMAIL": "x@example.com",
                                       "COUNTRY": "IN", "CREDIT_LIMIT": 1.0, "STATUS": "ACTIVE"}])])
with pd.ExcelWriter(DATA / "customers_with_diffs.xlsx") as xw:
    diff.to_excel(xw, sheet_name="Customers", index=False)

# ------------------------------------------------------------------- orders
base = date(2024, 1, 1)
def make_orders():
    return pd.DataFrame({
        "ORDER_ID": range(1, 41),
        "CUSTOMER_ID": [random.choice(range(1001, 1031)) for _ in range(40)],
        "ORDER_DATE": [(base + timedelta(days=i)).isoformat() for i in range(40)],
        "AMOUNT": [round(random.uniform(10, 900), 2) for _ in range(40)],
        "QUANTITY": [random.randint(1, 9) for _ in range(40)],
        "STATUS": [random.choice(["NEW", "SHIPPED", "CANCELLED"]) for _ in range(40)],
        "EMAIL": [f"buyer{i}@example.com" for i in range(40)],
    })
orders = make_orders()
dirty = orders.copy().astype(object)
dirty.loc[2, "ORDER_ID"] = 2                      # duplicate key
dirty.loc[4, "EMAIL"] = None                      # null
dirty.loc[6, "AMOUNT"] = "abc"                    # not numeric
dirty.loc[8, "AMOUNT"] = -15.5                    # out of range
dirty.loc[10, "ORDER_DATE"] = "2024-13-45"        # bad date
dirty.loc[12, "STATUS"] = "UNKNOWN"               # not allowed
dirty.loc[14, "EMAIL"] = "not-an-email"           # regex
dirty.loc[16, "QUANTITY"] = 2.5                   # not integer

with sqlite3.connect(DATA / "demo.db") as db:
    customers.to_sql("customers", db, index=False, if_exists="replace")
    orders.to_sql("orders", db, index=False, if_exists="replace")
    dirty.to_sql("orders_dirty", db, index=False, if_exists="replace")

# -------------------------------------------------- Excel cell-compare files
def sales_book(path, tweak=None):
    wb = Workbook()
    ws = wb.active; ws.title = "Summary"
    ws.append(["Region", "Q1", "Q2", "Q3", "Q4", "Total"])
    rows = [["North", 100, 120.5, 130, 140], ["South", 90, 95, 99.99, 105], ["East", 70, 80, 85, 90], ["West", 60, 65, 70, 75]]
    for i, r in enumerate(rows, start=2):
        ws.append(r + [f"=SUM(B{i}:E{i})"])
    ws2 = wb.create_sheet("Targets")
    ws2.append(["Region", "Target"])
    for r, t in [("North", 500), ("South", 400), ("East", 300), ("West", 250)]:
        ws2.append([r, t])
    if tweak:
        tweak(wb)
    wb.save(path)

sales_book(DATA / "sales_v1.xlsx")

def tweak_ok(wb):
    ws = wb["Summary"]
    ws["A2"] = "  north "          # trim + ignore_case
    ws["C2"] = 120.5004            # within tolerance
sales_book(DATA / "sales_v2_ok.xlsx", tweak_ok)

def tweak_diff(wb):
    ws = wb["Summary"]
    ws["C2"] = 999                 # numeric diff
    ws["B4"] = "seventy"           # type diff
    ws["E5"] = None                # blank vs value
    wb["Targets"]["B3"] = 410
sales_book(DATA / "sales_v2_diff.xlsx", tweak_diff)
print("Demo data written to", DATA)

# ------------------------------------------------ demo web page (Playwright scenarios)
# A static page with a searchable customer grid built from the same data as the database, so
# "UI grid vs database" comparisons pass out of the box and `file://` needs no web server.
site = DATA / "demo_site"
site.mkdir(exist_ok=True)
cols = ["CUSTOMER_ID", "NAME", "EMAIL", "COUNTRY", "CREDIT_LIMIT", "STATUS"]
body_rows = "\n".join(
    "<tr>" + "".join(f"<td>{r[c]:.2f}</td>" if c == "CREDIT_LIMIT" else f"<td>{r[c]}</td>" for c in cols) + "</tr>"
    for _, r in customers.iterrows())
(site / "index.html").write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Customer Directory</title></head>
<body>
<h1 id="heading">Customer Directory</h1>
<label>Filter by name <input id="name-filter" type="text"></label>
<button id="search" type="button">Search</button>
<p id="result-count">Showing {len(customers)} of {len(customers)} customers</p>
<table id="customers"><thead><tr>{"".join(f"<th>{c}</th>" for c in cols)}</tr></thead>
<tbody>
{body_rows}
</tbody></table>
<script>
// Filter rows whose NAME cell contains the typed text, and update the counter.
document.getElementById('search').addEventListener('click', () => {{
  const q = document.getElementById('name-filter').value.toLowerCase();
  const rows = document.querySelectorAll('#customers tbody tr');
  let shown = 0;
  rows.forEach(r => {{
    const match = r.children[1].textContent.toLowerCase().includes(q);
    r.style.display = match ? '' : 'none';
    if (match) shown++;
  }});
  document.getElementById('result-count').textContent = `Showing ${{shown}} of ${{rows.length}} customers`;
}});
</script></body></html>""", encoding="utf-8")
print("Demo site written to", site)
