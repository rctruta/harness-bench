"""Dynamic registry for loading TargetAdapters."""
from harnessbench.adapter import TargetAdapter


def load_adapter(name: str) -> TargetAdapter:
    """Dynamically loads the requested adapter by name."""
    if name == "sbd":
        # We lazily import so the generic engine doesn't blow up if SBD isn't installed
        from harnessbench.adapters.sbd import SbdAdapter
        return SbdAdapter()

    if name == "fake":
        from harnessbench.tests.fake_adapter import FakeAdapter
        return FakeAdapter()

    if name in ("bauplan", "bauplan_lakehouse"):
        # Mock by default — existing tests depend on this. Real experiments
        # MUST use 'bauplan_lakehouse_real' explicitly + contract
        # 'expect_mode: real', so check_environment() (api.py) can catch a
        # mismatch before any spend. See specimen SBD-12: this default
        # silently produced a fabricated-data study before that gate existed.
        from harnessbench.adapters.bauplan import BauplanAdapter
        return BauplanAdapter()

    if name == "bauplan_lakehouse_real":
        from harnessbench.adapters.bauplan import BauplanAdapter
        return BauplanAdapter(mock_mode=False)

    if name == "bauplan_mcp_mirror":
        from harnessbench.adapters.bauplan_mcp_mirror import BauplanMcpMirrorAdapter
        return BauplanMcpMirrorAdapter()

    if name.startswith("skill:"):
        inner_name = name[len("skill:"):]
        inner = load_adapter(inner_name)
        from harnessbench.adapters.skill import SkillAdapter
        return SkillAdapter(inner)

    if name == "mcp:http:bauplan":
        # Bauplan's real, production MCP server (docs.bauplanlabs.com/agents/mcp).
        # Key stays out of the target-name string (which becomes a runs/ folder
        # name via get_target_slug) — read from .env like BauplanAdapter does.
        import os
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.environ.get("BAUPLAN_API_KEY")
        if not api_key:
            raise RuntimeError("BAUPLAN_API_KEY not set in environment/.env")
        from harnessbench.adapters.mcp import McpAdapter
        return McpAdapter(
            url="https://mcp.use1.aprod.bauplanlabs.com/mcp",
            headers={"Authorization": f"Bearer {api_key}"},
        )

    if name.startswith("mcp:http:"):
        # e.g., mcp:http:http://localhost:4040/mcp
        url = name[len("mcp:http:"):]
        from harnessbench.adapters.mcp import McpAdapter
        return McpAdapter(url=url)

    if name.startswith("mcp:stdio:"):
        # e.g., mcp:stdio:uvx mcp-server-motherduck
        cmd_str = name[len("mcp:stdio:"):]
        import shlex
        command = shlex.split(cmd_str)
        from harnessbench.adapters.mcp import McpAdapter
        return McpAdapter(command)

    raise ValueError(f"Unknown TargetAdapter: '{name}'")
