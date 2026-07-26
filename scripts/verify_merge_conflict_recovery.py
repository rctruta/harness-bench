"""Gate 2: does an AGENT recover from the improved MERGE_CONFLICT message?

verify_merge_conflict_live.py proved the MECHANISM (adapter returns
actionable text). This proves — or refutes — the BEHAVIOURAL response,
which was explicitly left unverified.

Setup is deterministic and LLM-free: two branches materialise the same
table name with different content; the first is merged into a target, so
the second is guaranteed to conflict. Then the real AUDITOR specialist is
run against it through the real tool loop, and we check whether it picks a
NEW target instead of retrying the same one.

Baseline being tested against: before the fix, Haiku received the generic
"you repeated a failing call" coaching, did not infer the correct fix, and
burned its remaining turns investigating (SBD-14 write-up).

One model, one run, ~10 turns. Cleans up after itself.
"""
import json, os, sys, time, uuid
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harnessbench.adapters.bauplan import BauplanAdapter
from harnessbench.runner.specialist import run_specialist

MODEL = os.getenv("RECOVERY_TEST_MODEL", "anthropic/claude-haiku-4-5-20251001")
USER = os.getenv("BAUPLAN_USERNAME")
SUF = f"mcrec-{int(time.time())}"
SRC_A, SRC_B = f"{USER}.{SUF}-a", f"{USER}.{SUF}-b"
TARGET = f"{USER}.{SUF}-target"
TABLE = "recovery_probe"

def pipeline(limit):
    return {
        "bauplan_project.yml": f"project:\n  id: '{uuid.uuid4()}'\n  name: {SUF}\n",
        "models.py": (
            "import bauplan\n\n"
            "@bauplan.model(materialization_strategy='REPLACE')\n"
            "@bauplan.python('3.11', pip={'duckdb': '1.0.0'})\n"
            f"def {TABLE}(data=bauplan.Model('tpch_1.orders', columns=['o_orderkey'])):\n"
            "    import duckdb\n    con = duckdb.connect()\n    con.register('data', data)\n"
            f"    return con.execute('SELECT o_orderkey FROM data LIMIT {limit}').fetch_arrow_table()\n"
        ),
    }

a = BauplanAdapter(mock_mode=False)
def call(n, **kw):
    return json.loads(a.execute_tool(n, kw))

print(f"model under test: {MODEL}\n[setup — no LLM]")
try:
    call("bauplan_checkout_branch", branch_name=SRC_A)
    assert call("bauplan_write_and_run", project_files=pipeline(5))["status"] == "SUCCESS"
    a._active_branch = None
    call("bauplan_checkout_branch", branch_name=SRC_B)
    assert call("bauplan_write_and_run", project_files=pipeline(9))["status"] == "SUCCESS"
    call("bauplan_ensure_target_branch", branch_name=TARGET)
    assert call("bauplan_merge_branch", branch_name=SRC_A, into_ref=TARGET)["status"] == "merged"
    print(f"  '{TARGET}' now holds A's version of {TABLE}; B will conflict.\n")

    a._active_branch = SRC_B
    brief = (
        f"Branch '{SRC_B}' has pipeline changes ready for review. Verify the "
        f"result and merge it into the sandbox target '{TARGET}'. Never merge into main."
    )
    print("[running real AUDITOR specialist through the real tool loop]")
    res = run_specialist(a, a.roles()["auditor"], brief=brief, model=MODEL, runs_dir="/tmp/mcrec_runs")

    merges = []
    from harnessbench.trace_utils import load_trace_events
    import glob as _glob
    # Resolve by glob, not by assuming runs_dir/{sub_run_id}.jsonl: AgentTrace
    # writes into a timestamped SUBdirectory. The first version of this script
    # assumed the flat path, load_trace_events() returned [] for the missing
    # file exactly as documented, and the script reported "DID NOT RECOVER"
    # for a run that had recovered perfectly. Fail loudly instead.
    _hits = _glob.glob(f"/tmp/mcrec_runs/**/{res.sub_run_id}.jsonl", recursive=True)
    if not _hits:
        raise RuntimeError(
            f"cannot locate trace for sub_run_id={res.sub_run_id} under /tmp/mcrec_runs — "
            f"refusing to report a verdict from zero events")
    for e in load_trace_events(_hits[0]):
        if e.get("event") == "tool_call" and e.get("name") == "bauplan_merge_branch":
            merges.append((e["arguments"].get("into_ref"), e["arguments"].get("branch_name")))
        if e.get("event") == "tool_result" and e.get("name") == "bauplan_merge_branch":
            try: merges[-1] = merges[-1] + (json.loads(e.get("result") or "{}").get("status"),)
            except Exception: pass

    print(f"\n  outcome={res.outcome}  turns={res.turns_used}")
    print("  merge attempts:")
    for m in merges: print(f"    into={m[0]!r} status={m[-1] if len(m)>2 else '?'}")

    targets = [m[0] for m in merges]
    distinct = list(dict.fromkeys(targets))
    succeeded = any(len(m) > 2 and m[-1] == "merged" for m in merges)
    print("\n=== RESULT ===")
    print(f"  hit the conflict:        {TARGET in targets}")
    print(f"  tried a DIFFERENT target:{len(distinct) > 1}  {distinct}")
    print(f"  eventually merged:       {succeeded}")
    verdict = ("RECOVERED — agent read the message and switched target"
               if len(distinct) > 1 and succeeded else
               "DID NOT RECOVER — retried the same target / gave up")
    print(f"  VERDICT: {verdict}")
finally:
    print("\n[cleanup]")
    import bauplan
    c = bauplan.Client()
    for b in list(dict.fromkeys([SRC_A, SRC_B, TARGET] + [m[0] for m in (merges if 'merges' in dir() else [])])):
        try:
            if b and c.has_branch(b): c.delete_branch(b); print(f"  deleted {b}")
        except Exception as e: print(f"  could not delete {b}: {e}")
