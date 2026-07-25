"""Monolith driver for executing a benchmark against an un-partitioned target.

This driver is the baseline (Phase A). It crams all available tools into a
single context window and loops until a final answer is produced.
"""
from dataclasses import dataclass
from typing import Optional
import json
import litellm

from harnessbench.adapter import TargetAdapter
from harnessbench.hooks import HookState
from harnessbench.trace import AgentTrace


@dataclass
class MonolithResult:
    outcome: str
    analysis: Optional[str]
    run_id: str
    error: Optional[str] = None


class MonolithDriver:
    """A generic, unspecialized agent loop."""
    
    def __init__(self, adapter: TargetAdapter, goal: str, model: str,
                 runs_dir: str = "./agent_runs", system_preamble: Optional[str] = None,
                 hooks: Optional[list] = None, max_turns: int = 20):
        self.adapter = adapter
        self.goal = goal
        self.model = model
        self.system_preamble = system_preamble
        self.hooks = hooks or []
        self.hook_state = HookState()
        self.max_turns = max_turns  # was hardcoded in both __init__ and the
        # loop condition below — 2026-07-24, needed to test whether more
        # turns changes small-model outcomes on the Bauplan task.
        self.trace = AgentTrace(
            goal=f"[monolith] {goal}", model=model,
            agents_md_loaded=False, max_turns=max_turns,
            runs_dir=runs_dir
        )
        
    def run(self) -> MonolithResult:
        messages = []
        if self.system_preamble:
            # Anthropic-only explicit prompt caching (2026-07-24): a static,
            # repeated system prompt is exactly what cache_control is for —
            # marks this block as a cache breakpoint so subsequent turns in
            # the SAME conversation reuse it at a steep discount instead of
            # re-billing full price every turn. OpenAI does this
            # automatically already (verified live: 98.5% cache hit rate on
            # a real GPT-4o-mini run, no code needed); Gemini's equivalent
            # requires Vertex AI + GCP credentials, not yet configured.
            # Content-block format is Anthropic's own public API spec —
            # litellm passes it through unmodified for anthropic/* models.
            if self.model.startswith("anthropic/"):
                messages.append({
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": self.system_preamble,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                })
            else:
                messages.append({"role": "system", "content": self.system_preamble})
        messages.append({"role": "user", "content": self.goal})
        tools = self.adapter.tools(neutral_descriptions=True)
        
        turn = 0
        while turn < self.max_turns:
            turn += 1
            
            # If no tools, just generate a raw response.
            # If tools exist, provide them to the model.
            kwargs = {}
            if tools:
                kwargs["tools"] = tools
                
            try:
                # The generic completion call
                response = litellm.completion(
                    model=self.model,
                    messages=messages,
                    **kwargs
                )
            except Exception as e:
                self.trace.run_end("error", turns_used=turn, error=str(e))
                return MonolithResult(
                    outcome="error", analysis=None, run_id=self.trace.run_id, error=str(e)
                )

            # litellm can return a response with an empty choices list (seen
            # live, 2026-07-23, gemini/gemini-2.5-flash — crashed the whole
            # run with an unguarded IndexError). Treat it the same as a
            # completion-call exception: a graceful, gradable failure, not a
            # crash that loses the whole trace.
            if not response.choices:
                err = "litellm.completion returned an empty choices list"
                self.trace.run_end("error", turns_used=turn, error=err)
                return MonolithResult(
                    outcome="error", analysis=None, run_id=self.trace.run_id, error=err
                )

            msg = response.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))
            self.trace.model_response(
                turn, getattr(msg, "content", "") or "",
                getattr(msg, "tool_calls", None), response=response,
            )

            # If the model chose to call tools
            if getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    f = tc.function
                    name = f.name
                    try:
                        args = json.loads(f.arguments)
                    except Exception as e:
                        args = {"error": f"Invalid JSON in arguments: {str(e)}"}

                    self.trace.tool_call(turn, tc.id, name, args)

                    refusal = None
                    for hook in self.hooks:
                        refusal = hook(name, args, self.hook_state)
                        if refusal:
                            break
                    self.hook_state.record_call(name)

                    adapter_mode = getattr(self.adapter, "mode", None)
                    if refusal:
                        result_str = refusal
                        self.trace.tool_result(turn, tc.id, name, result_str,
                                               error_reason="gate_refused", mode=adapter_mode)
                    else:
                        try:
                            result_str = self.adapter.execute_tool(name, args)
                            self.trace.tool_result(turn, tc.id, name, result_str, mode=adapter_mode)
                            self.hook_state.record_success(name)
                        except Exception as e:
                            result_str = f"Tool execution failed: {str(e)}"
                            self.trace.tool_result(turn, tc.id, name, result_str,
                                                   error_reason=str(e), mode=adapter_mode)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": name,
                        "content": result_str,
                    })
                continue

            # If no tools were called, the text is the final answer.
            final_text = getattr(msg, "content", "")
            if final_text:
                self.trace.final_answer(turn, final_text)
                self.trace.run_end("complete", turns_used=turn)
                return MonolithResult(
                    outcome="complete", analysis=final_text, run_id=self.trace.run_id
                )
                
        # Loop budget exhausted
        self.trace.run_end("exhausted", turns_used=turn)
        return MonolithResult(
            outcome="exhausted", analysis=None, run_id=self.trace.run_id, error="Turn budget exhausted"
        )
