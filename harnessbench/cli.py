"""CLI for harness-bench."""
import argparse
import sys
import json
from harnessbench.api import check_environment, run_benchmark


def main():
    parser = argparse.ArgumentParser(description="Harness Bench: Agent Metrology Engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # `check` command
    parser_check = subparsers.add_parser("check", help="Pre-flight check for keys and target health")
    parser_check.add_argument("contract", help="Path to study YAML contract")
    parser_check.add_argument("--target", required=True, help="Target Adapter (e.g., sbd)")

    # `run` command
    parser_run = subparsers.add_parser("run", help="Run a benchmark matrix")
    parser_run.add_argument("contract", help="Path to study YAML contract")
    parser_run.add_argument("--target", required=True, help="Target Adapter (e.g., sbd)")
    parser_run.add_argument("--dry-run", action="store_true", help="Print matrix without executing")

    parser_grade = subparsers.add_parser("grade", help="Grade a completed study directory")
    parser_grade.add_argument("study_dir", help="Path to the directory containing agent traces")
    parser_grade.add_argument("--target", required=True, help="Target adapter (e.g. sbd or mcp:stdio:cmd)")

    parser_report = subparsers.add_parser("report", help="Generate a markdown report for a graded study")
    parser_report.add_argument("study_dir", help="Path to the directory containing agent traces")
    parser_report.add_argument("--target", required=True, help="Target adapter (e.g. sbd or mcp:stdio:cmd)")

    args = parser.parse_args()

    if args.command == "check":
        print(f"Checking environment for target: {args.target}")
        res = check_environment(args.contract, args.target)
        if res["status"] == "ok":
            print("✅ Environment is ready. Keys and Target are healthy.")
        else:
            print(f"❌ FATAL: {res['error']}")

    elif args.command == "run":
        print(f"Starting run for target: {args.target}")
        outcomes = run_benchmark(args.contract, args.target)
        print(f"Run complete. Outcomes: {outcomes}")

    elif args.command == "grade":
        from harnessbench.registry import load_adapter
        from harnessbench.grade import grade_study
        adapter = load_adapter(args.target)
        print(f"Grading study in {args.study_dir}")
        results = grade_study(args.study_dir, adapter)
        out_path = os.path.join(args.study_dir, "graded_traces.json")
        import json
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"Graded {len(results)} traces. Output saved to {out_path}")

    elif args.command == "report":
        from harnessbench.registry import load_adapter
        from harnessbench.grade import grade_study
        from harnessbench.report import generate_report
        adapter = load_adapter(args.target)
        results = grade_study(args.study_dir, adapter)
        report = generate_report(results)
        print("\n" + report)

if __name__ == "__main__":
    main()
