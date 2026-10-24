"""Grader invariants, derived from every grader defect this lab has found.

Across five separate incidents the grader — not the agent, not the platform —
was the failing component, and in each case it failed by producing a confident
VERDICT where it should have produced an ERROR. The mechanism was the same
every time: **the grader re-derived a fact instead of reading it from wherever
that fact is defined.**

  SBD-12  read "does the target branch hold the right data" -> passed
          vacuously against state left by an earlier, unrelated run.
  SBD-13  the fix for SBD-12 compared against the branch's CURRENT head, so
          re-grading an old trace after a later run touched the same branch
          produced a fresh PASS from someone else's commit.
  BP-1    tested `"error" in parsed` (key presence) rather than
          `parsed.get("error")` (value truthiness); every real success, which
          carries `"error": null`, was flagged as an error.
  BP-2    read only the trace file it was handed, so a merge performed inside
          a delegated specialist sub-run was invisible and a real PASS graded
          as "no merge found".
  BP-3    hardcoded the output table name, so it could not grade a pipeline
          that named its own output.
  MD-1    hand-reconstructed the study's ground-truth SQL, added a join that
          does not belong, and scored 8 correct model answers as failures.

This module encodes the rules those incidents imply. They are enforced
structurally where possible rather than documented and hoped for.

RULE 1  A grader MAY READ facts. It MUST NOT RECONSTRUCT them.
        Ground truth comes from the artifact that defines it — a file emitted
        at generation time, or a live query against the source of record.
        Never a transcribed literal. `GroundTruth` records which of those it
        was, and that provenance travels in the result.

RULE 2  "I cannot tell" is a first-class verdict.
        Verdict.UNGRADEABLE exists so a grader that lacks what it needs stops
        instead of guessing. Every one of the incidents above would have been
        caught at the point of failure had this been available and used.

RULE 3  Identity is pinned at event time, never re-derived at grade time.
        Grade against the exact commit/run/artifact id the trace itself
        recorded. Never "the current state of X" when X is shared.

RULE 4  A trace is the whole tree.
        Always traverse `delegate` events into specialist sub-runs.

RULE 5  Missing inputs fail loudly.
        No silent defaults, no empty-dict fallbacks.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from harnessbench.trace_utils import load_trace_events


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    # RULE 2. Not a synonym for FAIL. FAIL asserts the agent did not achieve
    # the goal; UNGRADEABLE asserts the INSTRUMENT could not determine it.
    # Conflating them is how a broken grader looks like a failing agent.
    UNGRADEABLE = "UNGRADEABLE"


class GroundTruthError(RuntimeError):
    """Ground truth could not be obtained. Never swallow this into a verdict."""


@dataclass
class GroundTruth:
    """A fact the grader compares against, plus how it was obtained.

    RULE 1. Construct only via `from_file` or `from_query`. There is
    deliberately no `from_literal` — a transcribed constant is the defect
    class this type exists to prevent.
    """
    value: Any
    provenance: str          # human-readable: which file / which query
    method: str              # "read_file" | "live_query"

    @classmethod
    def from_file(cls, path: str, key: Optional[str] = None) -> "GroundTruth":
        if not os.path.exists(path):
            raise GroundTruthError(
                f"ground-truth artifact missing: {path}. It must be emitted by "
                f"whatever generates the data; the grader will not reconstruct it."
            )
        with open(path) as f:
            data = json.load(f)
        if key is not None:
            if key not in data:
                raise GroundTruthError(f"key {key!r} not in {path} (have: {sorted(data)})")
            data = data[key]
        return cls(value=data, provenance=path, method="read_file")

    @classmethod
    def from_query(cls, runner: Callable[[], Any], description: str) -> "GroundTruth":
        """Derive live from the source of record (e.g. run the reference query
        against the canonical ref). Re-derivable, so it cannot drift."""
        try:
            value = runner()
        except Exception as e:
            raise GroundTruthError(f"could not derive ground truth via {description}: {e}") from e
        return cls(value=value, provenance=description, method="live_query")


@dataclass
class GraderResult:
    verdict: Verdict
    reason: str = ""
    ground_truth: Optional[GroundTruth] = None
    pinned_ref: Optional[str] = None      # RULE 3 — identity used, from the trace
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {"verdict": self.verdict.value}
        if self.reason:
            d["reason"] = self.reason
        if self.pinned_ref:
            d["pinned_ref"] = self.pinned_ref
        if self.ground_truth is not None:
            # Provenance travels with the verdict, so a reader can see whether
            # the number was read or derived without opening the grader.
            d["ground_truth_method"] = self.ground_truth.method
            d["ground_truth_provenance"] = self.ground_truth.provenance
        d.update(self.details)
        return d


def collect_all_events(trace_path: str) -> list:
    """RULE 4 — top-level events plus every delegated sub-run, flattened.

    Graders must use this, never `load_trace_events` directly, or a
    multi-stage run's real work is invisible (BP-2).
    """
    run_dir = os.path.dirname(trace_path)
    out: list = []

    def _scan(events: list) -> None:
        for e in events:
            out.append(e)
            if e.get("event") == "delegate" and e.get("sub_run_id"):
                _scan(load_trace_events(os.path.join(run_dir, f"{e['sub_run_id']}.jsonl")))

    _scan(load_trace_events(trace_path))
    return out


def result_is_error(result_str: str) -> bool:
    """BP-1 — VALUE truthiness, not key presence. Real successes carry
    `"error": null` and must not be read as errors."""
    try:
        parsed = json.loads(result_str or "{}")
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(parsed, dict):
        return False
    if parsed.get("error"):
        return True
    return str(parsed.get("status", "")).lower() in ("error", "failed")


def pinned_from_tool_result(events: list, tool_names: set, field_name: str) -> Optional[str]:
    """RULE 3 — pull the identity the trace's OWN successful tool result
    recorded (e.g. the commit hash returned by merge). Grade against that,
    never against current shared state."""
    pinned = None
    for e in events:
        if e.get("event") != "tool_result" or e.get("name") not in tool_names:
            continue
        if result_is_error(e.get("result") or ""):
            continue
        try:
            parsed = json.loads(e.get("result") or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if parsed.get(field_name):
            pinned = parsed[field_name]
    return pinned
