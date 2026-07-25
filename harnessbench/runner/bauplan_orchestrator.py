"""Bauplan state-machine driver.

Explicit state machine: `data_explorer -> branch_developer -> auditor`.
Parallel to `runner/orchestrator.py`, not a modification of it —
`Orchestrator.run()` hardcodes SBD's role names (`librarian`/
`config_builder`/`analyzer`) and cannot drive any adapter with a
different role vocabulary (verified 2026-07-24 by reading it directly;
documented in scratch/harness-bench-architecture.md). Generalizing
Orchestrator itself would touch the engine SBD's published findings
depend on; this file is the safer, isolated alternative for Bauplan.

Differs from Orchestrator in one structural way: SBD's `librarian` can
short-circuit the whole run (answer from the published corpus, skip
building). Bauplan's `data_explorer` has no equivalent — there's nothing
to answer from a library. There's also no poll step: BauplanAdapter's
`terminal_policy()` returns None (synchronous operations), unlike SBD's
async submit/poll model.

`data_explorer` is DEFINED on the adapter (still available via
adapter.roles(), still directly testable) but this driver no longer
CALLS it — was a straight 3-stage pipeline (data_explorer ->
branch_developer -> auditor); now 2 stages. Real incident, 2026-07-24
matched batch: data_explorer inspects all 3 TPC-H tables, then
branch_developer independently re-fetches the exact same 3 tables from
scratch (confirmed in every trace checked) despite receiving
data_explorer's written analysis in its brief — a full redundant
specialist stage's worth of tool calls and LLM round-trips on every run,
for zero benefit, since branch_developer already has the same
inspection tools and was re-deriving the same information anyway.
"""
from dataclasses import dataclass
from typing import Optional

from harnessbench.adapter import TargetAdapter
from harnessbench.runner.specialist import SpecialistResult, run_specialist
from harnessbench.trace import AgentTrace


@dataclass
class BauplanOrchestratorResult:
    outcome: str
    branch: Optional[str]
    analysis: Optional[str]
    orchestrator_run_id: str
    sub_run_ids: dict
    error: Optional[str] = None


class BauplanOrchestrator:
    """Runs data_explorer -> branch_developer -> auditor against a
    BauplanAdapter (or anything exposing the same three role names)."""

    def __init__(self, adapter: TargetAdapter, goal: str, model: str,
                 runs_dir: str = "./agent_runs"):
        self.adapter = adapter
        self.goal = goal
        self.model = model
        self.runs_dir = runs_dir
        self.trace = AgentTrace(
            goal=f"[bauplan_orchestrator] {goal}", model=model,
            agents_md_loaded=False, max_turns=0,
            runs_dir=runs_dir
        )
        self.roles = self.adapter.roles()

    def run(self) -> BauplanOrchestratorResult:
        sub_ids: dict = {}

        # --- Stage 1: branch_developer (required — writes and runs the
        # pipeline, must hand off a branch name) ---
        # No data_explorer stage anymore — see module docstring. It was a
        # full redundant round of table inspection every branch_developer
        # repeated anyway.
        dev_role = self.roles.get("branch_developer")
        if not dev_role:
            return BauplanOrchestratorResult(
                outcome="error", branch=None, analysis=None,
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
                error="Target adapter does not define a 'branch_developer' role."
            )

        dev_brief = self.goal

        dev: SpecialistResult = run_specialist(self.adapter, dev_role, brief=dev_brief,
                                                model=self.model, runs_dir=self.runs_dir)
        sub_ids["branch_developer"] = dev.sub_run_id
        self.trace.delegate(
            stage="branch_developer", sub_run_id=dev.sub_run_id,
            input_summary=dev_brief[:200], outcome=dev.outcome,
            output_summary=(str(dev.output)[:200] if dev.output else None),
        )
        if dev.outcome != "ok" or not dev.output or "branch" not in dev.output:
            self.trace.run_end("branch_developer_failed", turns_used=0, error=dev.error)
            return BauplanOrchestratorResult(
                outcome="branch_developer_failed", branch=None, analysis=None,
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
                error=dev.error or "branch_developer produced no branch handoff",
            )
        branch = dev.output["branch"]

        # No poll stage — adapter.terminal_policy() is None for Bauplan
        # (synchronous operations). If a future adapter driven by this
        # class needs one, add it here matching Orchestrator's pattern.

        return self._auditor_stage(branch, sub_ids)

    def _auditor_stage(self, branch: str, sub_ids: dict) -> BauplanOrchestratorResult:
        auditor_role = self.roles.get("auditor")
        if not auditor_role:
            return BauplanOrchestratorResult(
                outcome="error", branch=branch, analysis=None,
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
                error="Target adapter does not define an 'auditor' role."
            )

        auditor_brief = (
            f"Branch '{branch}' has pipeline changes ready for review. "
            f"Original goal: {self.goal}\n\n"
            f"Verify the result on '{branch}' and merge it into the sandbox "
            f"target specified in the original goal — never main."
        )
        aud: SpecialistResult = run_specialist(self.adapter, auditor_role, brief=auditor_brief,
                                                model=self.model, runs_dir=self.runs_dir)
        sub_ids["auditor"] = aud.sub_run_id
        self.trace.delegate(
            stage="auditor", sub_run_id=aud.sub_run_id,
            input_summary=auditor_brief[:200], outcome=aud.outcome,
            output_summary=(str(aud.output)[:200] if aud.output else None),
        )
        if aud.outcome != "ok" or not aud.output:
            self.trace.run_end("auditor_failed", turns_used=0, error=aud.error)
            return BauplanOrchestratorResult(
                outcome="auditor_failed", branch=branch, analysis=None,
                orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
                error=aud.error or "auditor produced no final answer",
            )

        self.trace.run_end("final_answer", turns_used=0)
        return BauplanOrchestratorResult(
            outcome="complete", branch=branch, analysis=aud.output.get("analysis"),
            orchestrator_run_id=self.trace.run_id, sub_run_ids=sub_ids,
        )
