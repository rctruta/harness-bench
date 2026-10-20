<!-- Generated from trace JSONL in runs/motherduck-study/; grading tolerance ±1.0 vs seeded ground truth (scripts/make_motherduck_study_db.py). -->

# MotherDuck MCP study: raw-SQL surface × mechanical gates

- Target: `mcp-server-motherduck` v1.0.7 (stdio, read-only, server-side result limits: 1024 rows / 50K chars)
- DB: deterministic seed, ground truth printed by the seeding script
- 3 goals x {gpt-4o-mini, claude-haiku-4.5, o3-mini, claude-sonnet-5} x {baseline, gated}, n=1
- Gates (gated cell): require_before(list_tables -> execute_query), deny_args(unbounded SELECT *), max_calls(execute_query, 8)

| goal | model | cell | grade | turns | tokens | first tool | discovery calls | gate refusals | sql errors |
|---|---|---|---|---|---|---|---|---|---|
| total_revenue | anthropic-claude-haiku-4-5-202 | baseline | PASS | 4 | 6,374 | list_databases | 3 | 0 | 0 |
| total_revenue | anthropic-claude-haiku-4-5-202 | gated | PASS | 5 | 7,686 | list_databases | 3 | 0 | 0 |
| total_revenue | anthropic-claude-sonnet-5 | baseline | PASS | 4 | 6,114 | list_tables | 2 | 0 | 0 |
| total_revenue | anthropic-claude-sonnet-5 | gated | PASS | 4 | 6,109 | list_tables | 2 | 0 | 0 |
| total_revenue | gpt-4o-mini | baseline | PASS | 4 | 2,397 | execute_query | 1 | 0 | 1 |
| total_revenue | gpt-4o-mini | gated | PASS | 6 | 3,863 | execute_query | 2 | 1 | 1 |
| total_revenue | o3-mini | baseline | PASS | 3 | 2,338 | list_columns | 1 | 0 | 0 |
| total_revenue | o3-mini | gated | PASS | 6 | 4,463 | execute_query | 2 | 1 | 1 |
| top_region | anthropic-claude-haiku-4-5-202 | baseline | PASS | 4 | 7,022 | list_databases | 4 | 0 | 0 |
| top_region | anthropic-claude-haiku-4-5-202 | gated | PASS | 4 | 6,617 | list_tables | 3 | 0 | 0 |
| top_region | anthropic-claude-sonnet-5 | baseline | PASS | 5 | 8,590 | list_databases | 4 | 0 | 0 |
| top_region | anthropic-claude-sonnet-5 | gated | PASS | 4 | 6,961 | list_tables | 3 | 0 | 0 |
| top_region | gpt-4o-mini | baseline | PASS | 4 | 2,533 | execute_query | 1 | 0 | 1 |
| top_region | gpt-4o-mini | gated | PASS | 6 | 4,122 | execute_query | 2 | 1 | 1 |
| top_region | o3-mini | baseline | PASS | 4 | 3,629 | execute_query | 1 | 0 | 1 |
| top_region | o3-mini | gated | PASS | 4 | 2,932 | list_tables | 2 | 0 | 0 |
| gold_revenue | anthropic-claude-haiku-4-5-202 | baseline | PASS | 4 | 7,049 | list_databases | 4 | 0 | 0 |
| gold_revenue | anthropic-claude-haiku-4-5-202 | gated | PASS | 4 | 6,614 | list_tables | 3 | 0 | 0 |
| gold_revenue | anthropic-claude-sonnet-5 | baseline | PASS | 4 | 6,859 | list_tables | 3 | 0 | 0 |
| gold_revenue | anthropic-claude-sonnet-5 | gated | PASS | 4 | 6,867 | list_tables | 3 | 0 | 0 |
| gold_revenue | gpt-4o-mini | baseline | PASS | 5 | 3,554 | execute_query | 2 | 0 | 1 |
| gold_revenue | gpt-4o-mini | gated | PASS | 7 | 5,273 | execute_query | 3 | 1 | 1 |
| gold_revenue | o3-mini | baseline | PASS | 5 | 3,934 | list_tables | 3 | 0 | 0 |
| gold_revenue | o3-mini | gated | PASS | 5 | 3,973 | list_tables | 3 | 0 | 0 |

All 24 runs graded PASS against seeded ground truth.
