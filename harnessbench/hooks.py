"""Pre-tool-call gates ("hooks") — the mechanical layer of the placement ladder.

A hook inspects a pending tool call and either allows it (returns None) or
refuses it (returns a message the model sees as the tool result). Refusals
cost zero backend execution and are traced as gate refusals, which makes
gates an ablatable variable: contract cells declare them under
`flags.hooks`, same as skills injection.

Declarative form (contract YAML):

    cells:
      gated:
        flags:
          hooks:
            - require_before: {tool: submit_experiment, requires: get_template}
            - max_calls: {tool: list_suites, limit: 2}
"""
from dataclasses import dataclass, field
from typing import Callable, List, Optional


@dataclass
class HookState:
    """Per-run state shared by all hooks."""
    succeeded: set = field(default_factory=set)
    call_counts: dict = field(default_factory=dict)

    def record_success(self, tool: str) -> None:
        self.succeeded.add(tool)

    def record_call(self, tool: str) -> None:
        self.call_counts[tool] = self.call_counts.get(tool, 0) + 1


def _require_before(spec: dict) -> Callable:
    tool, requires = spec["tool"], spec["requires"]

    def hook(name: str, args: dict, state: HookState) -> Optional[str]:
        if name == tool and requires not in state.succeeded:
            return (f"REFUSED by gate require_before: call {requires} "
                    f"successfully before {tool}.")
        return None
    return hook


def _max_calls(spec: dict) -> Callable:
    tool, limit = spec["tool"], int(spec["limit"])

    def hook(name: str, args: dict, state: HookState) -> Optional[str]:
        if name == tool and state.call_counts.get(tool, 0) >= limit:
            return (f"REFUSED by gate max_calls: {tool} already called "
                    f"{limit} time(s); use the results you have.")
        return None
    return hook


BUILTIN = {"require_before": _require_before, "max_calls": _max_calls}


def build_hooks(specs: List[dict]) -> List[Callable]:
    """Compile contract-declared hook specs into callables."""
    hooks = []
    for spec in specs or []:
        if len(spec) != 1:
            raise ValueError(f"hook spec must have exactly one key: {spec}")
        kind, params = next(iter(spec.items()))
        if kind not in BUILTIN:
            raise ValueError(f"unknown hook kind '{kind}' (have: {sorted(BUILTIN)})")
        hooks.append(BUILTIN[kind](params))
    return hooks
