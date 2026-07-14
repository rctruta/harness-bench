import json
from typing import List, Dict, Any

def detect_uniform_failure(trace_paths: List[str]) -> bool:
    """
    Analyzes a list of trace paths (representing all runs in a cell).
    Returns True if the cell exhibits a uniform cross-model failure,
    indicating a harness defect rather than a model capability limit.
    """
    if not trace_paths:
        return False

    # For a uniform failure, every single run must exhibit infrastructure errors.
    runs_with_errors = 0
    total_runs = len(trace_paths)

    for path in trace_paths:
        has_infra_error = False
        with open(path, 'r') as f:
            for line in f:
                event = json.loads(line)
                if event.get("event") == "tool_result":
                    result = event.get("result", "")
                    error_reason = event.get("error_reason", "")
                    
                    # Look for explicit infrastructure errors in stdout/stderr or the harness error reason
                    if result and isinstance(result, str):
                        if "No such file or directory" in result or "command not found" in result:
                            has_infra_error = True
                            break
                    if error_reason and isinstance(error_reason, str):
                        if "No such file or directory" in error_reason or "command not found" in error_reason:
                            has_infra_error = True
                            break
        
        if has_infra_error:
            runs_with_errors += 1

    # If every run in the cell hit the exact same class of infrastructure error,
    # the harness is broken, not the models.
    return runs_with_errors == total_runs and total_runs > 1
