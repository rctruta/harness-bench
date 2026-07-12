from dataclasses import dataclass, field
from typing import Protocol, Optional, Callable, Dict, Any, List


@dataclass
class SpecialistRole:
    """Static definition of what a specialist does."""
    name: str
    tool_names: List[str]
    system_prompt: str
    max_turns: int = 20
    parse_output: Optional[Callable[[str, list], Optional[dict]]] = None
    tool_preconditions: Dict[str, tuple[str, str]] = field(default_factory=dict)


@dataclass
class TerminalPolicy:
    """How the target signals a run is completely finished."""
    poll_until_terminal: Callable[[str], dict]


class TargetAdapter(Protocol):
    """The contract every target implements. Hides target-specific domains from the generic engine."""
    
    @property
    def name(self) -> str:
        ...

    def healthcheck(self) -> None:
        """Verify the target is alive and ready. Raises an exception if not."""
        ...

    # --- SURFACE: what the agent can do ---
    def tools(self, neutral_descriptions: bool = False) -> List[dict]:
        """OpenAI/litellm tool schema."""
        ...

    def execute_tool(self, name: str, args: dict) -> str:
        """Dispatch one tool call against the live target. Returns the tool result as a string."""
        ...

    # --- ROLES: the state machine's specialists (optional) ---
    def roles(self) -> Dict[str, SpecialistRole]:
        """Named specialist roles for the multi-agent driver."""
        ...

    # --- TERMINAL: how the target signals 'done' (optional) ---
    def terminal_policy(self) -> Optional[TerminalPolicy]:
        """Async submit->poll targets provide one; synchronous targets return None."""
        ...

    # --- GRADER: ground-truth grading (optional) ---
    def grader(self) -> Optional[Callable[[dict], dict]]:
        """Given a run's trace, return a grade verdict against the
        target's ground truth. None where no ground truth exists (then
        the report carries process markers only)."""
        ...

    # --- MARKERS: target-specific behavioral signals (optional) ---
    def markers(self) -> Dict[str, Callable]:
        """Extra behavioral markers layered on the generic set."""
        ...
