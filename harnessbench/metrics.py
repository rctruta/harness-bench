"""Every number this project would quote outward, derived rather than typed.

The problem this exists for. The README's summary line -- "16
content-addressed studies, 7 models, 110+ graded runs" -- appears in the
README and nowhere else. No code produces it. It was typed once and has been
read as authoritative since, which is the same shape as "416" in
ai-security-testbed: a true-ish number that lost the definition it needed and
could then be quoted as anything close.

Two things make this corpus harder to count than it looks, and both are
recorded in the definitions below rather than left for a reader to infer:

RUNS/ IS GITIGNORED. These metrics describe the corpus present on this
machine. A fresh clone has no runs/ and every count is zero -- which is
correct, not broken, and why a claim over these must declare its
precondition rather than fail.

MODE MATTERS. analysis.trace_mode already separates real execution from
mock, because a rate computed over a mixed set means nothing. 434 of 671
trace files predate the mode field entirely and report None. An aggregate
that silently folds those in is the failure TraceSet was built to prevent.

    python -m harnessbench.cli metrics
    python -m harnessbench.cli metrics --name graded_runs
"""
from __future__ import annotations

import glob
import json
import os
import re
from collections import Counter
from typing import Dict, List

from pydantic import BaseModel

from .analysis import trace_mode

RUNS_DIR = os.environ.get("HARNESSBENCH_RUNS_DIR", "runs")
CONTRACTS_DIR = os.environ.get("HARNESSBENCH_CONTRACTS_DIR", "contracts")

# A content-addressed run directory: timestamp plus a short content hash.
CONTENT_ADDRESSED = re.compile(r"\d{8}_\d{6}_[0-9a-f]{8}$")
GRADED_FILE = "graded_traces.json"


class Metric(BaseModel):
    """A derived number and the sentence saying what it counts."""
    name: str
    value: int
    definition: str
    derived_from: str = "runs/ on this machine (gitignored)"


def _graded() -> Counter:
    """Grades recoverable from graded_traces.json files, by verdict."""
    grades: Counter = Counter()
    for path in glob.glob(os.path.join(RUNS_DIR, "**", GRADED_FILE),
                          recursive=True):
        try:
            rows = json.load(open(path, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in rows:
            g = row.get("grade")
            if isinstance(g, dict):
                g = g.get("verdict")
            grades[g or "UNLABELLED"] += 1
    return grades


def all_metrics() -> List[Metric]:
    traces = glob.glob(os.path.join(RUNS_DIR, "**", "trace_*.jsonl"),
                       recursive=True)
    modes = Counter(trace_mode(p) for p in traces)
    grades = _graded()
    answered = sum(n for g, n in grades.items()
                   if g in ("PASS", "PARTIAL", "FAIL"))

    study_dirs = [d for d in glob.glob(os.path.join(RUNS_DIR, "*"))
                  if os.path.isdir(d)]
    addressed = [d for d in glob.glob(os.path.join(RUNS_DIR, "*", "*"))
                 if os.path.isdir(d) and CONTENT_ADDRESSED.search(d)]

    return [
        Metric(name="study_groups", value=len(study_dirs),
               definition="Top-level directories under runs/, one per study "
                          "family. NOT the same as content-addressed runs: a "
                          "family holds many."),
        Metric(name="content_addressed_runs", value=len(addressed),
               definition="Run directories named <timestamp>_<hash>. This is "
                          "what 'content-addressed' refers to."),
        Metric(name="trace_files", value=len(traces),
               definition="Files matching trace_*.jsonl. A file exists "
                          "whether or not the run produced a gradeable "
                          "answer, so this counts attempts."),
        Metric(name="traces_real_mode", value=modes.get("real", 0),
               definition="Traces that touched the real target at least once, "
                          "per analysis.trace_mode. The only set over which a "
                          "rate about real behaviour may be computed."),
        Metric(name="traces_mock_mode", value=modes.get("mock", 0),
               definition="Traces whose tool results were mocked throughout. "
                          "Never to be folded into a real-mode rate."),
        Metric(name="traces_mode_unlabelled", value=modes.get(None, 0),
               definition="Traces predating the mode field, so neither real "
                          "nor mock can be asserted of them. Counted "
                          "separately because silently including them is the "
                          "failure TraceSet exists to prevent."),
        Metric(name="graded_runs", value=sum(grades.values()),
               definition="Rows across all graded_traces.json files on this "
                          "machine. Grading recoverable TODAY -- runs/ is "
                          "gitignored and prunable, so this is a floor, not a "
                          "history of everything ever graded."),
        Metric(name="graded_runs_answered", value=answered,
               definition="Graded rows whose verdict is PASS, PARTIAL or "
                          "FAIL. The rest are NO-ANSWER: graded, but the "
                          "model produced nothing to grade."),
        Metric(name="graded_runs_passed", value=grades.get("PASS", 0),
               definition="Graded rows with verdict PASS."),
        Metric(name="contracts", value=len(
            glob.glob(os.path.join(CONTRACTS_DIR, "*.yaml"))),
               definition="Study contracts committed to the repository. "
                          "Unlike runs/, these are version-controlled, so "
                          "this number is reproducible from a fresh clone.",
               derived_from="contracts/ (tracked)"),
    ]


def as_dict() -> Dict[str, Dict]:
    return {m.name: m.model_dump() for m in all_metrics()}


def get(name: str) -> Metric:
    for m in all_metrics():
        if m.name == name:
            return m
    known = ", ".join(m.name for m in all_metrics())
    raise KeyError(f"no metric named {name!r}. Known: {known}")
