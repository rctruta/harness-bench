# harness-bench — the work before the work, generalized

**Mission.** Before an organization deploys LLM agents over MCP servers / tool
APIs, harness-bench measures what that deployment will actually cost and where
it will actually fail: token cost per architecture, which guidance layers pay
for themselves, which model tier suffices, what states and gates the harness is
missing. It reads a tool surface, infers a taxonomy, probes with contract-driven
studies, traces everything, grades what can be graded, and reports.

Everyone ships SKILLS and MCP servers; nobody measures them. This is the
instrument.

**Provenance.** Generalized from a working, verified implementation:
`sql-benchmarks-dagster` (sqlbenchdag), where this exact loop ran end-to-end —
16 content-addressed studies, 7 models, 110+ graded runs, findings 1–21.
Reference implementations are cited per component below; the builder's job is
to PORT and GENERALIZE, not invent.

## Measured priors (design constraints, not opinions)

1. Harness architecture dominates model choice: 20.7× cost reduction at equal
   answer quality; specialist decomposition equalized 5 models / 2 vendors into
   one 18–35K token band.
2. Prompt guidance is the weakest lever (AGENTS.md ≈ +50K tokens/run, zero
   behavioral delta); tool schema + role prompts carry frontier models.
3. Words don't bind; gates do. Every prompt instruction was eventually ignored
   by some model; every mechanical gate held (template-first precondition,
   memory caps, tool preconditions).
4. States are DISCOVERED by probing, not designed: refusal, suspend/resume,
   librarian, needs_experiment, resource caps all emerged from cheap probe runs.
5. Uniform cross-model failure = harness defect, not model defect. The model
   ladder inside one contract makes this signature self-identifying.
6. Grade the answers deterministically or you have anecdotes; and verify the
   verifier (first grader run had a false FAIL from LaTeX notation).
7. Replication discipline: n≥3 only when estimating distributions; n=1 for
   gate verification.

## Architecture (component → sqlbenchdag reference)

| Component | Job | Reference implementation |
|---|---|---|
| `surface.py` | Read the target: MCP `tools/list` (stdio/HTTP) or OpenAPI → normalized tool inventory (name, description, params schema) | new; schema shape mirrors `sql_benchmarks/agent_tools.py::TOOLS` |
| `taxonomy.py` | Infer categories over the inventory (LLM-assisted draft → human-approved, frozen YAML). Progressive disclosure needs a vocabulary | `sql_benchmarks/experiments/taxonomy.yaml`, `api/data/taxonomy.py` |
| `contracts.py` | Content-addressed study contracts: goals × models × cells(flags) × reps; study_id = sha256(bytes)[:8] | `scripts/run_study.py::load_contract` |
| `runner.py` | Drivers: monolith loop + specialist state machine (librarian → builder → poll/act → analyzer), per-run isolation, hardening (raw-text tool-call recovery, repeated-failing-call breaker, tool preconditions) | `sql_benchmarks/agent_specialist.py`, `agent_orchestrator.py`, `scripts/autonomous_agent.py` |
| `trace.py` | Per-turn JSONL: run_start, model_response(+usage), tool_call/result, nudge, delegate, run_end, prompt_provenance (sha256 per prompt component + ablation flags) | `sql_benchmarks/agent_trace.py` (post PR #159 — study-dir grouping, no env mutation) |
| `markers.py` | Generic behavioral markers from traces: first tool, narrowing-tool use, error loops, recovery events, gate refusals, tokens/turns per stage | `scripts/tools/analyze_agent_traces.py` |
| `oracles.py` | Pluggable answer-grading. Interface: `ground_truth(target, run) -> derivable facts`; verdicts PASS/PARTIAL/FAIL, flag-don't-convict. THE HARD PART in the general case — ship with: exact-value oracle (APIs with queryable truth), schema-conformance oracle, and human-spot-check protocol for the rest | `scripts/tools/grade_analyses.py` |
| `states.py` (v2) | Mine traces for missing-state signatures: uniform cross-model failure, thrash-to-honest-failure (needs refusal), poll timeouts on legit work (needs suspend/resume), knowledge re-derivation (needs librarian) | decisions_log entries 2026-07-05/06 document each discovery pattern |
| `report.py` | The deliverable: cost table per (model × architecture × guidance), marker table, grade distribution, discovered-gaps list with proposed gates | methodology-doc tables (findings 1–21) |

## MVP phases (each independently shippable, each with acceptance criteria)

**Phase 0 — read + probe (the MVP).**
Point at one MCP server. Read tools. Draft taxonomy (LLM) → freeze to YAML.
Run one contract: 2 models × monolith × 3 goals, n=1. Emit traces + cost
report. NO grading, NO specialists.
*Accept:* report reproduces from traces alone; a second run of the same
contract yields the same study_id and comparable costs.

**Phase 1 — architecture A/B.**
Add the specialist driver (port the state machine). Same contract, both
drivers. Report shows the architecture delta per model.
*Accept:* the sqlbenchdag result shape (decomposition compresses cost/variance)
is reproducible on a second, unrelated tool surface.

**Phase 2 — gates + discovered states.**
Hardening ports (recovery, breaker, preconditions) + suspend/resume + refusal.
*Accept:* an impossible goal produces a structured refusal, not thrash; a
slow tool produces suspended, not failure.

**Phase 3 — grading + state inference.**
Oracle interface + at least one real oracle for the chosen target; states.py
mining with the four signatures.
*Accept:* 0 false FAILs on a hand-audited sample (verify the verifier).

## Cost model (from measured data)

Probe runs cost 5–60K tokens each depending on architecture/guidance
(monolith rich-guidance worst, specialist best). A Phase-0 engagement
(2 models × 3 goals × 2 conditions, n=1) ≈ 12 runs ≈ 150–500K tokens ≈
single-digit dollars on current pricing. The report pays for itself the
first time it prevents one wrong-model or wrong-architecture default.

## Non-goals

- Not an agent framework. It measures agents; it ships only the minimal
  drivers needed to probe.
- Not a benchmark leaderboard. Results are per-target-harness, sealed and
  reproducible, not universal scores.
- No history rewriting of the reference lab: sqlbenchdag stays the citable
  origin.
