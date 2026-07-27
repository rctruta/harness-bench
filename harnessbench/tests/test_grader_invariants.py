"""The instrument's own regression corpus.

THE MECHANISM: every grader defect this lab discovers becomes a permanent
test here, at the moment it is found. A fix without an entry in this file is
not finished. That is what makes the instrument self-repairing in the only
sense that actually holds — not that it detects its own faults, but that a
fault, once found, cannot silently return.

Each test names the incident it pins (see graders/base.py for the catalogue).
When you find defect N+1: add a case here FIRST, watch it fail, then fix.
"""
import json
import os
import tempfile

import pytest

from harnessbench.graders.base import (
    GraderResult,
    GroundTruth,
    GroundTruthError,
    Verdict,
    collect_all_events,
    pinned_from_tool_result,
    result_is_error,
)


# --- BP-1: key presence vs value truthiness -------------------------------
@pytest.mark.parametrize("payload,expected", [
    ('{"status": "ok", "error": null}', False),   # real success — MUST NOT be an error
    ('{"status": "SUCCESS", "error": null}', False),
    ('{"error": "boom"}', True),
    ('{"status": "error", "error": null}', True),
    ('{"status": "FAILED"}', True),
    ('not json at all', False),
])
def test_bp1_error_detection_uses_value_not_key(payload, expected):
    assert result_is_error(payload) is expected


# --- MD-1 / RULE 1: ground truth is read or derived, never transcribed ----
def test_rule1_no_literal_constructor_exists():
    """The absence of `from_literal` is the enforcement."""
    assert not hasattr(GroundTruth, "from_literal")


def test_rule1_missing_artifact_raises_not_defaults():
    with pytest.raises(GroundTruthError):
        GroundTruth.from_file("/nonexistent/ground_truth.json")


def test_rule1_provenance_is_recorded():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "gt.json")
        json.dump({"task_a": 42}, open(p, "w"))
        gt = GroundTruth.from_file(p, key="task_a")
        assert gt.value == 42
        assert gt.method == "read_file" and p in gt.provenance


def test_rule1_derivation_failure_surfaces():
    def boom():
        raise ValueError("db unreachable")
    with pytest.raises(GroundTruthError):
        GroundTruth.from_query(boom, "reference query")


# --- BP-2: a trace is the whole tree --------------------------------------
def test_bp2_traversal_follows_delegate_subruns():
    """A merge inside a delegated sub-run must be visible to the grader."""
    with tempfile.TemporaryDirectory() as d:
        sub = "trace_x_auditor"
        with open(os.path.join(d, f"{sub}.jsonl"), "w") as f:
            f.write(json.dumps({"event": "tool_result", "name": "bauplan_merge_branch",
                                "result": '{"status":"merged","commit":"b@deadbeef"}'}) + "\n")
        top = os.path.join(d, "trace_x.jsonl")
        with open(top, "w") as f:
            f.write(json.dumps({"event": "run_start"}) + "\n")
            f.write(json.dumps({"event": "delegate", "sub_run_id": sub}) + "\n")

        flat = collect_all_events(top)
        names = [e.get("name") for e in flat]
        assert "bauplan_merge_branch" in names, "sub-run work invisible — BP-2 regression"


# --- SBD-13 / RULE 3: pin identity recorded at event time ------------------
def test_sbd13_pins_identity_from_the_traces_own_result():
    events = [
        {"event": "tool_result", "name": "merge_branch",
         "result": '{"status":"merged","commit":"branch@aaa111"}'},
    ]
    assert pinned_from_tool_result(events, {"merge_branch"}, "commit") == "branch@aaa111"


def test_sbd13_ignores_identity_from_a_failed_call():
    """A failed merge must not contribute a ref to grade against."""
    events = [
        {"event": "tool_result", "name": "merge_branch",
         "result": '{"status":"error","error":"MERGE_CONFLICT","commit":"branch@bbb222"}'},
    ]
    assert pinned_from_tool_result(events, {"merge_branch"}, "commit") is None


# --- RULE 2: "cannot tell" is distinct from "agent failed" ----------------
def test_rule2_ungradeable_is_distinct_from_fail():
    assert Verdict.UNGRADEABLE != Verdict.FAIL
    assert {v.value for v in Verdict} == {"PASS", "FAIL", "UNGRADEABLE"}


def test_rule2_result_carries_provenance_into_output():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "gt.json")
        json.dump({"v": 1}, open(p, "w"))
        r = GraderResult(verdict=Verdict.PASS, ground_truth=GroundTruth.from_file(p))
        out = r.to_dict()
        assert out["verdict"] == "PASS"
        assert out["ground_truth_method"] == "read_file"


# --- BP-3 / MD-1: the Bauplan reference is extracted, not retyped ---------
def test_bp3_reference_query_is_extracted_from_the_pipeline_source():
    from harnessbench.graders.bauplan_q3_reference import extract_reference
    ref = extract_reference()
    # filters live in the decorator, not the SQL — retyping them is the defect
    filters = {v["filter"] for v in ref["inputs"].values()}
    assert "c_mktsegment = 'BUILDING'" in filters
    assert any("1995-03-15" in (f or "") for f in filters)
    assert "SUM(l.l_extendedprice * (1 - l.l_discount))" in ref["sql"]


def test_bp3_grader_has_no_hardcoded_ground_truth_dict():
    """The transcribed GROUND_TRUTH dict must stay gone."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "graders", "bauplan_q3_ground_truth.py")).read()
    assert "GROUND_TRUTH = {" not in src, "hand-copied ground truth reintroduced"
