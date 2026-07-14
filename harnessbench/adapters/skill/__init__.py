"""The generic Skill Adapter Wrapper.

Wraps any TargetAdapter to strip its MCP tools and replace them with
local `run_command` and `read_file` tools, forcing the agent to rely on
prose skills and executable scripts instead of JSON-RPC schemas.
"""
import os
import subprocess
from typing import Dict, List, Optional, Callable

from harnessbench.adapter import TargetAdapter, SpecialistRole, TerminalPolicy


class SkillAdapter(TargetAdapter):
    """Wraps an inner TargetAdapter to test the 'skills-with-scripts' architecture."""

    def __init__(self, inner: TargetAdapter):
        self.inner = inner

    @property
    def name(self) -> str:
        return f"skill:{self.inner.name}"

    def healthcheck(self) -> None:
        """Verify the skill directory exists and run the inner healthcheck."""
        skill_dir = os.getenv("TARGET_SKILL_DIR")
        if not skill_dir:
            raise ValueError("TARGET_SKILL_DIR environment variable must be set for SkillAdapter")
        if not os.path.isdir(skill_dir):
            raise ValueError(f"Skill directory not found at TARGET_SKILL_DIR: {skill_dir}")
        self.inner.healthcheck()

    def tools(self, neutral_descriptions: bool = False) -> List[dict]:
        """Provide bash and read_file tools instead of the inner adapter's tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "run_command",
                    "description": "Run a shell command on the local filesystem. Use this to execute scripts provided in the skill directory.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "The exact shell command to execute."
                            }
                        },
                        "required": ["command"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file from the local filesystem. Use this to read SKILL.md or other text files.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Absolute path to the file."
                            }
                        },
                        "required": ["path"]
                    }
                }
            }
        ]

    def execute_tool(self, name: str, args: dict) -> str:
        """Execute the bash or read_file tools."""
        cwd = os.getenv("TARGET_SKILL_DIR")
        
        if name == "run_command":
            cmd = args.get("command")
            if not cmd:
                return "Error: missing 'command' argument."
            try:
                # Run the command securely in the skill directory
                result = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                output = result.stdout
                if result.stderr:
                    output += f"\nSTDERR:\n{result.stderr}"
                return output if output else "Command executed successfully with no output."
            except Exception as e:
                return f"Error executing command: {str(e)}"
                
        elif name == "read_file":
            path = args.get("path")
            if not path:
                return "Error: missing 'path' argument."
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                return f"Error reading file {path}: {str(e)}"
                
        # If somehow an unexpected tool gets through, delegate to inner
        return self.inner.execute_tool(name, args)

    def roles(self) -> Dict[str, SpecialistRole]:
        return self.inner.roles()

    def terminal_policy(self) -> Optional[TerminalPolicy]:
        return self.inner.terminal_policy()

    def grader(self) -> Optional[Callable[[dict], dict]]:
        return self.inner.grader()

    def markers(self) -> Dict[str, Callable]:
        return self.inner.markers()
