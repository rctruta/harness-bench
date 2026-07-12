"""The SBD Reference Adapter."""

from typing import Dict, List, Optional, Callable

from harnessbench.adapter import TargetAdapter, SpecialistRole, TerminalPolicy
from harnessbench.adapters.sbd.roles import CONFIG_BUILDER, ANALYZER, LIBRARIAN
from harnessbench.adapters.sbd.terminal import poll_until_terminal, healthcheck
from harnessbench.adapters.sbd.tools import get_tools, dispatch_tool


class SbdAdapter(TargetAdapter):
    """Bridges the generic harness to the SBD testbed."""

    @property
    def name(self) -> str:
        return "sbd"

    def healthcheck(self) -> None:
        healthcheck()

    def tools(self, neutral_descriptions: bool = False) -> List[dict]:
        return get_tools()

    def execute_tool(self, name: str, args: dict) -> str:
        return dispatch_tool(name, args)

    def roles(self) -> Dict[str, SpecialistRole]:
        return {
            "config_builder": CONFIG_BUILDER,
            "analyzer": ANALYZER,
            "librarian": LIBRARIAN,
        }

    def terminal_policy(self) -> Optional[TerminalPolicy]:
        return TerminalPolicy(poll_until_terminal=poll_until_terminal)

    def grader(self) -> Optional[Callable[[dict], dict]]:
        from harnessbench.adapters.sbd.grader import sbd_grader
        return sbd_grader

    def markers(self) -> Dict[str, Callable]:
        # SBD-specific behavioral markers
        def _extract(path: str):
            import json
            seen_get_template = False
            seen_submit = False
            cat_filtered = False
            unfiltered = False
            tmpl_first = None
            projs = []
            raw_used = False
            
            with open(path, 'r') as f:
                for line in f:
                    e = json.loads(line)
                    if e.get("event") == "tool_call":
                        name = e.get("name")
                        args = e.get("arguments") or {}
                        if name == "list_suites":
                            if isinstance(args, dict) and args.get("category"):
                                cat_filtered = True
                            else:
                                unfiltered = True
                        elif name == "get_template":
                            seen_get_template = True
                        elif name == "submit_experiment":
                            if not seen_submit:
                                tmpl_first = seen_get_template
                            seen_submit = True
                        elif name in {"get_experiment_summary", "get_means_by_partition", "get_scaling_factor", "get_replication_stability"}:
                            projs.append(name)
                        elif name == "get_experiment_result":
                            raw_used = True
                            
            return {
                "category_filtered": cat_filtered,
                "unfiltered_suites": unfiltered,
                "template_first": tmpl_first,
                "projections_used": list(set(projs)),
                "raw_result_used": raw_used
            }
            
        return {"sbd_markers": _extract}
