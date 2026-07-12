"""MCP Server for Harness Bench.

This exposes the exact same core API functions to autonomous agents
that the CLI exposes to human engineers.
"""
from mcp.server.fastmcp import FastMCP
from harnessbench.api import check_environment, run_benchmark

mcp = FastMCP("harness-bench")


@mcp.tool()
def check_harness_environment(contract_path: str, target_name: str) -> dict:
    """Pre-flight check: validates API keys and target health.
    
    Agents MUST run this tool before attempting to execute a benchmark matrix.
    If it returns an error, the agent MUST resolve the missing keys or 
    start the target backend before proceeding.
    """
    return check_environment(contract_path, target_name)


@mcp.tool()
def run_harness_benchmark(contract_path: str, target_name: str, dry_run: bool = False) -> dict:
    """Runs a study contract against a specific target.
    
    This executes the matrix (cells x replications) defined in the contract.
    If dry_run is True, it returns the matrix size without burning tokens.
    """
    try:
        return run_benchmark(contract_path, target_name, dry_run)
    except Exception as e:
        return {"status": "fatal_error", "message": str(e)}


if __name__ == "__main__":
    mcp.run()
