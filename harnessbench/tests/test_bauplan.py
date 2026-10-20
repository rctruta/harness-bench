import sys
import os
# the repository root, found from this file rather than from one machine
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import pytest
from harnessbench.registry import load_adapter

def test_bauplan_adapter_tools_and_gates():
    adapter = load_adapter("bauplan_lakehouse")
    assert adapter.name == "bauplan_lakehouse"

    tools = adapter.tools()
    assert len(tools) == 9  # +bauplan_write_and_run, +bauplan_ensure_target_branch
    tool_names = [t["function"]["name"] for t in tools]
    assert "bauplan_checkout_branch" in tool_names
    assert "bauplan_run" in tool_names
    assert "bauplan_branch_diff" in tool_names
    assert "bauplan_merge_branch" in tool_names

    roles = adapter.roles()
    assert "branch_developer" in roles
    assert "auditor" in roles

    # Verify Code Gate preconditions
    dev = roles["branch_developer"]
    assert "bauplan_run" in dev.tool_preconditions
    pre_req, refusal_msg = dev.tool_preconditions["bauplan_run"]
    assert pre_req == "bauplan_checkout_branch"
    assert "blocked" in refusal_msg.lower() or "refused" in refusal_msg.lower()

    auditor = roles["auditor"]
    assert "bauplan_merge_branch" in auditor.tool_preconditions
    pre_req, refusal_msg = auditor.tool_preconditions["bauplan_merge_branch"]
    assert pre_req == "bauplan_branch_diff"

def test_bauplan_workflow_execution():
    adapter = load_adapter("bauplan_lakehouse")
    
    # 1. Checkout
    r1 = adapter.execute_tool("bauplan_checkout_branch", {"branch_name": "ramona.feature-etl"})
    assert "ramona.feature-etl" in r1

    # 2. Table get
    r2 = adapter.execute_tool("bauplan_table_get", {"table_ref": "bauplan.taxi_fhvhv"})
    assert "taxi_fhvhv" in r2

    # 3. Dry run
    r3 = adapter.execute_tool("bauplan_run_dry_run", {"pipeline_path": "pipelines/clean_trips"})
    assert "dry_run_success" in r3

    # 4. Materialize run
    r4 = adapter.execute_tool("bauplan_run", {"pipeline_path": "pipelines/clean_trips"})
    assert "job_9981a2" in r4

    # 5. Diff
    r5 = adapter.execute_tool("bauplan_branch_diff", {"target_ref": "main"})
    assert "clean" in r5

    # 6. Merge
    r6 = adapter.execute_tool("bauplan_merge_branch", {"branch_name": "ramona.feature-etl", "into_ref": "main"})
    assert "merged" in r6

def _write_trace(tmp_path, tool_names, mode="mock"):
    """Build a real trace JSONL and return its path — grade_study() (and
    the SBD reference adapter) call the grader with a PATH, not a dict.
    The old version of this test passed a dict directly, which matched a
    bug in BauplanAdapter's grader rather than the real calling convention;
    see Gate C / specimen SBD-10."""
    import tempfile
    from harnessbench.trace import AgentTrace
    from harnessbench.adapters.bauplan import BauplanAdapter

    adapter = BauplanAdapter(mock_mode=(mode == "mock"))
    runs_dir = tmp_path or tempfile.mkdtemp()
    t = AgentTrace(goal="test", model="fake", agents_md_loaded=False,
                   max_turns=10, runs_dir=runs_dir)
    for i, name in enumerate(tool_names):
        args = {"branch_name": "ramona.feature-etl"} if "branch" in name or "merge" in name else \
               ({"pipeline_path": "p"} if "run" in name else {"target_ref": "main"})
        result = adapter.execute_tool(name, args)
        t.tool_call(turn=i + 1, tool_call_id=f"c{i}", name=name, arguments=args)
        t.tool_result(turn=i + 1, tool_call_id=f"c{i}", name=name, result=result, mode=adapter.mode)
    t.run_end(outcome="final_answer", turns_used=len(tool_names))
    return t.path


def test_bauplan_grader(tmp_path):
    adapter = load_adapter("bauplan_lakehouse")
    grader = adapter.grader()

    # Pass trace
    pass_path = _write_trace(str(tmp_path), [
        "bauplan_checkout_branch", "bauplan_run", "bauplan_branch_diff", "bauplan_merge_branch"
    ])
    grade = grader(pass_path)
    assert grade["verdict"] == "PASS"
    assert grade["simulated"] is True  # built with mock_mode=True above

    # Fail trace (merged without diff verification)
    fail_path = _write_trace(str(tmp_path), [
        "bauplan_checkout_branch", "bauplan_run", "bauplan_merge_branch"
    ])
    assert grader(fail_path)["verdict"] == "FAIL"


def test_bauplan_grader_flags_real_mode_correctly():
    """Gate C: the grader independently re-derives simulated status from the
    raw trace's mode stamps, not from any adapter self-report at report time."""
    import tempfile
    path = _write_trace(tempfile.mkdtemp(), [
        "bauplan_checkout_branch", "bauplan_branch_diff", "bauplan_merge_branch"
    ], mode="mock")
    adapter = load_adapter("bauplan_lakehouse")
    grade = adapter.grader()(path)
    assert grade["simulated"] is True
