"""Structured JSONL logging for agent runs.

Every meaningful event during a run is emitted as one JSON line.
"""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional, Dict

from harnessbench.trace_utils import slugify


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


def _response_metadata(response) -> Dict:
    """Provider metadata beyond token counts.

    Token counts alone answer "how big was this call" but not "what actually
    ran, did it finish, and what did it cost". Each field below closes a gap
    that showed up while analysing the existing corpus:

      model_served      The model that ANSWERED, which is not the model you
                        asked for. Request 'gpt-4o' and OpenAI serves
                        'gpt-4o-2024-08-06'. Without this, a corpus spanning
                        months silently mixes model snapshots under one label
                        and every cross-model comparison is suspect.
      finish_reason     'length' means the response was TRUNCATED — a silent
                        failure that looks like a short answer. Currently
                        indistinguishable from a model that simply stopped.
      response_cost     Actual dollars, computed by litellm from its pricing
                        table. The corpus can currently only say "tokens",
                        which is not comparable across vendors — a cost claim
                        needs this or it is a token claim wearing a suit.
      cached_tokens     Cache hits change cost by an order of magnitude and
                        make two identical-token runs cost differently.
      system_fingerprint  Provider backend config version. Two runs with the
                        same model and different fingerprints are not the
                        same experiment.
      provider / request_id  Routing and support forensics.

    Every field is optional and best-effort: providers differ in what they
    return, and a missing field must read as absent rather than zero.
    """
    meta: Dict = {}

    for attr, key in (("model", "model_served"),
                      ("id", "request_id"),
                      ("created", "created_at_epoch"),
                      ("system_fingerprint", "system_fingerprint")):
        val = getattr(response, attr, None)
        if val is not None:
            meta[key] = val

    choices = getattr(response, "choices", None) or []
    if choices:
        fr = getattr(choices[0], "finish_reason", None)
        if fr is not None:
            meta["finish_reason"] = fr
            # Called out explicitly because a truncated answer is a real
            # failure that otherwise reads as a terse one.
            meta["was_truncated"] = (fr == "length")

    usage = getattr(response, "usage", None)
    if usage is not None:
        details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", None) if details else None
        if cached is not None:
            meta["cached_prompt_tokens"] = cached
        reasoning = getattr(getattr(usage, "completion_tokens_details", None),
                            "reasoning_tokens", None)
        if reasoning is not None:
            meta["reasoning_tokens"] = reasoning

    hidden = getattr(response, "_hidden_params", None) or {}
    if isinstance(hidden, dict):
        for k in ("custom_llm_provider", "region_name", "response_cost"):
            if hidden.get(k) is not None:
                meta[k] = hidden[k]

    # litellm computes cost from its pricing table when the provider did not
    # return one. Wrapped: an unknown model raises, and a missing cost must
    # never break a run that already produced an answer.
    if "response_cost" not in meta:
        try:
            import litellm
            cost = litellm.completion_cost(completion_response=response)
            if cost is not None:
                meta["response_cost"] = cost
        except Exception:
            pass

    return meta


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
            # Provider metadata: which model actually served, whether the
            # response was truncated, real cost, cache hits. See
            # _response_metadata for why each one is here.
            "response_meta": _response_metadata(response) if response is not None else None,
        })

    def tool_call(self, turn: int, tool_call_id: str, name: str, arguments: Any) -> None:
        self._emit("tool_call", {
            "turn": turn,
            "tool_call_id": tool_call_id,
            "name": name,
            "arguments": arguments,
        })

    def tool_result(self, turn: int, tool_call_id: str, name: str,
                    result: str, error_reason: Optional[str] = None,
                    mode: Optional[str] = None) -> None:
        self._emit("tool_result", {
            "turn": turn,
            "tool_call_id": tool_call_id,
            "name": name,
            "result": result or "",
            "result_len": len(result or ""),
            "error_reason": error_reason,
            # Stamped by the ENGINE from adapter.mode, not self-reported by the
            # agent — this is what makes "was this run real or simulated"
            # mechanically checkable instead of a claim in a report.
            "mode": mode,
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
