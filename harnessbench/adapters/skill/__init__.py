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
            
            # Sanitize path to be relative to cwd if not absolute
            if os.path.isabs(path):
                full_path = path
            else:
                full_path = os.path.join(cwd, path)
            
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                return f"Error reading file {path} (resolved to {full_path}): {str(e)}"
                
        # If somehow an unexpected tool gets through, delegate to inner
        return self.inner.execute_tool(name, args)

    def roles(self) -> Dict[str, SpecialistRole]:
        inner_roles = self.inner.roles()
        
        # Build the skill metadata list
        skill_dir = os.getenv("TARGET_SKILL_DIR")
        skill_metadata = []
        if skill_dir and os.path.isdir(skill_dir):
            for d in sorted(os.listdir(skill_dir)):
                full_d = os.path.join(skill_dir, d)
                skill_file = os.path.join(full_d, "SKILL.md")
                if os.path.isdir(full_d) and os.path.isfile(skill_file):
                    name = d
                    description = ""
                    with open(skill_file, "r") as f:
                        lines = f.readlines()
                        if lines and lines[0].strip() == "---":
                            for line in lines[1:]:
                                if line.strip() == "---":
                                    break
                                if line.startswith("name:"):
                                    name = line.split(":", 1)[1].strip()
                                elif line.startswith("description:"):
                                    description = line.split(":", 1)[1].strip()
                    
                    skill_metadata.append(f"- **{name}**: {description}\n  Path: `{skill_file}`")

        skills_intro = (
            "ENVIRONMENT NOTE: You are running in a 'Skills-with-Scripts' architecture.\n"
            "You have been provided with bash and file reading tools instead of direct JSON APIs.\n"
            "Your instructions and necessary python scripts are located in the local directory.\n"
            "Here are the available skills and their absolute paths:\n\n"
            + "\n\n".join(skill_metadata) + "\n\n"
            "You MUST use `read_file` on the absolute path of the relevant skill to learn the exact bash commands to run.\n"
            "Ignore any JSON tool names mentioned in your workflow below; you must read and execute the actual scripts.\n\n"
        )
        
        for role in inner_roles.values():
            role.tool_names = {"run_command", "read_file"}
            role.system_prompt = skills_intro + role.system_prompt
        return inner_roles

    def terminal_policy(self) -> Optional[TerminalPolicy]:
        return self.inner.terminal_policy()

    def grader(self) -> Optional[Callable[[dict], dict]]:
        return self.inner.grader()

    def markers(self) -> Dict[str, Callable]:
        return self.inner.markers()
