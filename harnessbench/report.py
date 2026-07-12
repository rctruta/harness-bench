"""Generate Markdown reports from graded agent traces."""
from collections import defaultdict
from typing import List, Dict, Any


def condition_label(flags: dict) -> str:
    """Short label from ablation flags for grouping."""
    if not flags:
        return "pre-provenance"
    if flags.get("architecture") == "specialist":
        return f"specialist:{flags.get('role')}"
    
    condition_keys = sorted(k for k in flags
                            if k not in ("architecture", "study_id", "cell", "rep", "role", "study_model"))
    if not condition_keys:
        return flags.get("architecture", "unknown")
        
    short = ",".join(
        f"{k}={'Y' if flags[k] else 'N'}"
        for k in condition_keys)
    return f"{flags.get('architecture', '?')}({short})"


def generate_report(graded_traces: List[Dict[str, Any]]) -> str:
    """Take a list of graded traces and render a markdown report."""
    if not graded_traces:
        return "No traces to report."
        
    by_condition = defaultdict(list)
    for gt in graded_traces:
        m = gt["markers"]
        lbl = f"{m.get('model', 'unknown')} | {condition_label(m['flags'])}"
        by_condition[lbl].append(gt)

    lines = []
    lines.append("# Harness Bench Report")
    lines.append("")
    
    for cond in sorted(by_condition.keys()):
        group = by_condition[cond]
        lines.append(f"## {cond} (n={len(group)})")
        
        # Build table
        lines.append("| Run ID | Outcome | Turns | Tokens | Grade | Details |")
        lines.append("|---|---|---|---|---|---|")
        
        for gt in group:
            m = gt["markers"]
            run_id = m["run_id"]
            outcome = m.get("outcome", "-")
            turns = m.get("turns", 0)
            tokens = m.get("tokens", 0)
            
            grade_obj = gt.get("grade")
            if grade_obj:
                verdict = grade_obj.get("verdict", "-")
                if verdict == "PASS":
                    details = "✅"
                elif verdict == "PARTIAL":
                    details = f"⚠️ Unmatched: {grade_obj.get('unmatched_claims_ms', [])}"
                else:
                    details = f"❌ Missing: {grade_obj.get('missing_means', [])}"
            else:
                verdict = "N/A"
                details = "-"
                
            lines.append(f"| {run_id} | {outcome} | {turns} | {tokens:,} | **{verdict}** | {details} |")
            
        lines.append("")
        
        # Summary stats
        successes = sum(1 for gt in group if gt.get("grade", {}).get("verdict") == "PASS")
        mean_tokens = sum(gt["markers"].get("tokens", 0) for gt in group) / len(group) if group else 0
        lines.append(f"**Summary:** {successes}/{len(group)} passed. Mean tokens: {mean_tokens:,.0f}")
        lines.append("")
        
    return "\n".join(lines)
