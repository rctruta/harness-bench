"""One reusable specialist loop.

A specialist is a scoped LLM agent: given a `role` (name + tool subset +
system prompt) and an `input` (natural-language brief), it runs a bounded
tool-use loop and returns a structured `SpecialistResult`.
"""
from dataclasses import dataclass
import json
from typing import Optional

from litellm import completion

from harnessbench.adapter import TargetAdapter, SpecialistRole
from harnessbench.trace import AgentTrace


MAX_EMPTY_RESPONSES = 3


@dataclass
class SpecialistResult:
    role: str
    outcome: str  # "ok" | "gave_up" | "max_turns" | "exception"
    output: Optional[dict]
    sub_run_id: Optional[str]  # the specialist's own AgentTrace run_id
    turns_used: int
    error: Optional[str] = None


def _parse_tool_arguments(raw) -> dict:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw or {}


class _RecoveredCall:
    _counter = 0

    def __init__(self, name: str, args: dict):
        _RecoveredCall._counter += 1
        self.id = f"recovered_{_RecoveredCall._counter}"

        class _Fn:
            pass
        self.function = _Fn()
        self.function.name = name
        self.function.arguments = json.dumps(args)

    def model_dump(self):
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.function.name, "arguments": self.function.arguments},
        }


_NAME_KEYS = ("name", "function_name", "tool", "tool_name")


def try_recover_tool_call_from_text(text: str, allowed_tools: set):
    if not text:
        return None, None
    raw = text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 2:
            block = parts[1]
            if block.startswith("json\n"):
                block = block[len("json\n"):]
            raw = block.strip()
    if not (raw.startswith("{") and raw.endswith("}")):
        return None, None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(parsed, dict):
        return None, None

    name = None
    for key in _NAME_KEYS:
        if isinstance(parsed.get(key), str):
            name = parsed[key]
            break
    if name is None and isinstance(parsed.get("function"), dict):
        name = parsed["function"].get("name")
    if not name:
        return None, None

    args = parsed.get("arguments") or parsed.get("function", {}).get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    if not isinstance(args, dict):
        args = {}

    if name not in allowed_tools:
        return None, f"model called unknown tool '{name}' (allowed: {sorted(allowed_tools)})"
    return _RecoveredCall(name, args), None


def _extract_error(result_str: str) -> Optional[str]:
    try:
        data = json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(data, dict):
        if data.get("error"):
            return str(data["error"])
        if data.get("detail") and not data.get("experiment_id"):
            return str(data["detail"])
    return None


def run_specialist(adapter: TargetAdapter, role: SpecialistRole, brief: str, model: str, runs_dir: str = "./agent_runs") -> SpecialistResult:
    """Run one specialist to completion. Returns a structured result."""
    # Filter tools from adapter based on role.tool_names
    tools = [t for t in adapter.tools() if t["function"]["name"] in role.tool_names]
    
    trace = AgentTrace(
        goal=f"[specialist:{role.name}] {brief}",
        model=model,
        agents_md_loaded=False,
        max_turns=role.max_turns,
        role=role.name,
        runs_dir=runs_dir
    )

    trace.prompt_provenance(
        components={
            "agents_md": None,
            "skills": None,
            "role_prompt": role.system_prompt,
            "tools_schema": tools,
            "brief": brief,
        },
        ablation_flags={"architecture": "specialist", "role": role.name},
    )

    messages = [
        {"role": "system", "content": role.system_prompt},
        {"role": "user", "content": brief},
    ]
    empty_in_a_row = 0
    last_content = ""
    failing_call_counts: dict = {}  
    succeeded_tools: set = set()  

    for turn in range(1, role.max_turns + 1):
        trace.turn_start(turn)
        try:
            response = completion(model=model, messages=messages, tools=tools, tool_choice="auto")
        except Exception as e:
            trace.run_end("exception", turn, error=str(e))
            return SpecialistResult(
                role=role.name, outcome="exception", output=None,
                sub_run_id=trace.run_id, turns_used=turn, error=str(e),
            )

        msg = response.choices[0].message
        content = msg.content or ""
        tool_calls = msg.tool_calls or []
        last_content = content

        recovery_reason = None
        if not tool_calls:
            recovered, recovery_reason = try_recover_tool_call_from_text(
                content, allowed_tools={t["function"]["name"] for t in tools})
            if recovered is not None:
                tool_calls = [recovered]

        trace.model_response(turn=turn, content=content, tool_calls=tool_calls,
                             response=response, recovered_call_reason=recovery_reason)

        if tool_calls:
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [t.model_dump() for t in tool_calls],
            })
        else:
            messages.append({"role": "assistant", "content": content})

        if role.parse_output is not None:
            parsed = role.parse_output(content, tool_calls)
            if parsed is not None:
                trace.final_answer(turn=turn, content=content)
                trace.run_end("final_answer", turn)
                return SpecialistResult(
                    role=role.name, outcome="ok", output=parsed,
                    sub_run_id=trace.run_id, turns_used=turn,
                )

        if not tool_calls:
            empty_in_a_row += 1
            if empty_in_a_row >= MAX_EMPTY_RESPONSES:
                trace.run_end("gave_up", turn)
                return SpecialistResult(
                    role=role.name, outcome="gave_up", output=None,
                    sub_run_id=trace.run_id, turns_used=turn,
                    error=f"specialist produced {empty_in_a_row} non-actionable responses in a row",
                )
            trace.nudge(turn=turn, reason="no_tool_call", attempt=empty_in_a_row,
                        max_attempts=MAX_EMPTY_RESPONSES)
            if recovery_reason:
                nudge_msg = (
                    f"Your message tried to call a tool that does not exist ({recovery_reason}). "
                    "Retry with one of your registered tools, as a NATIVE tool call "
                    "(not JSON text)."
                )
            else:
                nudge_msg = (
                    "You didn't call a tool. If you're done, produce your structured "
                    "output as instructed in the system prompt. Otherwise call the next tool."
                )
            messages.append({"role": "user", "content": nudge_msg})
            continue

        empty_in_a_row = 0
        pending_coaching = []
        for tc in tool_calls:
            args = _parse_tool_arguments(tc.function.arguments)
            trace.tool_call(turn=turn, tool_call_id=tc.id, name=tc.function.name, arguments=args)

            precondition = role.tool_preconditions.get(tc.function.name)
            if precondition:
                required_tool, gate_message = precondition
                if required_tool not in succeeded_tools:
                    result_str = json.dumps({"error": gate_message})
                    trace.tool_result(turn=turn, tool_call_id=tc.id, name=tc.function.name,
                                      result=result_str, error_reason=gate_message)
                    messages.append({
                        "role": "tool", "tool_call_id": tc.id,
                        "name": tc.function.name, "content": result_str,
                    })
                    pending_coaching.append(gate_message)
                    continue

            result_str = adapter.execute_tool(tc.function.name, args)
            error_reason = _extract_error(result_str)
            if not error_reason:
                succeeded_tools.add(tc.function.name)
            trace.tool_result(turn=turn, tool_call_id=tc.id, name=tc.function.name,
                              result=result_str, error_reason=error_reason)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tc.function.name,
                "content": result_str,
            })

            if error_reason:
                call_sig = f"{tc.function.name}:{json.dumps(args, sort_keys=True, default=str)}"
                repeat_count = failing_call_counts.get(call_sig, 0) + 1
                failing_call_counts[call_sig] = repeat_count
                if repeat_count >= 2:
                    trace.nudge(turn=turn, reason="repeated_failing_call",
                                attempt=repeat_count, max_attempts=0)
                    coaching = (
                        f"STOP. You have now made this exact call {repeat_count} times and it "
                        f"failed identically every time: `{tc.function.name}` with the same "
                        f"arguments. Repeating it again will produce the same error. "
                        f"Read the error: {error_reason}\n"
                        f"Your available tools are: {sorted(t['function']['name'] for t in tools)}. "
                        "Change your approach: pick a DIFFERENT tool or DIFFERENT arguments."
                    )
                else:
                    coaching = (
                        f"The `{tc.function.name}` call returned an error: {error_reason}\n"
                        f"Your available tools are: {sorted(t['function']['name'] for t in tools)}. "
                        "Fix the specific problem named in the error and retry."
                    )
                pending_coaching.append(coaching)

        if pending_coaching:
            messages.append({"role": "user", "content": "\n\n".join(pending_coaching)})

    trace.run_end("max_turns", role.max_turns)
    return SpecialistResult(
        role=role.name, outcome="max_turns", output=None,
        sub_run_id=trace.run_id, turns_used=role.max_turns,
        error=f"reached max_turns={role.max_turns} without a parseable final output",
    )
