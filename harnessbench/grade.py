"""Generic Grade Harness for Trace Evaluation.

This script parses all traces in a study directory, calculates generic process
metrics (tokens, turns, outcome), and defers to the TargetAdapter's grader()
for domain-specific correctness.
"""
import glob
import json
import os
from typing import Dict, Any, List

from harnessbench.adapter import TargetAdapter
from harnessbench.markers import extract_markers


def grade_study(study_dir: str, adapter: TargetAdapter) -> List[Dict[str, Any]]:
    """Iterate over all trace JSONL files in a study directory and grade them."""
    # Find all main orchestrator/monolith traces (those starting with trace_ and not _sub_)
    # Actually, we can just look at traces that have prompt_provenance to filter out sub_runs.
    trace_files = glob.glob(os.path.join(study_dir, "*.jsonl"))
    
    main_traces = []
    for tf in trace_files:
        is_main = False
        with open(tf, 'r') as f:
            for line in f:
                if "prompt_provenance" in line:
                    is_main = True
                    break
        if is_main:
            main_traces.append(tf)

    results = []
    for tf in main_traces:
        # Extract generic (and adapter-specific) markers
        markers = extract_markers(tf, adapter)
        
        # Determine domain correctness
        grader_fn = adapter.grader()
        
        grade_result = None
        if grader_fn:
            # Pass the trace to the adapter's grading logic
            grade_result = grader_fn(tf)
        
        # Combine
        combined = {
            "run_id": markers["run_id"],
            "markers": markers,
            "grade": grade_result
        }
        results.append(combined)
        
    return results
