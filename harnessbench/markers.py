"""Extract generic behavioral markers from agent traces.

This strips the domain-specific logic out of SBD's original analysis script.
It calculates tokens, turns, outcomes, and identifies the first tool used.
"""
import json
import os
from typing import Dict, Any

from harnessbench.adapter import TargetAdapter


def _specialist_tokens(run_id: str, runs_dir: str) -> int:
    """Sum prompt+completion tokens of one specialist's trace."""
    path = os.path.join(runs_dir, f"{run_id}.jsonl")
    if not os.path.exists(path):
        return 0
    total = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            if e.get("event") == "model_response" and e.get("usage"):
                total += (e["usage"].get("prompt_tokens") or 0) + \
                         (e["usage"].get("completion_tokens") or 0)
    return total


def extract_generic_markers(path: str) -> Dict[str, Any]:
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    markers = {
        "run_id": os.path.basename(path).removesuffix(".jsonl"),
        "model": None, "flags": {}, "composition": None,
        "outcome": None, "turns": 0, "tokens": 0,
        "first_tool": None,
    }
    
    for e in events:
        ev = e["event"]
        if ev == "run_start":
            markers["model"] = e.get("model")
        elif ev == "prompt_provenance":
            markers["flags"] = e.get("ablation_flags") or {}
            comps = e.get("components") or {}
            parts = []
            for name in sorted(comps):
                v = comps[name]
                parts.append(f"{name}:{v['sha256'][:8] if v else 'ABSENT'}")
            markers["composition"] = "|".join(parts)
        elif ev == "model_response":
            u = e.get("usage") or {}
            markers["tokens"] += (u.get("prompt_tokens") or 0) + (u.get("completion_tokens") or 0)
        elif ev == "tool_call":
            name = e.get("name")
            if markers["first_tool"] is None:
                markers["first_tool"] = name
        elif ev == "run_end":
            markers["outcome"] = e.get("outcome")
            markers["turns"] = e.get("turns_used") or 0
        elif ev == "delegate":
            sub = e.get("sub_run_id")
            if sub:
                markers["tokens"] += _specialist_tokens(sub, os.path.dirname(path))

    return markers


def extract_markers(path: str, adapter: TargetAdapter) -> Dict[str, Any]:
    """Extract generic markers and supplement with target-specific markers."""
    base = extract_generic_markers(path)
    
    for marker_name, extractor in adapter.markers().items():
        base[marker_name] = extractor(path)
        
    return base
