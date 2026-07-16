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

print("tables:", con.execute("show tables").fetchall())
print("orders rows:", con.execute("select count(*) from orders").fetchone()[0])
print("GT total revenue:", con.execute("select round(sum(amount),2) from orders").fetchone()[0])
print("GT top region by revenue:", con.execute(
    "select region, round(sum(amount),2) from orders group by 1 order by 2 desc limit 1").fetchone())
print("GT gold-tier revenue:", con.execute("""
    select round(sum(o.amount),2) from orders o
    join customers c using (customer_id) where c.tier='gold'""").fetchone()[0])
con.close()
print("written:", DEST)
