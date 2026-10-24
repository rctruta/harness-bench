"""SBD specialist roles and output parsers."""
import re
from typing import Optional

from harnessbench.adapter import SpecialistRole
from harnessbench.adapters.sbd.constants import CONFIG_BUILDER_PROMPT, ANALYZER_PROMPT, LIBRARIAN_PROMPT


_HANDOFF_RE = re.compile(r"HANDOFF:\s*experiment_id=([0-9a-f]{8})", re.IGNORECASE)
_REFUSAL_RE = re.compile(r"HANDOFF:\s*impossible\s+reason=(.+)", re.IGNORECASE)
_BUILD_RE = re.compile(r"HANDOFF:\s*build\s+reason=(.+)", re.IGNORECASE)


def _parse_handoff(content: str) -> Optional[dict]:
    m = _HANDOFF_RE.search(content or "")
    if m:
        return {"experiment_id": m.group(1)}
    r = _REFUSAL_RE.search(content or "")
    if r:
        return {"impossible": r.group(1).strip()}
    return None


def _parse_analyzer_final(content: str) -> Optional[dict]:
    if not content:
        return None
    if "final answer" in content.lower() and len(content.strip()) > 100:
        return {"analysis": content}
    return None


def _parse_librarian(content: str) -> Optional[dict]:
    if not content:
        return None
    b = _BUILD_RE.search(content)
    if b:
        return {"build": b.group(1).strip()}
    r = _REFUSAL_RE.search(content)
    if r:
        return {"impossible": r.group(1).strip()}
    if "final answer" in content.lower() and len(content.strip()) > 100:
        return {"analysis": content}
    return None


CONFIG_BUILDER = SpecialistRole(
    name="config_builder",
    tool_names=[
        "list_categories", "list_suites", "search_published_capsules",
        "list_templates", "get_template", "submit_experiment",
    ],
    system_prompt=CONFIG_BUILDER_PROMPT,
    max_turns=15,
    parse_output=lambda content, tool_calls: _parse_handoff(content),
    tool_preconditions={
        "submit_experiment": (
            "get_template",
            "REFUSED: you must call `get_template` and adapt a working template "
            "before submitting. Hand-written configs are rejected by this workflow "
            "— fetch `quickstart` (DuckDB-only) or another template from "
            "`list_templates` first.",
        ),
    },
)

ANALYZER = SpecialistRole(
    name="analyzer",
    tool_names=[
        "analyze_experiment", "get_means_by_benchmark"
    ],
    system_prompt=ANALYZER_PROMPT,
    max_turns=15,
    parse_output=lambda content, tool_calls: _parse_analyzer_final(content),
)

LIBRARIAN = SpecialistRole(
    name="librarian",
    tool_names=[
        "search_published_capsules", "list_lab_docs", "get_lab_doc",
        "list_categories", "analyze_experiment", "get_means_by_benchmark"
    ],
    system_prompt=LIBRARIAN_PROMPT,
    max_turns=12,
    parse_output=lambda content, tool_calls: _parse_librarian(content),
)
