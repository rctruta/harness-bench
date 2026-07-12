"""Fake TargetAdapter for testing the generic engine without a real backend."""
from typing import Dict, List, Optional, Callable

from harnessbench.adapter import TargetAdapter, SpecialistRole, TerminalPolicy


class FakeAdapter(TargetAdapter):
    name = "fake"

    def __init__(self):
        self.execute_log = []

    def tools(self, neutral_descriptions: bool = False) -> List[dict]:
        return [
            {"type": "function", "function": {"name": "fake_tool_1", "description": "", "parameters": {}}},
            {"type": "function", "function": {"name": "fake_tool_2", "description": "", "parameters": {}}}
        ]

    def execute_tool(self, name: str, args: dict) -> str:
        self.execute_log.append((name, args))
        if name == "boom":
            raise ValueError("explosive tool")
        return '{"ok": true}'

    def roles(self) -> Dict[str, SpecialistRole]:
        return {
            "librarian": SpecialistRole(
                name="librarian",
                tool_names=["fake_tool_1"],
                system_prompt="You are a librarian.",
                parse_output=lambda c, t: {"analysis": c} if "FINAL ANSWER" in c else ({"build": "need build"} if "HANDOFF" in c else None)
            ),
            "config_builder": SpecialistRole(
                name="config_builder",
                tool_names=["fake_tool_2"],
                system_prompt="You are a builder.",
                parse_output=lambda c, t: {"experiment_id": "1234"} if "HANDOFF" in c else None
            ),
            "analyzer": SpecialistRole(
                name="analyzer",
                tool_names=["fake_tool_1", "fake_tool_2"],
                system_prompt="You are an analyzer.",
                parse_output=lambda c, t: {"analysis": c} if "FINAL ANSWER" in c else None
            )
        }

    def terminal_policy(self) -> Optional[TerminalPolicy]:
        def fake_poll(exp_id: str, max_polls: int, interval_seconds: int):
            return {"status": "complete", "polls": 1}
        return TerminalPolicy(poll_until_terminal=fake_poll)

    def grader(self) -> Optional[Callable[[dict], dict]]:
        return lambda trace: {"grade": "PASS", "reason": "fake"}

    def markers(self) -> Dict[str, Callable]:
        return {"fake_marker": lambda trace: True}
