"""Regression tests for the mode gate (near-miss 2026-07-30).

The rule from grader_invariants.md: every defect becomes a permanent test at
the moment it is found. This one was a near-miss rather than a shipped defect
-- the wrong claim was caught before it reached the maintainer -- but the
mechanism was identical to the shipped ones, so it gets the same treatment.
"""
import pytest

from harnessbench.analysis import (MixedModeError, load_traces, require_real,
                                   trace_mode)


def _write(tmp_path, name, modes):
    p = tmp_path / name
    lines = [{"event": "tool_result", "mode": m} for m in modes]
    p.write_text("\n".join(__import__("json").dumps(x) for x in lines))
    return p


def test_reproduces_the_near_miss(tmp_path):
    """The exact 2026-07-30 shape: two mock cells + one real cell.

    Globbing all three and computing a rate is what produced the false
    'skills prevent the error' conclusion. It must now raise.
    """
    _write(tmp_path, "trace_skills_default.jsonl", ["mock"] * 353)
    _write(tmp_path, "trace_code_gates.jsonl", ["mock"] * 305)
    _write(tmp_path, "trace_skills_full.jsonl", ["real"] * 148)

    with pytest.raises(MixedModeError, match="spans execution modes"):
        load_traces(str(tmp_path / "*.jsonl"), mode=None)


def test_default_is_real_only(tmp_path):
    """The safe default: counting simulated runs as evidence is the common
    mistake, so 'real' is what you get unless you ask otherwise."""
    _write(tmp_path, "a.jsonl", ["mock"] * 10)
    _write(tmp_path, "b.jsonl", ["real"] * 5)

    ts = load_traces(str(tmp_path / "*.jsonl"))
    assert len(ts.paths) == 1
    assert ts.paths[0].endswith("b.jsonl")


def test_mixing_is_possible_but_must_be_deliberate(tmp_path):
    _write(tmp_path, "a.jsonl", ["mock"])
    _write(tmp_path, "b.jsonl", ["real"])

    ts = load_traces(str(tmp_path / "*.jsonl"), mode=None, allow_mixed=True)
    assert len(ts.paths) == 2
    assert ts.is_mixed
    # The composition travels with the data so a caller cannot report a rate
    # without having the means to know it is uninterpretable.
    assert ts.modes["real"] == 1 and ts.modes["mock"] == 1


def test_a_single_real_call_makes_the_trace_real(tmp_path):
    """Conservative direction: a real observation must never hide inside a
    trace classified as simulation."""
    p = _write(tmp_path, "mixed.jsonl", ["mock"] * 20 + ["real"])
    assert trace_mode(str(p)) == "real"


def test_unlabelled_traces_are_not_silently_treated_as_real(tmp_path):
    """Older traces predate the mode field. Absence of evidence is not
    evidence of realness."""
    p = tmp_path / "old.jsonl"
    p.write_text('{"event": "tool_result"}')
    assert trace_mode(str(p)) is None
    assert load_traces(str(tmp_path / "*.jsonl"), mode="real").paths == []


def test_require_real_refuses_to_bless_a_dirty_set(tmp_path):
    _write(tmp_path, "a.jsonl", ["mock"])
    ts = load_traces(str(tmp_path / "*.jsonl"), mode=None, allow_mixed=True)
    with pytest.raises(MixedModeError, match="Do not quote"):
        require_real(ts)
