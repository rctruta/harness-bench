"""Grade agent final answers against the SBD capsule's ground truth.

This is the SBD domain-specific Oracle implementation.
"""
import json
import os
import re
from statistics import mean
from typing import Dict, Any

# Assuming SBD results are relative to the execution root, or we can use AGENT_STUDY_DIR
SBD_RESULTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../sql-benchmarks-dagster/sql_benchmarks/experiments/results"))

DURATION_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:\\text\{)?\s*(ms|milliseconds|s\b|seconds)", re.IGNORECASE)
RATIO_RE = re.compile(r"[~≈]?(\d+(?:\.\d+)?)\s*(?:[x×]\b|\\times)")
EXP_ID_RE = re.compile(r"^[0-9a-f]{8}$")

DUR_TOL = 0.02
RATIO_TOL = 0.05


def load_ground_truth(exp_id: str):
    frag_dir = os.path.join(SBD_RESULTS_DIR, exp_id, "fragments")
    if not os.path.isdir(frag_dir):
        return None
    means, all_stats = {}, []
    for fn in os.listdir(frag_dir):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(frag_dir, fn)) as f:
            frag = json.load(f)
        part = frag["meta"]["partition"]
        eng = frag["meta"]["engine"]
        asset = frag["meta"].get("asset", "")
        raw = frag["metrics"].get("durations_raw") or [frag["metrics"]["duration_seconds"]]
        raw_ms = [v * 1000 for v in raw]
        m = mean(raw_ms)
        means[(asset, part, eng)] = m
        all_stats.extend(raw_ms)
        all_stats.append(m)
        all_stats.extend([min(raw_ms), max(raw_ms)])
        if len(raw_ms) >= 2:
            s = (sum((v - m) ** 2 for v in raw_ms) / (len(raw_ms) - 1)) ** 0.5
            all_stats.extend([s, m - s, m + s])
            all_stats.append(100 * s / m if m else 0)

    ratios = set()
    vals = list(means.values())
    for a in vals:
        for b in vals:
            if a and b and a != b:
                ratios.add(b / a)
                
    cfg = os.path.join(SBD_RESULTS_DIR, exp_id, "experiment_config.yaml")
    row_counts = []
    if os.path.exists(cfg):
        with open(cfg) as f:
            for line in f:
                mrow = re.match(r"\s+\w+:\s*([\d_]+)\s*$", line)
                if mrow:
                    try:
                        row_counts.append(int(mrow.group(1).replace("_", "")))
                    except ValueError:
                        pass
    for a in row_counts:
        for b in row_counts:
            if a and b and a != b:
                ratios.add(b / a)
    return means, all_stats, ratios


def _close(claim, truth, tol):
    return truth and abs(claim - truth) / abs(truth) <= tol


def extract_answer_and_exp(path: str):
    answer = None
    exp_ids = []
    for line in open(path, encoding="utf-8"):
        e = json.loads(line)
        if e["event"] == "final_answer":
            answer = e.get("content") or answer
        elif e["event"] == "tool_call":
            arg = (e.get("arguments") or {})
            eid = arg.get("experiment_id") if isinstance(arg, dict) else None
            if eid and EXP_ID_RE.match(str(eid)):
                exp_ids.append(eid)
    exp_id = max(set(exp_ids), key=exp_ids.count) if exp_ids else None
    return answer, exp_id


def sbd_grader(path: str) -> Dict[str, Any]:
    """The grader plugin for SBD."""
    answer, exp_id = extract_answer_and_exp(path)
    if not answer or not exp_id:
        return {"verdict": "NO-ANSWER"}
    gt = load_ground_truth(exp_id)
    if gt is None:
        return {"exp_id": exp_id, "verdict": "NO-CAPSULE"}
    means, all_stats, ratios = gt

    claims = []
    for num, unit in DURATION_RE.findall(answer):
        v = float(num)
        claims.append(v * 1000 if unit.lower().startswith("s") else v)

    covered = {k: any(_close(c, m, DUR_TOL) for c in claims) for k, m in means.items()}
    matched = [c for c in claims if any(_close(c, s, DUR_TOL) for s in all_stats)]
    unmatched = [c for c in claims if c not in matched]

    ratio_claims = [float(x) for x in RATIO_RE.findall(answer)]
    ratio_ok = [r for r in ratio_claims if any(_close(r, t, RATIO_TOL) for t in ratios)]

    coverage = sum(covered.values()) / len(covered) if covered else 0.0
    coverage_any = any(covered.values())
    
    if claims and coverage_any and not unmatched:
        verdict = "PASS"
    elif coverage_any and unmatched:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
        
    return {
        "exp_id": exp_id, "verdict": verdict,
        "coverage": round(coverage, 3),
        "duration_claims": len(claims), "matched": len(matched),
        "unmatched_claims_ms": [round(u, 3) for u in unmatched],
        "ratio_claims": len(ratio_claims), "ratio_matched": len(ratio_ok),
        "missing_means": [f"{a}/{p}/{e}" for (a, p, e), ok in covered.items() if not ok],
    }
