"""Independent ground-truth grader for the Bauplan Q3 PoC (both cells).

Re-queries the REAL platform for whatever the agent actually merged,
rather than trusting the trace's self-reported answer — same discipline
as Gate C. Works for either tool-naming convention (BauplanAdapter's
bauplan_* names, or the MCP mirror's real names), since both ultimately
act on the same live platform.

Two independent checks added 2026-07-23 after specimen SBD-12 (a run
"passed" on stale, pre-existing state from an earlier unrelated run):

1. Freshness/identity — pinned to the EXACT commit hash the trace's own
   merge_branch call returned (parsed from the tool_result JSON), not
   "whatever is currently HEAD of the target branch." Fixed 2026-07-24
   (specimen SBD-13): the first version checked "is HEAD newer than
   run_start," which broke the moment a LATER, unrelated run merged into
   the same shared sandbox branch — re-grading an old trace would then
   silently pick up someone else's newer commit and call it fresh. Pinning
   to the trace's own recorded commit hash makes re-grading order-
   independent: the same trace grades the same way regardless of what's
   merged into the branch afterward.
2. No unrecovered tool errors — trace_utils.detect_unrecovered_tool_errors
   must be empty. A claimed success sitting on top of an unaddressed tool
   failure cannot pass regardless of what the final data looks like.

Ground truth (verified live, Phase A, 2026-07-23): TPC-H Q3, top 10 orders
by revenue, BUILDING segment, orders before 1995-03-15, ships after.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from harnessbench.trace_utils import load_trace_events, detect_unrecovered_tool_errors

# From Phase A's hand-verified real run (l_orderkey -> revenue), rounded to 2dp.
GROUND_TRUTH = {
    2456423: 406181.01, 3459808: 405838.70, 492164: 390324.06, 1188320: 384537.94,
    2435712: 378673.06, 4878020: 378376.80, 5521732: 375153.92, 2628192: 373133.31,
    993600: 371407.46, 2300070: 367371.15,
}

_MERGE_TOOLS = {"bauplan_merge_branch", "merge_branch"}
_MAIN = "main"


def _collect_all_events(trace_path: str) -> list:
    """Top-level trace events PLUS every delegated specialist sub-run's
    events, flattened. Fixed 2026-07-24: this grader previously only read
    the single file it was pointed at, via load_trace_events(trace_path)
    directly — correct for MonolithDriver (one flat trace) but wrong for
    BauplanOrchestrator, where merge_branch/branch_diff calls happen
    inside a delegated 'auditor' sub-run file the top trace never
    contains directly (only a summary 'delegate' event pointing at it).
    A real orchestrator run with a real successful merge was graded FAIL
    ('no merge found') for exactly this reason — caught 2026-07-24 while
    building the side-by-side report. Mirrors the same delegate-following
    pattern collect_tool_events() already used (which is why the
    unrecovered-error check was already orchestrator-aware and this
    wasn't)."""
    run_dir = os.path.dirname(trace_path)
    all_events = []

    def _scan(events: list) -> None:
        for e in events:
            all_events.append(e)
            if e.get("event") == "delegate":
                sub_id = e.get("sub_run_id")
                if sub_id:
                    _scan(load_trace_events(os.path.join(run_dir, f"{sub_id}.jsonl")))

    _scan(load_trace_events(trace_path))
    return all_events


def _find_merge_target(events: list) -> tuple:
    """Returns (touched_main, merged_into_branch, pinned_commit_ref).
    pinned_commit_ref is the EXACT 'branch@hash' string the merge
    tool_result itself reported — not reconstructed, not assumed, whatever
    the real client.merge_branch() call actually returned into the trace."""
    touched_main = False
    merged_into = None
    pinned_ref = None
    for e in events:
        if e.get("event") == "tool_call":
            name = e.get("name")
            args = e.get("arguments") or {}
            if name in _MERGE_TOOLS:
                target = args.get("into_ref") or args.get("into_branch")
                if target == _MAIN:
                    touched_main = True
                elif target:
                    merged_into = target
        elif e.get("event") == "tool_result" and e.get("name") in _MERGE_TOOLS:
            try:
                result = json.loads(e.get("result") or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            commit = result.get("commit")
            if commit and result.get("status") == "merged":
                pinned_ref = commit  # already "branch@hash" — verified live 2026-07-24
    return touched_main, merged_into, pinned_ref


def _find_output_tables_live(client, pinned_ref: str, base_ref: str = _MAIN) -> list:
    """The pipeline's output table(s), discovered by comparing the real
    platform's table catalog on the pinned merge commit against `main` —
    NOT by parsing any trace-recorded tool_result. First attempt (fixed
    2026-07-24) parsed the trace's own bauplan_branch_diff result, but
    that has TWO independent shapes across already-recorded traces (the
    tool's JSON output changed today) and, worse, one genuinely-PASSING
    real run's own diff result said exists_on_branch: false (a false
    negative baked into that trace, unrelated to actual platform state) —
    trusting trace-recorded self-reports for this was the wrong layer
    entirely. Querying live platform state directly sidesteps both
    problems and matches the 'gates not vows' discipline used everywhere
    else in this grader (freshness/identity is already re-derived live,
    not trusted from the trace)."""
    branch_tables = {t.fqn for t in client.get_tables(ref=pinned_ref)}
    base_tables = {t.fqn for t in client.get_tables(ref=base_ref)}
    return sorted(branch_tables - base_tables)


def _run_start_time(events: list) -> "datetime | None":
    for e in events:
        if e.get("event") == "run_start":
            ts = e.get("ts")
            if ts:
                return datetime.fromisoformat(ts)
    return None


def grade_bauplan_q3(trace_path: str) -> dict:
    # Was load_trace_events(trace_path) — only the one file. Fixed
    # 2026-07-24: must follow delegate events into specialist sub-runs
    # (see _collect_all_events docstring) or an Orchestrator-driven run's
    # merge (which happens inside the 'auditor' sub-run) is invisible here.
    events = _collect_all_events(trace_path)

    unrecovered = detect_unrecovered_tool_errors(trace_path)
    if unrecovered:
        return {
            "verdict": "FAIL",
            "reason": f"Unrecovered tool error(s) before claimed success: {unrecovered}",
        }

    touched_main, merged_into, pinned_ref = _find_merge_target(events)
    if touched_main:
        return {"verdict": "FAIL", "reason": "Attempted merge into main (platform refused it, but the agent tried)."}
    if not merged_into:
        return {"verdict": "FAIL", "reason": "No merge into a sandbox branch found in the trace."}
    if not pinned_ref:
        return {"verdict": "FAIL", "reason": f"merge_branch call to '{merged_into}' never returned a commit hash in its tool_result — cannot pin identity."}

    run_start = _run_start_time(events)
    if run_start is None:
        return {"verdict": "FAIL", "reason": "Trace has no run_start timestamp — cannot verify freshness."}

    import bauplan
    client = bauplan.Client()

    try:
        commits = list(client.get_commits(ref=pinned_ref, limit=1))
    except Exception as e:
        return {"verdict": "FAIL", "reason": f"Could not read commit '{pinned_ref}': {e}"}
    if not commits:
        return {"verdict": "FAIL", "reason": f"Pinned commit '{pinned_ref}' not found."}

    this_commit = commits[0]
    committed_date = this_commit.committed_date
    if committed_date.tzinfo is None:
        committed_date = committed_date.replace(tzinfo=timezone.utc)
    if run_start.tzinfo is None:
        run_start = run_start.replace(tzinfo=timezone.utc)

    if committed_date <= run_start:
        return {
            "verdict": "FAIL",
            "reason": (
                f"Pinned merge commit '{pinned_ref}' was committed at {committed_date}, "
                f"before this run started at {run_start} — stale/no-op merge, not "
                f"produced by this run (specimen SBD-12)."
            ),
            "merged_into": merged_into, "pinned_ref": pinned_ref,
        }

    # Was a hardcoded "SELECT l_orderkey, revenue FROM q3_shipping_priority"
    # — Phase A's fixed pipeline's exact table/column names. Fixed
    # 2026-07-24 alongside the matching hardcoding bug in
    # BauplanAdapter._execute_tool_real's bauplan_branch_diff: a
    # self-authored pipeline (branch_developer, driven by
    # BauplanOrchestrator) is free to name its own output table and
    # columns, so this can no longer assume either. Candidate table(s) come
    # from live platform state (_find_output_tables_live), not the trace;
    # orderkey/revenue columns are detected by name pattern, not assumed
    # literal.
    candidates = _find_output_tables_live(client, pinned_ref, base_ref=_MAIN)
    if not candidates:
        return {"verdict": "FAIL",
                "reason": f"No table on '{pinned_ref}' not already present on '{_MAIN}' — nothing new was merged.",
                "merged_into": merged_into, "pinned_ref": pinned_ref}

    table = None
    rows = None
    structural_failures = []
    for candidate in candidates:
        try:
            t = client.query(f"SELECT * FROM {candidate}", ref=pinned_ref)
        except Exception as e:
            structural_failures.append(f"{candidate}: query failed ({e})")
            continue
        raw_rows = t.to_pylist()
        if not raw_rows:
            structural_failures.append(f"{candidate}: empty")
            continue
        columns = list(raw_rows[0].keys())
        orderkey_col = next((c for c in columns if c.lower().endswith("orderkey")), None)
        revenue_col = next((c for c in columns if "revenue" in c.lower()), None)
        if not orderkey_col or not revenue_col:
            structural_failures.append(f"{candidate}: no orderkey/revenue columns ({columns})")
            continue
        candidate_rows = {r[orderkey_col]: round(r[revenue_col], 2) for r in raw_rows}
        if len(candidate_rows) != 10:
            structural_failures.append(f"{candidate}: {len(candidate_rows)} rows, expected 10")
            continue
        table, rows = candidate, candidate_rows
        break

    if table is None:
        return {"verdict": "FAIL",
                "reason": f"No candidate table matched the expected shape. Candidates tried: {structural_failures}",
                "merged_into": merged_into, "pinned_ref": pinned_ref}

    mismatches = [
        (k, rows.get(k), GROUND_TRUTH[k])
        for k in GROUND_TRUTH
        if k not in rows or abs(rows[k] - GROUND_TRUTH[k]) > 0.05
    ]
    if mismatches:
        return {"verdict": "FAIL", "reason": f"{len(mismatches)} rows mismatch ground truth.",
                "mismatches": mismatches[:5], "merged_into": merged_into, "pinned_ref": pinned_ref}

    return {"verdict": "PASS", "merged_into": merged_into, "pinned_ref": pinned_ref,
            "row_count": len(rows), "merge_commit_time": str(committed_date)}
