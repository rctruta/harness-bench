# harness-bench — extraction plan (agent layer from SBD)

> Corrected scope, 2026-07-15. This extracts the **agent-harness layer**
> (orchestrator, specialists, states, contracts, trace, markers, grader
> interface) so it can measure ANY MCP/tool agent. It does NOT extract
> SBD's metrology core (that's a separate future concern — the inference
> lab). SBD becomes the first *target adapter*: the reference implementation.

## The seam (measured, not guessed)

A file-level coupling audit of SBD's agent stack (2026-07-15) found the layer
splits cleanly:

**GENERIC ENGINE — ships in `harnessbench/`, moves near-verbatim:**

| SBD source | → harness-bench | coupling to strip |
|---|---|---|
| `agent_specialist.py` (359 loc) | `runner/specialist.py` | only `from .agent_tools import execute_tool, filter_tools` — both become adapter calls |
| `agent_trace.py` (240 loc) | `trace.py` | one hardcoded `AGENT_RUNS_DIR` path → constructor arg |
| `agent_orchestrator.py` FLOW (run/resume/ask, `_parse_*`, `poll_until_terminal`) | `runner/orchestrator.py` | role definitions move OUT to adapter; poll semantics become a `TerminalPolicy` |
| `run_study.py` (contract load + matrix expansion) | `contracts.py` | driver dispatch (`import autonomous_agent` / `Orchestrator`) → adapter-provided drivers |
| `analyze_agent_traces.py` (generic markers: first_tool, tokens, turns, outcome, error loops) | `markers.py` | SBD markers (template_first, category_filtered, projections_used) move to adapter |

**TARGET ADAPTER — SBD is the reference; a new MCP server is a new one:**

| SBD source | → SBD adapter (`adapters/sbd/`) | why it's target-specific |
|---|---|---|
| `agent_tools.py::TOOLS` + `execute_tool` + `_get_client` | `adapters/sbd/tools.py` | SBD's inventory + REST dispatch + ASGI app |
| `CONFIG_BUILDER/ANALYZER/LIBRARIAN` role defs | `adapters/sbd/roles.py` | SBD-specific prompts + tool subsets + gates |
| `poll_until_terminal` /status semantics | `adapters/sbd/terminal.py` | not every target is async submit→poll |
| `grade_analyses.py` | `adapters/sbd/oracle.py` | grades against SQL fragments (sealed ground truth) |
| SBD behavioral markers | `adapters/sbd/markers.py` | template-first etc. mean nothing for another target |

## The `TargetAdapter` interface (the load-bearing design)

Everything target-specific hides behind ONE protocol. harness-bench's engine
imports the adapter; the adapter imports nothing from the engine except types.

```python
# harnessbench/adapter.py  (the contract every target implements)
from typing import Protocol, Optional, Callable

class TargetAdapter(Protocol):
    name: str

    # --- SURFACE: what the agent can do ---
    def tools(self, neutral_descriptions: bool = False) -> list[dict]:
        """OpenAI/litellm tool schema. From MCP tools/list, an OpenAPI
        spec, or hand-written. `neutral_descriptions` supports the
        floor-ablation cell (strip steering language)."""

    def execute_tool(self, name: str, args: dict) -> str:
        """Dispatch one tool call against the live target. Returns the
        tool result as a string (JSON by convention)."""

    # --- ROLES: the state machine's specialists (optional) ---
    def roles(self) -> dict[str, "SpecialistRole"]:
        """Named specialist roles for the multi-agent driver. A simple
        target can return {} and use the monolith driver only."""

    # --- TERMINAL: how the target signals 'done' (optional) ---
    def terminal_policy(self) -> Optional["TerminalPolicy"]:
        """Async submit→poll targets (like SBD) provide one; synchronous
        targets return None (the driver treats tool-return as terminal)."""

    # --- ORACLE: ground-truth grading (optional) ---
    def oracle(self) -> Optional[Callable[[dict], dict]]:
        """Given a run's trace, return a grade verdict against the
        target's ground truth. None where no ground truth exists (then
        the report carries process markers only, honestly labelled)."""

    # --- MARKERS: target-specific behavioral signals (optional) ---
    def markers(self) -> dict[str, Callable]:
        """Extra behavioral markers layered on the generic set."""
```

The generic engine (`SpecialistRole`, `run_specialist`, `Orchestrator`,
`AgentTrace`, contract loader, generic markers) depends ONLY on this
protocol. That is the whole fork: engine + protocol + reference adapter.

## Directory layout

```
harnessbench/
├── adapter.py            # TargetAdapter protocol + SpecialistRole, TerminalPolicy types
├── trace.py              # ← agent_trace.py (AGENT_RUNS_DIR parameterized)
├── contracts.py          # ← run_study.py load_contract + matrix; driver dispatch via adapter
├── runner/
│   ├── specialist.py     # ← agent_specialist.py (execute_tool/filter_tools via adapter)
│   ├── orchestrator.py   # ← agent_orchestrator.py FLOW (roles injected from adapter)
│   └── monolith.py       # ← autonomous_agent.run_agent loop (single-agent driver)
├── markers.py            # ← analyze_agent_traces.py generic markers + provenance grouping
├── grade.py              # generic grade harness (verify-the-verifier discipline); adapter supplies the oracle
├── report.py             # cost × architecture × guidance tables (from findings 1–21 shape)
├── cli.py                # harnessbench run <contract> --target <adapter>
└── adapters/
    └── sbd/              # THE REFERENCE ADAPTER (first consumer, proves the seam)
        ├── tools.py      # ← agent_tools.py TOOLS + execute_tool + _get_client
        ├── roles.py      # ← CONFIG_BUILDER/ANALYZER/LIBRARIAN
        ├── terminal.py   # ← poll_until_terminal
        ├── oracle.py     # ← grade_analyses.py
        └── markers.py    # ← SBD behavioral markers
contracts/               # study YAMLs (gains a `target:` field)
tests/                   # port the 38 mocked-transition tests → engine tests + a FakeAdapter
```

Contract gains one field: `target: sbd` (or `mcp:stdio:<cmd>` / `openapi:<url>`
for the generic adapters that come after SBD).

## Phases (each shippable, each with an acceptance gate)

**P0 — the seam, proven.** Port `trace.py` + `runner/specialist.py` +
`adapter.py` (protocol) + a `FakeAdapter` (tools that echo, mocked). Port the
specialist-loop tests against FakeAdapter.
*Accept:* `run_specialist` drives FakeAdapter with ZERO import of anything
SBD; the ported mocked-transition tests pass; the engine has no `sql_benchmarks`
import anywhere.

**P1 — SBD as reference adapter.** Implement `adapters/sbd/` importing from
the installed `sqlbenchdag` package (or a path shim). Port the orchestrator
flow + contracts loader. Run one existing SBD contract THROUGH harness-bench.
*Accept:* the same study (same content-addressed id, comparable cost) runs via
`harnessbench run <contract> --target sbd` as it does natively in SBD —
byte-comparable traces. This is the proof the extraction is lossless.

**P2 — second target.** A generic `mcp` adapter: read a real MCP server's
`tools/list`, run the monolith driver, emit cost report. No oracle (process
markers only).
*Accept:* point at one public MCP server, get a traced cost report; the
extraction's value proposition (works on a target it wasn't built for) is
demonstrated on something that isn't SBD.

**P3 — the report + oracle framework.** `report.py` cost/marker tables;
`grade.py` with the verify-the-verifier gate; SBD's oracle plugged back in.
*Accept:* a report reproduces from traces alone; every FAIL hand-audited.

## Build rules (from the corpus, non-negotiable)

Inherit `AGENTS.md` rules 1–10. Two that bite hardest here:
- **Port, don't rewrite** — the specialist loop, the parsers, the gates are
  battle-tested (they survived the llama3 autopsy, the env-leak bug, the
  spec-skills confound). Move them; don't "improve" them mid-move.
- **The seam is the deliverable, not the code volume.** If a file won't cross
  the seam without dragging SBD with it, it belongs in the adapter, not the
  engine. When in doubt, the engine stays ignorant of the target.

## What this is NOT

- Not the metrology core extraction (hashing/sealing/matrix) — that serves
  the *domain* labs (SBD, future inference lab), not the agent layer. Different
  seam, different day.
- Not a rewrite. The agent stack already WORKS; the fork relocates it behind
  an interface so a second target can use it. If P1 traces aren't
  byte-comparable to native SBD, the extraction is wrong, not the original.
```
