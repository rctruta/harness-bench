"""Orchestrator state machine driver.

Explicit state machine: `librarian -> config_builder -> poll -> analyzer`.
Each state is a specialist. Roles, prompts, and the polling mechanism
are completely abstracted behind the TargetAdapter interface.
"""
from dataclasses import dataclass
import json
from typing import Optional

from harnessbench.adapter import TargetAdapter
from harnessbench.runner.specialist import SpecialistResult, run_specialist
from harnessbench.trace import AgentTrace


@dataclass
class OrchestratorResult:
    outcome: str
    experiment_id: Optional[str]
    analysis: Optional[str]
    orchestrator_run_id: str
    sub_run_ids: dict
    error: Optional[str] = None


class Orchestrator:
    """Runs the state machine, pulling roles dynamically from the TargetAdapter."""

    def __init__(self, adapter: TargetAdapter, goal: str, model: str, poll_budget_seconds: float = 180.0, runs_dir: str = "./agent_runs"):
        self.adapter = adapter
        self.goal = goal
        self.model = model
        self.poll_budget_seconds = poll_budget_seconds
        self.runs_dir = runs_dir
        self.trace = AgentTrace(
            goal=f"[orchestrator] {goal}", model=model,
            agents_md_loaded=False, max_turns=0,
            runs_dir=runs_dir
        )
        self.roles = self.adapter.roles()

    def ask(self) -> OrchestratorResult:
        """Reference-desk mode: librarian ONLY."""
        sub_ids: dict = {}
        librarian_role = self.roles.get("librarian")
        if not librarian_role:
            return OrchestratorResult(
                outcome="error", experiment_id=None, analysis=None,
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
                error="Target adapter does not define a 'librarian' role."
            )

        lib = run_specialist(self.adapter, librarian_role, brief=self.goal, model=self.model, runs_dir=self.runs_dir)
        sub_ids["librarian"] = lib.sub_run_id
        self.trace.delegate(
            stage="librarian", sub_run_id=lib.sub_run_id,
            input_summary=self.goal[:200], outcome=lib.outcome,
            output_summary=(str(lib.output)[:200] if lib.output else None),
        )
        if lib.outcome == "ok" and lib.output and "analysis" in lib.output:
            self.trace.run_end("answered", turns_used=0)
            return OrchestratorResult(
                outcome="answered", experiment_id=None,
                analysis=lib.output["analysis"],
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
            )
        if lib.outcome == "ok" and lib.output and "impossible" in lib.output:
            self.trace.run_end("refused", turns_used=0)
            return OrchestratorResult(
                outcome="refused", experiment_id=None,
                analysis=f"REFUSED: {lib.output['impossible']}",
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
            )
        if lib.outcome == "ok" and lib.output and "build" in lib.output:
            self.trace.run_end("needs_experiment", turns_used=0)
            return OrchestratorResult(
                outcome="needs_experiment", experiment_id=None,
                analysis=f"NEEDS EXPERIMENT: {lib.output['build']}",
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
            )
        self.trace.run_end("librarian_failed", turns_used=0, error=lib.error)
        return OrchestratorResult(
            outcome="librarian_failed", experiment_id=None, analysis=None,
            orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
            error=lib.error or "librarian produced no parseable close",
        )

    def run(self) -> OrchestratorResult:
        sub_ids: dict = {}
        librarian_role = self.roles.get("librarian")
        
        if librarian_role:
            lib = run_specialist(self.adapter, librarian_role, brief=self.goal, model=self.model, runs_dir=self.runs_dir)
            sub_ids["librarian"] = lib.sub_run_id
            self.trace.delegate(
                stage="librarian", sub_run_id=lib.sub_run_id,
                input_summary=self.goal[:200], outcome=lib.outcome,
                output_summary=(str(lib.output)[:200] if lib.output else None),
            )
            if lib.outcome == "ok" and lib.output and "analysis" in lib.output:
                self.trace.run_end("answered", turns_used=0)
                return OrchestratorResult(
                    outcome="answered", experiment_id=None,
                    analysis=lib.output["analysis"],
                    orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
                )
            if lib.outcome == "ok" and lib.output and "impossible" in lib.output:
                self.trace.run_end("refused", turns_used=0)
                return OrchestratorResult(
                    outcome="refused", experiment_id=None,
                    analysis=f"REFUSED: {lib.output['impossible']}",
                    orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
                )

        config_builder_role = self.roles.get("config_builder")
        if not config_builder_role:
            return OrchestratorResult(
                outcome="error", experiment_id=None, analysis=None,
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
                error="Target adapter does not define a 'config_builder' role."
            )
            
        cb: SpecialistResult = run_specialist(self.adapter, config_builder_role, brief=self.goal, model=self.model, runs_dir=self.runs_dir)
        sub_ids["config_builder"] = cb.sub_run_id
        self.trace.delegate(
            stage="config_builder", sub_run_id=cb.sub_run_id,
            input_summary=self.goal[:200], outcome=cb.outcome,
            output_summary=(json.dumps(cb.output) if cb.output else None),
        )
        if cb.outcome == "ok" and cb.output and "impossible" in cb.output:
            reason = cb.output["impossible"]
            self.trace.run_end("refused", turns_used=0, error=None)
            return OrchestratorResult(
                outcome="refused", experiment_id=None,
                analysis=f"REFUSED: {reason}",
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
            )
        if cb.outcome != "ok" or not cb.output or "experiment_id" not in cb.output:
            self.trace.run_end("config_builder_failed", turns_used=0, error=cb.error)
            return OrchestratorResult(
                outcome="config_builder_failed", experiment_id=None, analysis=None,
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
                error=cb.error or "config_builder produced no experiment_id",
            )
        exp_id = cb.output["experiment_id"]

        terminal_policy = self.adapter.terminal_policy()
        if terminal_policy:
            interval = 3.0
            poll_result = terminal_policy.poll_until_terminal(
                exp_id,
                max_polls=max(1, int(self.poll_budget_seconds / interval)),
                interval_seconds=interval,
            )
            self.trace.delegate(
                stage="poll", sub_run_id=None,
                input_summary=f"experiment_id={exp_id}",
                outcome=poll_result["status"],
                output_summary=json.dumps(poll_result),
            )
            if poll_result["status"] == "timeout":
                self.trace.run_end("suspended", turns_used=0, error=None)
                return OrchestratorResult(
                    outcome="suspended", experiment_id=exp_id, analysis=None,
                    orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
                    error=None,
                )
            if poll_result["status"] != "complete":
                self.trace.run_end("poll_failed", turns_used=0, error=str(poll_result))
                return OrchestratorResult(
                    outcome="poll_failed", experiment_id=exp_id, analysis=None,
                    orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
                    error=f"poll returned {poll_result['status']}: {poll_result.get('detail') or poll_result.get('error')}",
                )

        return self._analyzer_stage(exp_id, sub_ids)

    def _analyzer_stage(self, exp_id: str, sub_ids: dict) -> OrchestratorResult:
        analyzer_role = self.roles.get("analyzer")
        if not analyzer_role:
            return OrchestratorResult(
                outcome="error", experiment_id=exp_id, analysis=None,
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
                error="Target adapter does not define an 'analyzer' role."
            )
            
        analyzer_brief = (
            f"The experiment {exp_id} has completed. Original user goal: {self.goal}\n\n"
            "Produce the analysis."
        )
        an: SpecialistResult = run_specialist(self.adapter, analyzer_role, brief=analyzer_brief, model=self.model, runs_dir=self.runs_dir)
        sub_ids["analyzer"] = an.sub_run_id
        self.trace.delegate(
            stage="analyzer", sub_run_id=an.sub_run_id,
            input_summary=analyzer_brief[:200], outcome=an.outcome,
            output_summary=(str(an.output)[:200] if an.output else None),
        )
        if an.outcome != "ok" or not an.output:
            self.trace.run_end("analyzer_failed", turns_used=0, error=an.error)
            return OrchestratorResult(
                outcome="analyzer_failed", experiment_id=exp_id, analysis=None,
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
                error=an.error or "analyzer produced no final answer",
            )

        self.trace.run_end("final_answer", turns_used=0)
        return OrchestratorResult(
            outcome="complete", experiment_id=exp_id, analysis=an.output.get("analysis"),
            orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
        )
