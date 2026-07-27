"""Seed the DuckDB database for the motherduck MCP study.

Deterministic (fixed seed) so ground truth is re-derivable by anyone:
    python scripts/make_motherduck_study_db.py [dest.duckdb]
Prints the ground-truth answers used by the study goals.
"""
import os
import sys

import duckdb

DEST = sys.argv[1] if len(sys.argv) > 1 else "data/motherduck_study.duckdb"

os.makedirs(os.path.dirname(DEST) or ".", exist_ok=True)
if os.path.exists(DEST):
    os.remove(DEST)
con = duckdb.connect(DEST)

con.execute("select setseed(0.42)")
con.execute("""
create table orders as
select
    row_number() over () as order_id,
    (random() * 500)::int + 1 as customer_id,
    ['North','South','East','West'][(random()*4)::int + 1] as region,
    ['widget','gadget','sprocket'][(random()*3)::int + 1] as product,
    round(random() * 490 + 10, 2) as amount,
    date '2025-01-01' + interval ((random()*364)::int) day as order_date
from range(250000)
""")
con.execute("""
create table customers as
select
    range as customer_id,
    'customer_' || range as name,
    ['bronze','silver','gold'][(random()*3)::int + 1] as tier
from range(1, 501)
""")

# Ground truth is DEFINED here, once, and EMITTED to disk so graders read it
# instead of reconstructing it. Added 2026-07-27 after an analysis
# hand-rewrote the top-region query with a spurious `join customers` — region
# is a column on `orders` — producing a wrong ground truth that scored 8
# correct model answers as failures. Two of the three reconstructions happened
# to match; that was luck, not method. One source of truth, machine-read.
GT_QUERIES = {
    "md_total_revenue": "select round(sum(amount),2) from orders",
    "md_top_region":
        "select region, round(sum(amount),2) from orders group by 1 order by 2 desc limit 1",
    "md_gold_revenue":
        "select round(sum(o.amount),2) from orders o "
        "join customers c using (customer_id) where c.tier='gold'",
}

print("tables:", con.execute("show tables").fetchall())
print("orders rows:", con.execute("select count(*) from orders").fetchone()[0])

ground_truth = {}
for task, q in GT_QUERIES.items():
    row = con.execute(q).fetchone()
    ground_truth[task] = {"query": q, "value": list(row) if len(row) > 1 else row[0]}
    print(f"GT {task}: {ground_truth[task]['value']}")

import json as _json
_gt_path = os.path.join(os.path.dirname(DEST), "motherduck_study_ground_truth.json")
with open(_gt_path, "w") as _f:
    _json.dump(ground_truth, _f, indent=2)
print("ground truth written:", _gt_path)

con.close()
print("written:", DEST)
