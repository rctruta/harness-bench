"""Shared raw-trace-traversal helpers.

Both the generic marker extractor (markers.py) and any adapter's grader
need the same low-level operation: read a trace JSONL file, follow
`delegate` events into specialist sub-run files, and collect facts from
`tool_call`/`tool_result` events. This module is the single place that
walk lives, so adapters never need to reimplement it (see the DRY note in
dual_agent_collaboration.md SBD-10 / SBD-11).
"""
import json
import os
import re
from typing import Dict, List, Tuple


def slugify(text: str) -> str:
    """File-safe lowercased slug. Was duplicated verbatim in api.py and
    trace.py; consolidated here as part of the same DRY pass as
    collect_tool_events (see specimen SBD-10/11)."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:30]


def load_trace_events(trace_path: str) -> List[dict]:
    """Read one trace JSONL file into a list of event dicts. Missing file
    returns an empty list rather than raising — a delegated sub-run that
    hasn't been written yet is a normal transient state, not an error."""
    if not os.path.exists(trace_path):
        return []
    events = []
    with open(trace_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def collect_tool_events(trace_path: str) -> Tuple[List[str], List[str]]:
    """Walk a trace file AND any delegated specialist sub-runs in the same
    directory. Returns (tool_names_called, distinct_execution_modes).

    execution_modes comes from the 'mode' field trace.tool_result() stamps
    (see trace.py) — "mock" | "real" | None (adapters that don't declare
    .mode). This is the mechanical half of catching a simulated run
    presented as real: any caller — markers.py at report time, or an
    adapter's own grader at grade time — gets the same ground truth.
    """
    run_dir = os.path.dirname(trace_path)
    tool_names: List[str] = []
    modes: List[str] = []

    def _scan(events: List[dict]) -> None:
        for e in events:
            ev = e.get("event")
            if ev == "tool_call":
                tool_names.append(e.get("name"))
            elif ev == "tool_result":
                m = e.get("mode")
                if m and m not in modes:
                    modes.append(m)
            elif ev == "delegate":
                sub_id = e.get("sub_run_id")
                if sub_id:
                    _scan(load_trace_events(os.path.join(run_dir, f"{sub_id}.jsonl")))

    _scan(load_trace_events(trace_path))
    return tool_names, modes


def _result_is_error(event: dict) -> bool:
    """Bug fixed 2026-07-24 (caught by Ramona questioning a grade): checked
    key PRESENCE ('error' in parsed) instead of the value's truthiness.
    BauplanAdapter's real success responses always include "error": null
    (mirroring state.error) — every successful call was being flagged as an
    error just for having that key. Now checks the value is truthy."""
    if event.get("error_reason"):
        return True
    result = event.get("result") or ""
    try:
        parsed = json.loads(result)
        if isinstance(parsed, dict) and parsed.get("error"):
            return True
        status = parsed.get("status") if isinstance(parsed, dict) else None
        if isinstance(status, str) and status.lower() in ("error", "failed"):
            return True
    except (json.JSONDecodeError, TypeError):
        pass
    return False


def detect_unrecovered_tool_errors(trace_path: str) -> List[str]:
    """Adapter-agnostic integrity check (specimen SBD-12): find any tool
    name whose LAST call in the trace was error-shaped, with no later
    successful call to the same tool name, yet the run still reached a
    final_answer. Returns the list of such tool names (empty = clean).

    This does not prove the agent lied — only that it reported done while
    a real signal of failure sat unaddressed in its own trace. That's
    exactly the shape of the SBD-10/SBD-12 incidents: a tool errored, the
    agent silently substituted something else, and the final answer never
    acknowledged it.
    """
    run_dir = os.path.dirname(trace_path)
    last_status: Dict[str, bool] = {}  # tool_name -> is_error
    saw_final_answer = False

    def _scan(events: List[dict]) -> None:
        nonlocal saw_final_answer
        for e in events:
            ev = e.get("event")
            if ev == "tool_result":
                last_status[e.get("name")] = _result_is_error(e)
            elif ev == "final_answer":
                saw_final_answer = True
            elif ev == "delegate":
                sub_id = e.get("sub_run_id")
                if sub_id:
                    _scan(load_trace_events(os.path.join(run_dir, f"{sub_id}.jsonl")))

    _scan(load_trace_events(trace_path))
    if not saw_final_answer:
        return []
    return sorted(name for name, is_err in last_status.items() if is_err)
