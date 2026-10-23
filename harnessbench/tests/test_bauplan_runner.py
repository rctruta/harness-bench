"""The Bauplan study pipeline: the free half, and the half that spends.

This file used to hold one test that ran the whole pipeline against three
live providers on every `pytest` invocation. The Bauplan tool was mocked;
the models were not, so a six-cell matrix of real completions ran before
every push, took 57-76 seconds, and failed whenever a provider rate-limited.

Split on 2026-10-23:

  the free half   contract shape, matrix size, grading, and the mock
                  watermark -- deterministic, no provider touched, runs on
                  every push the way the old test was supposed to.

  the paid half   that three real models actually drive the pipeline end to
                  end. Marked `paid` and deselected unless --run-paid.

The paid test also asserts far more than the old one did. `assert
len(results) >= 2` passed when four of six cells produced nothing, which is
the same shape as the NO-ANSWER rows the metrics module surfaced across the
corpus. A test permitted to spend money asserts on every cell it paid for.
"""
import os
import sys

# the repository root, found from this file rather than from one machine
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

import pytest                                               # noqa: E402

from harnessbench.api import check_environment, run_benchmark  # noqa: E402
from harnessbench.grade import grade_study                  # noqa: E402
from harnessbench.registry import load_adapter              # noqa: E402
from harnessbench.report import generate_report             # noqa: E402

CONTRACT = os.path.join(REPO_ROOT, "contracts", "bauplan_study.yaml")
TARGET = "bauplan_lakehouse"
ALIAS = "bauplan-lakehouse"

# 3 models x 2 cells x 1 replication. Named rather than inlined so the free
# and paid tests cannot drift apart on what the matrix is.
EXPECTED_MATRIX = 6


# --------------------------------------------------------------- free

def test_preflight_and_matrix_shape():
    """The contract loads, the target is healthy, and the matrix is 6 cells.

    No provider is touched: the Bauplan adapter is mock by default and a
    dry run plans the matrix without calling a model. This is the assertion
    the old test made before it started spending.
    """
    chk = check_environment(CONTRACT, TARGET)
    assert chk["status"] == "ok", f"Pre-flight failed: {chk}"

    dry = run_benchmark(CONTRACT, TARGET, dry_run=True, alias=ALIAS)
    assert dry["status"] == "dry_run"
    assert dry["matrix_size"] == EXPECTED_MATRIX


def _graded(run_id, modes):
    """One graded row in the shape report.generate_report consumes."""
    return {"run_id": run_id, "grade": {"verdict": "PASS"},
            "markers": {"run_id": run_id, "model": "m1", "flags": {},
                        "execution_modes": modes}}


def test_report_refuses_mock_traces_without_acknowledgement():
    """A mock run rendered as a report is a fabricated study.

    Gate C / specimen SBD-10. Both directions are asserted, because only
    the refusal is the gate -- a test that checks the watermark alone would
    still pass if the refusal were removed.

    Deterministic: no pipeline, no provider, fixture rows only. The first
    version of this test built rows the renderer could not consume and so
    skipped on every run, which is a test that proves nothing while
    reporting green.
    """
    from harnessbench.report import MockTraceError

    mock_rows = [_graded("r1", ["mock"])]
    with pytest.raises(MockTraceError):
        generate_report(mock_rows, allow_mock=False)

    acknowledged = generate_report(mock_rows, allow_mock=True)
    assert "SIMULATED" in acknowledged, "the mock watermark must be present"

    # A trace with no mode stamp is unknown, not mock, and must not be
    # refused -- legacy traces predate the field.
    generate_report([_graded("r2", None)], allow_mock=False)


# --------------------------------------------------------------- paid

@pytest.mark.paid
def test_bauplan_benchmark_run_live():
    """Three real models drive the pipeline end to end.

    Billable: six completions against gemini-2.5-flash,
    claude-haiku-4-5 and gpt-4o-mini. Run with --run-paid.

    Every assertion below is on the full matrix. The previous version
    asserted `len(results) >= 2`, which passed while four of six cells
    produced nothing -- paying for six runs and checking two.
    """
    chk = check_environment(CONTRACT, TARGET)
    assert chk["status"] == "ok", f"Pre-flight failed: {chk}"

    outcomes = run_benchmark(CONTRACT, TARGET, dry_run=False, alias=ALIAS)
    assert outcomes["status"] == "complete"
    assert "runs_dir" in outcomes

    adapter = load_adapter(TARGET)
    results = grade_study(outcomes["runs_dir"], adapter)

    # Every cell paid for must come back graded.
    assert len(results) == EXPECTED_MATRIX, (
        f"paid for {EXPECTED_MATRIX} cells, graded {len(results)}. "
        f"A missing cell is a silent failure, not a smaller sample.")

    # And every one must carry a verdict the grader recognises. A row with
    # no grade, or graded NO-ANSWER, means the model returned nothing -- the
    # spend produced no observation and the test must say so.
    allowed = {"PASS", "FAIL", "PARTIAL"}
    verdicts = []
    for row in results:
        g = row.get("grade")
        verdicts.append(g.get("verdict") if isinstance(g, dict) else g)
    unanswered = [v for v in verdicts if v not in allowed]
    assert not unanswered, (
        f"{len(unanswered)} of {EXPECTED_MATRIX} cells produced no gradeable "
        f"answer: {unanswered}. Money was spent and nothing was measured.")

    report = generate_report(results, allow_mock=True)
    assert "SIMULATED" in report, "the mock watermark must be present"
