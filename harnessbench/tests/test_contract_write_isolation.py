"""Per-replication write isolation gate (specimen SBD-14).

The gate this file pins is the one that was MISSING when a 24-replication
Bauplan study sent every replication into one shared branch. Reps 2+ hit
genuine MERGE_CONFLICTs and a paid batch measured the collision instead of
the architecture. A mitigation (actionable conflict text) shipped first;
this is the actual prevention.
"""
import os
import tempfile

import pytest

from harnessbench.contracts import find_pinned_write_target, load_contract


def _write(tmpdir, body):
    p = os.path.join(tmpdir, "c.yaml")
    with open(p, "w") as f:
        f.write(body)
    return p


_SHARED_GOAL_BODY = """\
driver: monolith
replications: 3
model: gpt-4o
goal: >
  Compute the result on your own branch, then merge it into
  'ramona.sandbox-matched' (not main).
cells:
  c1:
    flags: {}
"""


def test_refuses_multi_replication_with_pinned_target():
    """The exact shape of the real SBD-14 contract must not load."""
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(ValueError) as e:
            load_contract(_write(d, _SHARED_GOAL_BODY))
        msg = str(e.value)
        assert "ramona.sandbox-matched" in msg
        assert "SBD-14" in msg
        assert "allow_shared_write_target" in msg, "must name the opt-out"


def test_single_replication_is_allowed():
    """One replication cannot collide with itself — must not be blocked."""
    with tempfile.TemporaryDirectory() as d:
        sid, c = load_contract(_write(d, _SHARED_GOAL_BODY.replace("replications: 3", "replications: 1")))
        assert c["replications"] == 1


def test_explicit_opt_out_is_honoured():
    """Sharing on purpose stays possible — the gate informs, it doesn't trap."""
    with tempfile.TemporaryDirectory() as d:
        body = _SHARED_GOAL_BODY.replace(
            "driver: monolith", "driver: monolith\nallow_shared_write_target: true")
        sid, c = load_contract(_write(d, body))
        assert c["replications"] == 3


def test_goal_without_pinned_target_is_allowed():
    """Agent chooses its own destination -> no shared-write hazard."""
    with tempfile.TemporaryDirectory() as d:
        body = _SHARED_GOAL_BODY.replace(
            "merge it into\n  'ramona.sandbox-matched' (not main).",
            "merge it into a sandbox branch you name yourself.")
        sid, c = load_contract(_write(d, body))
        assert c["replications"] == 3


@pytest.mark.parametrize("goal,expected", [
    ("merge it into 'ramona.sandbox-b'", "ramona.sandbox-b"),
    ("publish the table into `prod.reporting`", "prod.reporting"),
    ('write the output into "results/final"', "results/final"),
    # Must NOT fire on ordinary prose that merely quotes a name.
    ("read from 'tpch_1.orders' and summarise", None),
    ("the BUILDING segment, ordered by revenue", None),
    ("merge into a branch of your choosing", None),
])
def test_detector_precision(goal, expected):
    assert find_pinned_write_target(goal) == expected
