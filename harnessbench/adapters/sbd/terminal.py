"""SBD terminal polling policy."""
import time

# We import the live client directly from SBD. The adapter is the bridge.
import sys
import os
_SBD_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_SBD_SRC = os.path.join(_SBD_ROOT, "../sql-benchmarks-dagster")
if _SBD_SRC not in sys.path:
    sys.path.insert(0, _SBD_SRC)

from sql_benchmarks.agent_tools import _get_client


def poll_until_terminal(experiment_id: str, max_polls: int = 60, interval_seconds: float = 3.0) -> dict:
    """Poll SBD FastAPI `/status` until complete or failed."""
    client = _get_client()
    for i in range(1, max_polls + 1):
        try:
            r = client.get(f"/v1/experiments/{experiment_id}/status", timeout=30)
            body = r.json()
            status = body.get("status", "unknown")
        except Exception as e:
            return {"status": "poll_error", "polls": i, "error": str(e)}
        if status in ("complete", "failed"):
            return {"status": status, "polls": i, "detail": body.get("detail")}
        time.sleep(interval_seconds)
    return {"status": "timeout", "polls": max_polls}

def healthcheck() -> None:
    """Check if the SBD FastAPI backend is running."""
    try:
        client = _get_client()
        r = client.get("/", timeout=5.0)
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"SBD backend is not reachable. Is it running? Error: {e}")
