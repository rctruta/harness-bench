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


class MockTraceError(RuntimeError):
    """Raised when graded_traces contain simulated (mock) tool results and
    the caller did not explicitly acknowledge that with allow_mock=True.

    This is the mechanical half of the fix for the Bauplan incident: an
    adapter can still run in mock mode, but the report generator can no
    longer render output that looks like a real run without a human
    explicitly opting in. See specimen SBD-10 (dual_agent_collaboration.md).
    """


def generate_report(graded_traces: List[Dict[str, Any]], allow_mock: bool = False) -> str:
    """Take a list of graded traces and render a markdown report.

    Raises MockTraceError if any trace ran against a mock/simulated adapter
    and allow_mock is not explicitly set to True. Traces with no mode stamp
    at all (legacy traces, or adapters that don't declare .mode) are treated
    as unknown, not mock — they pass through with a neutral label.
    """
    if not graded_traces:
        return "No traces to report."

    mock_run_ids = [
        gt["markers"]["run_id"] for gt in graded_traces
        if "mock" in (gt["markers"].get("execution_modes") or [])
    ]
    if mock_run_ids and not allow_mock:
        raise MockTraceError(
            f"{len(mock_run_ids)} of {len(graded_traces)} traces ran in MOCK mode "
            f"(simulated tool results, not a real target): {mock_run_ids}. "
            "This report would misrepresent a simulated run as real. "
            "Pass allow_mock=True (CLI: --allow-mock) if you intend that, "
            "and the report will be watermarked accordingly."
        )

    by_condition = defaultdict(list)
    for gt in graded_traces:
        m = gt["markers"]
        lbl = f"{m.get('model', 'unknown')} | {condition_label(m['flags'])}"
        by_condition[lbl].append(gt)

    lines = []
    lines.append("# Harness Bench Report")
    if mock_run_ids:
        lines.append("")
        lines.append(f"> ⚠️ **SIMULATED — {len(mock_run_ids)} of {len(graded_traces)} traces ran "
                     "in MOCK mode.** Tool results were fabricated by the adapter, not produced "
                     "by a real target. Do not present this report as a live run.")
    lines.append("")

    for cond in sorted(by_condition.keys()):
        group = by_condition[cond]
        lines.append(f"## {cond} (n={len(group)})")

        # Build table
        lines.append("| Run ID | Mode | Outcome | Turns | Tokens | Grade | Details |")
        lines.append("|---|---|---|---|---|---|---|")

        for gt in group:
            m = gt["markers"]
            run_id = m["run_id"]
            modes = m.get("execution_modes") or []
            mode_label = "/".join(modes) if modes else "unknown"
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

            lines.append(f"| {run_id} | {mode_label} | {outcome} | {turns} | {tokens:,} | **{verdict}** | {details} |")

        lines.append("")

        # Summary stats
        successes = sum(1 for gt in group if gt.get("grade", {}).get("verdict") == "PASS")
        mean_tokens = sum(gt["markers"].get("tokens", 0) for gt in group) / len(group) if group else 0
        lines.append(f"**Summary:** {successes}/{len(group)} passed. Mean tokens: {mean_tokens:,.0f}")
        lines.append("")

    return "\n".join(lines)
