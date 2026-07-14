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
        
    if name.startswith("skill:"):
        inner_name = name[len("skill:"):]
        inner = load_adapter(inner_name)
        from harnessbench.adapters.skill import SkillAdapter
        return SkillAdapter(inner)
        
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
