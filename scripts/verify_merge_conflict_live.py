"""Live MERGE_CONFLICT verification against the real Bauplan platform.

Reproduces the exact SBD-14 confound on purpose: two independent branches
that each materialize a table with the SAME name but DIFFERENT content,
both merged into one shared target. The second merge must conflict.

Asserts our adapter turns that into the actionable error text (not the raw
opaque 409), which is the fix that was never verified live.

No LLM calls. Cleans up after itself.
"""
import json, os, sys, time
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harnessbench.adapters.bauplan import BauplanAdapter

SUF = f"mctest-{int(time.time())}"
USER = os.getenv("BAUPLAN_USERNAME")
SRC_A = f"{USER}.{SUF}-a"
SRC_B = f"{USER}.{SUF}-b"
TARGET = f"{USER}.{SUF}-target"
TABLE = "mc_probe"

def pipeline(limit):
    """Same table name, different content -> genuine conflicting keys."""
    return {
        "bauplan_project.yml": f"project:\n  id: '{__import__('uuid').uuid4()}'\n  name: {SUF}\n",
        "models.py": (
            "import bauplan\n\n"
            "@bauplan.model(materialization_strategy='REPLACE')\n"
            "@bauplan.python('3.11', pip={'duckdb': '1.0.0'})\n"
            f"def {TABLE}(data=bauplan.Model('tpch_1.orders', columns=['o_orderkey'])):\n"
            "    import duckdb\n"
            "    con = duckdb.connect()\n"
            "    con.register('data', data)\n"
            f"    return con.execute('SELECT o_orderkey FROM data LIMIT {limit}').fetch_arrow_table()\n"
        ),
    }

a = BauplanAdapter(mock_mode=False)
results = {}

def call(name, **args):
    out = json.loads(a.execute_tool(name, args))
    print(f"  {name}({', '.join(f'{k}={v!r}' for k,v in args.items() if k!='project_files')}) -> {json.dumps(out)[:180]}")
    return out

try:
    print("\n[1] branch A + materialize (LIMIT 5)")
    call("bauplan_checkout_branch", branch_name=SRC_A)
    r = call("bauplan_write_and_run", project_files=pipeline(5))
    assert r.get("status") == "SUCCESS", f"setup failed: {r}"

    print("\n[2] branch B from main + materialize SAME table, DIFFERENT content (LIMIT 7)")
    a._active_branch = None
    call("bauplan_checkout_branch", branch_name=SRC_B)
    r = call("bauplan_write_and_run", project_files=pipeline(7))
    assert r.get("status") == "SUCCESS", f"setup failed: {r}"

    print("\n[3] create shared target")
    call("bauplan_ensure_target_branch", branch_name=TARGET)

    print("\n[4] first merge (A -> target): should SUCCEED")
    r1 = call("bauplan_merge_branch", branch_name=SRC_A, into_ref=TARGET)
    assert r1.get("status") == "merged", f"expected clean first merge, got {r1}"

    print("\n[5] second merge (B -> SAME target): should CONFLICT")
    r2 = call("bauplan_merge_branch", branch_name=SRC_B, into_ref=TARGET)
    results["conflict_response"] = r2

    print("\n=== ASSERTIONS ===")
    checks = [
        ("status is error", r2.get("status") == "error"),
        ("did not silently succeed", r2.get("status") != "merged"),
        ("names MERGE_CONFLICT", "MERGE_CONFLICT" in str(r2.get("error", ""))),
        ("says retrying won't work", "will not work" in str(r2.get("error", "")).lower()),
        ("tells agent to pick NEW target", "new target branch name" in str(r2.get("error", "")).lower()),
        ("preserves original platform error", "conflict" in str(r2.get("error", "")).lower()),
    ]
    ok = True
    for label, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
        ok = ok and passed
    print("\n  FULL ERROR TEXT THE AGENT WOULD SEE:")
    print(f"  {r2.get('error')}")
    print(f"\n=== {'VERIFIED LIVE' if ok else 'FAILED'} ===")
    results["ok"] = ok

finally:
    print("\n[cleanup]")
    import bauplan
    c = bauplan.Client()
    for b in (SRC_A, SRC_B, TARGET):
        try:
            if c.has_branch(b):
                c.delete_branch(b); print(f"  deleted {b}")
        except Exception as e:
            print(f"  could not delete {b}: {e}")

sys.exit(0 if results.get("ok") else 1)
