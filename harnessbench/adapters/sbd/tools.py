"""SBD tools wrapper."""

import sys
import os
_SBD_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_SBD_SRC = os.path.join(_SBD_ROOT, "../sql-benchmarks-dagster")
if _SBD_SRC not in sys.path:
    sys.path.insert(0, _SBD_SRC)

from sql_benchmarks.agent_tools import TOOLS, execute_tool

def get_tools() -> list:
    """Return the litellm-compatible list of tool schemas."""
    return TOOLS

def dispatch_tool(name: str, args: dict) -> str:
    """Execute the tool against the live SBD backend."""
    return execute_tool(name, args)
