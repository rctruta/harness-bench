"""Structured JSONL logging for agent runs.

Every meaningful event during a run is emitted as one JSON line.
"""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional, Dict


def slugify(text: str) -> str:
    """Return a file-safe lowercased slug of model names."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:30]


def _new_run_id(goal: str) -> str:
    """`<UTC-ISO-compact>_<goal-hash-8>` — sortable + identifiable."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    goal_h = hashlib.sha256(goal.encode("utf-8")).hexdigest()[:8]
    return f"{ts}_{goal_h}"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_tool_calls(tool_calls) -> list:
    out = []
    for tc in tool_calls or []:
        if hasattr(tc, "function"):
            name = tc.function.name
            args = tc.function.arguments
        elif isinstance(tc, dict):
            fn = tc.get("function") or {}
            name = fn.get("name") or tc.get("name")
            args = fn.get("arguments") or tc.get("arguments")
        else:
            name, args = None, None
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                pass
        out.append({"name": name, "arguments": args})
    return out


def _usage_from_response(response) -> Optional[Dict]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if isinstance(usage, dict):
        return usage
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


class AgentTrace:
    """One agent run = one JSONL file. Each method emits one event line."""

    _standalone_dirs: dict = {}
    _used_run_ids: set = set()

    def __init__(self, goal: str, model: str, agents_md_loaded: bool, max_turns: int, role: Optional[str] = None, runs_dir: str = "./agent_runs"):
        study_dir = os.getenv("AGENT_STUDY_DIR")
        trace_prefix = os.getenv("AGENT_TRACE_PREFIX")

        if not (study_dir and trace_prefix):
            key = runs_dir
            if key not in AgentTrace._standalone_dirs:
                AgentTrace._standalone_dirs[key] = os.path.join(
                    runs_dir,
                    f"standalone_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}")
            study_dir = AgentTrace._standalone_dirs[key]
            trace_prefix = f"trace_{slugify(model)}"

        role_suffix = f"_{role}" if role else ""
        run_id = f"{trace_prefix}{role_suffix}"
        
        candidate, n = run_id, 1
        while candidate in AgentTrace._used_run_ids or os.path.exists(os.path.join(study_dir, f"{candidate}.jsonl")):
            n += 1
            candidate = f"{run_id}_{n}"
        self.run_id = candidate
        AgentTrace._used_run_ids.add(self.run_id)

        os.makedirs(study_dir, exist_ok=True)
        self.path = os.path.join(study_dir, f"{self.run_id}.jsonl")
        self._emit("run_start", {
            "goal": goal,
            "model": model,
            "agents_md_loaded": agents_md_loaded,
            "max_turns": max_turns,
        })

    def _emit(self, event: str, data: dict) -> None:
        record = {"ts": _iso_now(), "run_id": self.run_id, "event": event, **data}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def turn_start(self, turn: int) -> None:
        self._emit("turn_start", {"turn": turn})

    def model_response(self, turn: int, content: str, tool_calls,
                       response=None, recovered_call_reason: Optional[str] = None) -> None:
        self._emit("model_response", {
            "turn": turn,
            "content": content or "",
            "content_len": len(content or ""),
            "tool_calls": _normalize_tool_calls(tool_calls),
            "empty_content": not (content or "").strip(),
            "recovered_call_reason": recovered_call_reason,
            "usage": _usage_from_response(response) if response is not None else None,
        })

    def tool_call(self, turn: int, tool_call_id: str, name: str, arguments: Any) -> None:
        self._emit("tool_call", {
            "turn": turn,
            "tool_call_id": tool_call_id,
            "name": name,
            "arguments": arguments,
        })

    def tool_result(self, turn: int, tool_call_id: str, name: str,
                    result: str, error_reason: Optional[str] = None) -> None:
        self._emit("tool_result", {
            "turn": turn,
            "tool_call_id": tool_call_id,
            "name": name,
            "result": result or "",
            "result_len": len(result or ""),
            "error_reason": error_reason,
        })

    def nudge(self, turn: int, reason: str, attempt: int, max_attempts: int) -> None:
        self._emit("nudge", {
            "turn": turn,
            "reason": reason,
            "attempt": attempt,
            "max_attempts": max_attempts,
        })

    def final_answer(self, turn: int, content: str) -> None:
        self._emit("final_answer", {"turn": turn, "content": content or ""})

    def run_end(self, outcome: str, turns_used: int, error: Optional[str] = None) -> None:
        self._emit("run_end", {
            "outcome": outcome,
            "turns_used": turns_used,
            "error": error,
        })

    def prompt_provenance(self, components: dict, ablation_flags: Optional[dict] = None) -> None:
        hashed = {}
        for name, content in components.items():
            if content is None:
                hashed[name] = None
            else:
                data = content if isinstance(content, str) else json.dumps(content, sort_keys=True)
                hashed[name] = {
                    "sha256": hashlib.sha256(data.encode("utf-8")).hexdigest(),
                    "bytes": len(data.encode("utf-8")),
                }
        self._emit("prompt_provenance", {
            "components": hashed,
            "ablation_flags": ablation_flags or {},
        })

    def delegate(self, stage: str, sub_run_id: Optional[str],
                 input_summary: str, outcome: str,
                 output_summary: Optional[str] = None) -> None:
        self._emit("delegate", {
            "stage": stage,
            "sub_run_id": sub_run_id,
            "input_summary": input_summary,
            "outcome": outcome,
            "output_summary": output_summary,
        })
