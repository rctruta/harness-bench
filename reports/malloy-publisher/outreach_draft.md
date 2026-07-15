<!-- DRAFT for Ramona to rewrite in her voice before sending. Numbers and
     claims below are verified against the traces; the framing/wording is
     placeholder. Suggested channel: GitHub issue on malloydata/publisher. -->

# Suggested title
Measured: your agent skills fix real agent failures — but agents can't reach them

# Suggested body (rework freely)

Hi — I build measurement tooling for agent/tool surfaces, and I ran your
Publisher MCP server (official Docker image, DuckDB samples) through it as a
case study. Sharing the results with you first, before I publish anything,
because most of what I found is good news you can act on.

**What I did.** Pointed an instrumented agent harness at `:4040/mcp`, gave
three models (gpt-4o-mini, claude-haiku-4.5, claude-sonnet-5) three tasks
(exact flight count, top-3 carriers, describe the ecommerce model), and ran
each task twice: once with only the MCP tool surface, once with the relevant
`skills/` bodies (from main @ ad6c09b) injected into context. Per-turn traces
for all 18 runs.

**Finding 1 — your skill content demonstrably works.** Without guidance,
the two smaller models repeatedly wrote SQL at `malloy_executeQuery`
("no viable alternative at input 'select'", 9–17 failed calls per run);
gpt-4o-mini gave up on the count task after 20 turns / 73K tokens, and
haiku-4.5 exhausted its budget at 123K. With `malloy-queries` +
`gotchas-queries` in context, the same models answered correctly
(344,827) in 3–5 turns at ~1/5 the cost. Your gotchas target exactly the
failures that actually occur.

**Finding 2 — but no autonomous agent can reach that content.**
The released image serves 4 utility prompts; the 28 skills on main are
exposed as MCP prompts, which are host/user-invoked — they never appear in
`tools/list`, so a model-driven agent cannot discover or fetch them.
In every unguided run, the guidance that would have prevented the failure
existed in your repo and was invisible to the agent.

**Finding 3 — the guidance is tier- and task-conditional.** claude-sonnet-5
needed nothing (0 query errors, cheapest correct runs), and on the
model-description task the injected skills were pure overhead (+12–20K
tokens, no behavior change). Blanket injection would be the wrong fix.

**What I'd suggest measuring toward:** compiling the gotchas into the
surface the agent *does* see — `malloy_executeQuery`'s error responses
(e.g., detect SQL-shaped input and return the translate-sql-to-malloy
guidance) and argument descriptions — rather than relying on the prompts
channel. Happy to share the full traces, the report, and the contracts so
you can rerun everything yourself, and to run any variant you'd find
useful.

[attach or paste: dynamic_report.md]
