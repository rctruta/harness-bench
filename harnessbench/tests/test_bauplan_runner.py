import sys
import os
sys.path.insert(0, "/Users/ramona/Projects/harness-bench")

import pytest
from harnessbench.api import check_environment, run_benchmark
from harnessbench.registry import load_adapter
from harnessbench.grade import grade_study
from harnessbench.report import generate_report

def test_bauplan_benchmark_run():
    contract_path = "/Users/ramona/Projects/harness-bench/contracts/bauplan_study.yaml"
    target_name = "bauplan_lakehouse"

    # Pre-flight check
    chk = check_environment(contract_path, target_name)
    assert chk["status"] == "ok", f"Pre-flight failed: {chk}"

    # Run benchmark in dry-run mode
    dry_outcomes = run_benchmark(contract_path, target_name, dry_run=True, alias="bauplan-lakehouse")
    assert dry_outcomes["status"] == "dry_run"
    # contract declares 3 models (gemini-2.5-flash, claude-haiku-4-5, gpt-4o-mini)
    # x 2 cells x 1 rep. The old assertion (==2, "1 model") predates this
    # contract's actual models list and was never exercised because the
    # contract failed to load at all until Gate B's missing-SKILL.md fix.
    assert dry_outcomes["matrix_size"] == 6

    # Execute mock run
    outcomes = run_benchmark(contract_path, target_name, dry_run=False, alias="bauplan-lakehouse")
    assert outcomes["status"] == "complete"
    assert "runs_dir" in outcomes
    
    # Grade study
    adapter = load_adapter(target_name)
    results = grade_study(outcomes["runs_dir"], adapter)
    assert len(results) >= 2
    
    # Generate report — this run is mock mode (no live Bauplan call exists
    # yet), so it must be explicitly acknowledged or generate_report()
    # refuses (MockTraceError; see Gate C / specimen SBD-10).
    report = generate_report(results, allow_mock=True)
    assert "SIMULATED" in report  # the mock watermark must be present
    assert "Graded Traces" in report or "Report" in report or len(report) > 50
    print("\n--- Bauplan Benchmark Metrology Report ---")
    print(report)
