"""Monolith driver for executing a benchmark against an un-partitioned target.

This driver is the baseline (Phase A). It crams all available tools into a
single context window and loops until a final answer is produced.
"""
from dataclasses import dataclass
from typing import Optional
import json
import litellm

from harnessbench.adapter import TargetAdapter
from harnessbench.trace import AgentTrace


@dataclass
class MonolithResult:
    outcome: str
    analysis: Optional[str]
    run_id: str
    error: Optional[str] = None


class MonolithDriver:
    """A generic, unspecialized agent loop."""
    
    def __init__(self, adapter: TargetAdapter, goal: str, model: str, runs_dir: str = "./agent_runs"):
        self.adapter = adapter
        self.goal = goal
        self.model = model
        self.trace = AgentTrace(
            goal=f"[monolith] {goal}", model=model,
            agents_md_loaded=False, max_turns=20,
            runs_dir=runs_dir
        )
        
    def run(self) -> MonolithResult:
        messages = [{"role": "user", "content": self.goal}]
        tools = self.adapter.tools(neutral_descriptions=True)
        
        turn = 0
        while turn < 20:
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

                    try:
                        result_str = self.adapter.execute_tool(name, args)
                        self.trace.tool_result(turn, tc.id, name, result_str)
                    except Exception as e:
                        result_str = f"Tool execution failed: {str(e)}"
                        self.trace.tool_result(turn, tc.id, name, result_str,
                                               error_reason=str(e))

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
