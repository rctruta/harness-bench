# Static skill-surface report: `/tmp/malloy-publisher/skills`

- **Skills:** 28
- **Total body size:** ~50,260 tokens (bytes/4 estimate)
- **Metadata channel (name+description, what a lazy-loading host carries every turn):** ~1,745 tokens
- **Always-loaded worst case (all bodies in prompt):** ~50,260 tokens/turn

## Per-skill inventory

| skill | ~body tokens | ~desc tokens | extra files |
|---|---|---|---|
| malloy-model | 3,460 | 60 | 5 |
| malloy-charts | 3,188 | 66 | 0 |
| gotchas-modeling | 2,929 | 76 | 0 |
| html-data-app-runtime | 2,830 | 49 | 0 |
| malloy-analyze | 2,697 | 87 | 0 |
| malloy-discover | 2,592 | 57 | 0 |
| malloy-define | 2,581 | 61 | 0 |
| malloy-modeling | 2,451 | 37 | 0 |
| malloy-queries | 2,418 | 55 | 0 |
| html-data-apps | 2,412 | 60 | 0 |
| malloy-review | 2,410 | 60 | 10 |
| malloy-document | 2,068 | 113 | 0 |
| phrase-detection | 1,771 | 53 | 0 |
| malloy-analysis | 1,610 | 61 | 0 |
| analysis-pitfalls | 1,606 | 50 | 0 |
| malloy-notebooks | 1,575 | 57 | 0 |
| analysis-report | 1,483 | 52 | 0 |
| malloy-scope | 1,270 | 50 | 0 |
| gotchas-queries | 1,246 | 51 | 0 |
| malloy-debug | 1,240 | 52 | 0 |
| malloy-publish | 1,052 | 36 | 0 |
| lookml-review | 976 | 63 | 8 |
| gotchas-rendering | 960 | 48 | 0 |
| malloy-patterns | 937 | 73 | 0 |
| malloy | 685 | 42 | 0 |
| html-data-app-embedding | 652 | 41 | 0 |
| getting-started | 607 | 88 | 0 |
| notebook-chat | 554 | 56 | 0 |

## Description collision (top pairs, Jaccard over content words)

High overlap means description-based routing must distinguish near-identical triggers.

| pair | Jaccard |
|---|---|
| gotchas-queries ↔ malloy-queries | 0.26 |
| malloy-analysis ↔ malloy-modeling | 0.25 |
| analysis-report ↔ malloy-notebooks | 0.23 |
| gotchas-rendering ↔ malloy-queries | 0.23 |
| malloy-modeling ↔ malloy-publish | 0.23 |
| malloy-model ↔ malloy-modeling | 0.21 |
| html-data-apps ↔ malloy-publish | 0.21 |
| malloy ↔ malloy-charts | 0.21 |
| malloy-analyze ↔ malloy-notebooks | 0.20 |
| gotchas-queries ↔ gotchas-rendering | 0.20 |
| malloy-modeling ↔ malloy-review | 0.19 |
| malloy-analysis ↔ malloy-publish | 0.19 |

## Body redundancy (top pairs, Jaccard over 5-gram shingles)

| pair | Jaccard |
|---|---|
| gotchas-rendering ↔ malloy-charts | 0.04 |
| gotchas-modeling ↔ malloy-modeling | 0.02 |
| analysis-report ↔ malloy-analyze | 0.02 |
| gotchas-modeling ↔ malloy-debug | 0.01 |
| malloy ↔ malloy-modeling | 0.01 |
| malloy-model ↔ malloy-notebooks | 0.01 |
| malloy-analyze ↔ malloy-charts | 0.01 |
| malloy-analyze ↔ malloy-model | 0.01 |
| malloy-document ↔ malloy-model | 0.01 |
| analysis-report ↔ malloy-queries | 0.01 |
| malloy-define ↔ malloy-discover | 0.01 |
| analysis-report ↔ malloy-charts | 0.01 |

## Prevention-class skills (guidance that must act BEFORE the error)

- **analysis-pitfalls** (~1,606 tok): Common data analysis pitfalls to watch for during query construction and result interpretation. Reference this checklist
- **gotchas-modeling** (~2,929 tok): Common Malloy modeling mistakes and how to avoid them. Read BEFORE writing source definitions, dimensions, measures, or 
- **gotchas-queries** (~1,246 tok): Common Malloy query and view mistakes. Read BEFORE writing views, queries, or notebooks. Covers chart constraints, aggre
- **gotchas-rendering** (~960 tok): Common Malloy renderer annotation mistakes. Read BEFORE adding chart annotations, formatting tags, or building dashboard
- **malloy-analysis** (~1,610 tok): Workflow for answering data questions against Malloy semantic models served by Publisher, using the malloy-publisher MCP
- **malloy-modeling** (~2,451 tok): Build semantic models with Malloy for the Malloy Publisher. Read this skill whenever the user asks about modeling data o

6 skills, ~10,802 tokens. Delivered on-demand (MCP prompts), these are consulted only after the mistake they exist to prevent — the delivery channel inverts their purpose.

---

## Interpretation (analyst notes over the derived numbers above)

**What they did well — say this first.** Total SKILL.md body mass is ~50K
tokens, but the metadata channel is only ~1.7K: the server exposes skills as
on-demand MCP prompts (packages/server/src/mcp/server.ts), so no compliant
host carries the bodies per turn. Body redundancy is near zero (max 5-gram
Jaccard 0.04) — 28 skills with almost no copy-paste. This is the most
disciplined public skills surface we have measured.

**Three measurable risks (each is a testable hypothesis for the Phase 0
dynamic study):**

1. **Dead channel.** MCP prompts are host/user-invoked, not model-invoked, in
   most harnesses. Prior measurement (sqlbenchdag Sweep B): 0/5 models called
   an optional skill-activation tool unprompted. Hypothesis: for autonomous
   agents, ~50K tokens of guidance is unreachable. Test: same goals with
   prompts available vs injected; count retrievals.
2. **Prevention paradox.** The gotchas-* / pitfalls skills (~10.8K tokens;
   keyword-classified above — verify membership manually) say "Read BEFORE
   writing..." in their own descriptions. On-demand delivery means they are
   consulted, if ever, after the mistake. The server's own source comments
   acknowledge this inversion. Test: error rates on gotcha-triggering goals,
   with and without pre-injection of the relevant gotcha body.
3. **Routing collision.** Top description-pair overlap 0.26
   (gotchas-queries ↔ malloy-queries) with several near-synonym skill names
   (malloy-model/malloy-modeling, malloy-analysis/malloy-analyze). With 28
   near-neighbors, description-based selection accuracy is measurable and
   likely imperfect. Test: routing-accuracy probe — N user intents, graded
   against intended skill.

**Oracle feasibility for Phase 0:** the server's execute_query tool against
the repo's sample models provides queryable ground truth — the same
exact-value grading discipline used in the sqlbenchdag corpus applies.

*Token figures are bytes/4 estimates; re-derive with a model tokenizer before
publishing exact counts. Earlier informal estimate of ~80K counted all files
(including malloy-review's 10 auxiliary files); SKILL.md bodies alone are ~50K.*

---

## Phase 0 dynamic probe (2026-07-14, n=1, 2 models × 3 goals)

Target: official Docker image (`ms2data/malloy-publisher:latest`), DuckDB
sample config, MCP over streamable HTTP (`:4040/mcp`). Models: gpt-4o-mini,
claude-haiku-4.5. Contracts: `contracts/malloy_p0_{count,breakdown,model}.yaml`;
traces in `runs/mcp-http-http-localhost-4040-m/`.

**Instrument note (defect caught before conclusions).** The first sweep was
invalidated by a harness-bench adapter defect: MCP embedded-resource results
were rendered to the model as the literal string `[resource content]`. Both
models then produced confident, specific, wrong flight counts ("exactly
5,000"; "9,988,909") from that placeholder — ground truth is 344,827.
Evidence-starvation fabrication reproduced across two vendors at once, and
only trace autopsy caught it. All numbers below are from the post-fix rerun.

**Results (post-fix):**

| goal | gpt-4o-mini | claude-haiku-4.5 |
|---|---|---|
| exact flight count | honest failure after 7 failed queries (26K tok) | unverified derivation after 6 failed queries (57K tok) |
| top-3 carriers | honest failure after 4 failed queries (14K tok) | **exact match to ground truth** (88,751/37,683/34,577) after 5 failed queries (40K tok) |
| model comprehension (read-only) | clean, 0 errors, 7K tok | clean, 0 errors, 12K tok |

**Findings:**

1. **The dead channel is real and its cost is measurable.** Every failed
   query in the table is a Malloy syntax/reserved-word error — the exact
   error classes `gotchas-queries` and `gotchas-modeling` (~4.2K tokens)
   exist to prevent. That guidance was unreachable: MCP prompts do not
   appear in `tools/list`, so no autonomous agent can load them. 4–7
   error-loop attempts per query goal is the per-run price of the
   unreachable guidance.
2. **Read-only goals are already well served.** Both models handled model
   comprehension cleanly through the typed read tools. The gap is
   query-*writing*, precisely where the prose guidance sits stranded.
3. **Actionable for the Publisher team (the compilation move):** attach the
   relevant gotcha snippet to `malloy_executeQuery`'s error responses
   (teach at the error site), and/or fold the top constraints into the tool's
   argument descriptions. Both deliver the existing prose through channels
   agents demonstrably receive — no new content required.

*n=1 probe; error-loop counts and token bands are indicative. A graded n=3
sweep with an exact-value oracle (execute_query ground truth, demonstrated
above) is the natural next study.*
