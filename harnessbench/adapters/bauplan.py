"""Bauplan Lakehouse Adapter for harness-bench.

Implements the TargetAdapter contract for Bauplan lakehouse workflows:
- Exposes Bauplan CLI/SDK operations as typed tools.
- Provides Specialist Roles (DATA_EXPLORER, BRANCH_DEVELOPER, AUDITOR).
- Implements mechanical Code Gates (tool_preconditions) for lakehouse safety rules (e.g. no direct materialization on main, diff verification before merge).
"""
import dataclasses
import json
import os
import re
from typing import Dict, List, Optional, Any, Callable

from harnessbench.adapter import TargetAdapter, SpecialistRole, TerminalPolicy
from harnessbench.trace_utils import collect_tool_events


# --- Specialist System Prompts ---

_DATA_EXPLORER_PROMPT = """\
You are the Bauplan data explorer specialist. Your job is to inspect lakehouse tables and schemas.
Only call tools in your tool inventory.

Workflow:
1. Use `bauplan_table_get` to check metadata and schema for source tables.
2. Use `bauplan_query` to sample data.
3. Hand off findings with "FINAL ANSWER:" followed by a summary of the lakehouse state.
"""

_BRANCH_DEVELOPER_PROMPT_TEMPLATE = """\
You are the Bauplan branch developer specialist. Your job is to create a \
feature branch and write pipeline code (Python models, e.g. via DuckDB or \
polars) that computes the requested result.

IMPORTANT:
- Never execute or materialize directly on `main`.
- Always create a data branch first via `bauplan_checkout_branch`, named \
`{username}.<branch_name>` — your real username is `{username}`, not a \
placeholder to fill in.
- Write your own pipeline code and run it with `bauplan_write_and_run` \
(dry_run first, then for real). There is no pre-built pipeline for you.
- STOP as soon as your table has the correct data. Do not build \
additional verification, summary, or detail tables beyond what's needed \
to confirm correctness — hand off immediately once you've verified your \
one output table is right.

When ready, hand off with:
    HANDOFF: branch=<branch_name>
"""

_AUDITOR_PROMPT = """\
You are the Bauplan auditor specialist. Your job is to verify pipeline \
outputs on a feature branch and merge them into a SANDBOX target — never \
`main`, which you do not have permission to merge into (the platform will \
refuse it).

Workflow:
1. Check diff against the sandbox target with `bauplan_branch_diff`.
2. Verify the result with `bauplan_query`.
3. If correct, call `bauplan_ensure_target_branch` on the sandbox target \
(it's a no-op if the branch already exists — merging requires the target \
to exist first).
4. Call `bauplan_merge_branch` into the sandbox target you were given — \
not `main`. If this fails with MERGE_CONFLICT, the target already has a \
table with the same name but different content from an unrelated run — \
do not retry the same merge; pick a new target name instead (e.g. append \
a short unique suffix) and merge into that.
5. Close with "FINAL ANSWER: Pipeline merged successfully into <target>."
"""


# --- Specialist Roles & Code Gates ---

DATA_EXPLORER = SpecialistRole(
    name="data_explorer",
    # Was ["bauplan_table_get", "bauplan_query", "bauplan_branch_ls"] —
    # bauplan_branch_ls does not exist in tools() below; never caught
    # because this role was never actually driven until 2026-07-24.
    tool_names=["bauplan_table_get", "bauplan_query"],
    system_prompt=_DATA_EXPLORER_PROMPT,
    max_turns=10,
    parse_output=lambda content, tool_calls: {"analysis": content} if content and "final answer" in content.lower() else None
)

BRANCH_DEVELOPER = SpecialistRole(
    name="branch_developer",
    # bauplan_write_and_run added 2026-07-24 — it didn't exist when this
    # role was first written, so it was never reachable even though it's
    # the only tool that lets this role author its own pipeline code.
    tool_names=["bauplan_checkout_branch", "bauplan_run_dry_run", "bauplan_run",
                "bauplan_write_and_run", "bauplan_table_get"],
    # Inert placeholder — real runs never see this text. adapter.roles()
    # (the only path any driver uses to get this role) always overrides
    # system_prompt with the real BAUPLAN_USERNAME via dataclasses.replace.
    # Was a literal '<your-username>' in the prompt itself — two different
    # models parroted that bracket syntax back as a real branch name
    # (real incident, 2026-07-24 matched batch) — fixed by requiring a real,
    # configured username, never a hardcoded one.
    system_prompt=_BRANCH_DEVELOPER_PROMPT_TEMPLATE.format(username="<BAUPLAN_USERNAME not configured>"),
    max_turns=15,
    parse_output=lambda content, tool_calls: _parse_dev_handoff(content),
    tool_preconditions={
        # Mechanical Code Gate 1: Materialization blocked on main
        "bauplan_run": (
            "bauplan_checkout_branch",
            "REFUSED: Materialization on `main` is strictly blocked. You must create and checkout a feature branch (`username.branch`) using `bauplan_checkout_branch` before running a pipeline."
        ),
        "bauplan_write_and_run": (
            "bauplan_checkout_branch",
            "REFUSED: Materialization on `main` is strictly blocked. You must create and checkout a feature branch (`username.branch`) using `bauplan_checkout_branch` before writing and running a pipeline."
        ),
    }
)

AUDITOR = SpecialistRole(
    name="auditor",
    # bauplan_ensure_target_branch added 2026-07-24 — real Bauplan's
    # merge_branch requires the target to already exist (no auto-create),
    # and this role had no way to create one.
    tool_names=["bauplan_branch_diff", "bauplan_query", "bauplan_merge_branch",
                "bauplan_ensure_target_branch"],
    system_prompt=_AUDITOR_PROMPT,
    max_turns=10,
    parse_output=lambda content, tool_calls: {"analysis": content} if content and "final answer" in content.lower() else None,
    tool_preconditions={
        # Mechanical Code Gate 2: Merge requires diff verification first
        "bauplan_merge_branch": (
            "bauplan_branch_diff",
            "REFUSED: You must review changes with `bauplan_branch_diff` before merging a feature branch into `main`."
        ),
    }
)


def _parse_dev_handoff(content: str) -> Optional[dict]:
    """Was HANDOFF: branch=X job_id=Y — job_id is vestigial (copied from
    SBD's async submit/poll pattern). Bauplan's operations are synchronous
    (terminal_policy() returns None below, no polling), so there is no
    job to hand off — only which branch has the work. Fixed 2026-07-24,
    caught while actually driving this role for the first time."""
    if not content:
        return None
    m = re.search(r"HANDOFF:\s*branch=(\S+)", content, re.IGNORECASE)
    if m:
        return {"branch": m.group(1)}
    return None


# --- Target Adapter Implementation ---

class BauplanAdapter(TargetAdapter):
    """Adapter exposing Bauplan lakehouse primitives to harness-bench.

    IMPORTANT: as of this writing there is no live Bauplan SDK/CLI call
    implemented anywhere in this class — execute_tool() only ever returns
    hardcoded, simulated data. mock_mode=False therefore fails loudly on
    first use instead of silently returning fabricated data labeled "real".
    Wire a live path in execute_tool() before this can honestly be False.
    """

    def __init__(self, mock_mode: bool = True):
        self.mock_mode = mock_mode
        # .mode is read by the trace/report pipeline (markers.py, report.py)
        # to stamp and, if unacknowledged, refuse rendering mock results as
        # if they were real. See harnessbench/report.py:MockTraceError.
        self.mode = "mock" if mock_mode else "real"
        self._active_branch = "main"
        self._branches = {"main": {"commit": "c0_init"}}
        self._history: List[dict] = []
        # No hardcoded username — read from BAUPLAN_USERNAME, matching
        # BAUPLAN_API_KEY's own env-driven pattern. Was a literal "ramona."
        # scattered across this file; fixed 2026-07-24 (see the prompt
        # placeholder incident this same fix responds to). Real mode fails
        # fast if unset, since every branch-ownership guard depends on it;
        # mock mode doesn't enforce ownership at all (see execute_tool),
        # so it's allowed to run unconfigured.
        self._username = os.getenv("BAUPLAN_USERNAME")
        if not mock_mode and not self._username:
            raise RuntimeError(
                "BAUPLAN_USERNAME is not set. Real Bauplan runs need a real "
                "username to scope branch ownership — set it in .env."
            )

    @property
    def name(self) -> str:
        return "bauplan_lakehouse"

    def healthcheck(self) -> None:
        """Mock mode declares itself honestly and passes trivially — there is
        nothing live to check. Real mode MUST verify the actual Bauplan
        CLI/SDK is present and authenticated; it raises if not, so
        check_environment() (api.py) blocks the run before any tool call.
        """
        if self.mock_mode:
            return
        # Live identity check (verified live 2026-07-23: client.info() ->
        # InfoState(user=..., organization=...)) — catches bad/missing auth,
        # not just a missing CLI (this adapter uses the Python SDK, not the
        # CLI, so a PATH check would have been the wrong thing to verify).
        client = self._real_client()
        try:
            info = client.info()
        except Exception as e:
            raise RuntimeError(f"Bauplan authentication failed: {e}") from e
        if not getattr(info, "user", None):
            raise RuntimeError("Bauplan healthcheck: no authenticated user returned.")

    def tools(self, neutral_descriptions: bool = False) -> List[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "bauplan_checkout_branch",
                    "description": "Create and switch to a new Bauplan data branch (naming: username.feature).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "branch_name": {"type": "string", "description": f"Branch name (e.g. {self._username}.feature-pipeline)"},
                            "from_ref": {"type": "string", "description": "Source ref, default 'main'"}
                        },
                        "required": ["branch_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "bauplan_table_get",
                    "description": "Inspect table metadata and schema in the lakehouse.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "table_ref": {"type": "string", "description": "Fully qualified table name (namespace.table)"}
                        },
                        "required": ["table_ref"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "bauplan_query",
                    "description": "Run a SQL query over Bauplan lakehouse tables.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "SQL query string"},
                            "max_rows": {"type": "integer", "description": "Row limit (default 10)"}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "bauplan_run_dry_run",
                    "description": "Dry-run a DAG transformation pipeline without materializing tables.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pipeline_path": {"type": "string", "description": "Path to pipeline directory"}
                        },
                        "required": ["pipeline_path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "bauplan_run",
                    "description": "Materialize pipeline outputs on the active data branch.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pipeline_path": {"type": "string", "description": "Path to pipeline directory"}
                        },
                        "required": ["pipeline_path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "bauplan_branch_diff",
                    "description": (
                        "List tables added/removed on the active branch relative to a "
                        "target ref, with row counts for added tables. Use this to find "
                        "the actual name of any table your pipeline created — don't guess it."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target_ref": {"type": "string", "description": "Target reference to compare against (e.g. main)"}
                        },
                        "required": ["target_ref"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "bauplan_merge_branch",
                    "description": "Merge a feature data branch into main to publish changes.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "branch_name": {"type": "string", "description": "Feature branch to merge"},
                            "into_ref": {"type": "string", "description": "Target branch (default main)"}
                        },
                        "required": ["branch_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "bauplan_write_and_run",
                    "description": (
                        "Write pipeline project files and run them on the active branch. "
                        "Requires EXACTLY this project structure (real Bauplan schema, not "
                        "guessable from field names — verified 2026-07-24; a prior run "
                        "burned its whole turn budget guessing wrong shapes):\n\n"
                        "bauplan_project.yml MUST be:\n"
                        "  project:\n"
                        "    id: <any valid UUID4 string>\n"
                        "    name: <short_name>\n\n"
                        "models.py MUST define each model as a function decorated with "
                        "@bauplan.model(...) and @bauplan.python('3.11', pip={...}), with "
                        "upstream tables declared as typed default arguments via "
                        "bauplan.Model('namespace.table', columns=[...], filter='...'), e.g.:\n"
                        "  import bauplan\n"
                        "  @bauplan.model(materialization_strategy='REPLACE')\n"
                        "  @bauplan.python('3.11', pip={'duckdb': '1.0.0'})\n"
                        "  def my_result(orders=bauplan.Model('tpch_1.orders', columns=[...])):\n"
                        "      import duckdb\n"
                        "      con = duckdb.connect()\n"
                        "      con.register('orders', orders)\n"
                        "      return con.execute('SELECT ...').fetch_arrow_table()\n"
                        "A bare function with no bauplan decorators, or a function returning "
                        "a raw SQL string, will fail to parse."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "project_files": {
                                "type": "object",
                                "description": "Map of relative file path -> full file content, e.g. {'bauplan_project.yml': '...', 'models.py': '...'}"
                            },
                            "dry_run": {"type": "boolean", "description": "Validate without materializing (default false)"}
                        },
                        "required": ["project_files"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "bauplan_ensure_target_branch",
                    "description": (
                        "Create a branch to use as a merge target if it doesn't already "
                        "exist yet (no-op if it does). Unlike bauplan_checkout_branch, this "
                        "does NOT switch your active branch — use it right before merging, "
                        "so verification queries against your working branch aren't affected."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "branch_name": {"type": "string", "description": f"Branch name (e.g. {self._username}.sandbox-x)"},
                            "from_ref": {"type": "string", "description": "Source ref if creation is needed, default 'main'"}
                        },
                        "required": ["branch_name"]
                    }
                }
            }
        ]

    # PoC-scoped safety limits (2026-07-23). This adapter's real path was
    # wired specifically for the harness-bench Q3 branch/verify/merge
    # experiment (specimen SBD-10 follow-up) — it is deliberately narrow,
    # not a general Bauplan client. Two hard, mechanical refusals below
    # protect the real shared "Bauplan Alpha" org: an agent bug or a bad
    # tool call cannot touch `main` or another user's branch, regardless
    # of what the LLM decides to do.
    _SHARED_MAIN = "main"

    def _require_own_branch(self, branch: str) -> None:
        prefix = f"{self._username}."
        if not branch.startswith(prefix):
            raise PermissionError(
                f"Refused: '{branch}' is not a {prefix}* branch. This adapter "
                "only operates on branches you own, per Bauplan's own naming "
                "convention (only username-prefixed branches are writable)."
            )

    def _real_client(self):
        if not hasattr(self, "_client"):
            import bauplan as _bauplan
            self._client = _bauplan.Client()
        return self._client

    def execute_tool(self, name: str, args: dict) -> str:
        if not self.mock_mode:
            try:
                return self._execute_tool_real(name, args)
            except Exception as e:
                # _execute_tool_real calls the real Bauplan SDK, which raises
                # (e.g. ApiError on bad SQL) rather than returning an error
                # value. Uncaught, that exception propagated past
                # run_specialist and crashed the whole orchestrator run
                # instead of giving the agent a chance to see the error and
                # retry — real incident, 2026-07-24 (bad DATE literal in a
                # data_explorer probe query killed the run before
                # branch_developer even started). Surface it as a normal
                # tool-result error instead.
                return json.dumps({"status": "error", "error": str(e)})
        self._history.append({"tool": name, "args": args, "branch": self._active_branch})

        if name == "bauplan_checkout_branch":
            branch = args["branch_name"]
            self._branches[branch] = {"commit": "c1_dev"}
            self._active_branch = branch
            return json.dumps({"status": "ok", "active_branch": branch})

        elif name == "bauplan_table_get":
            tbl = args.get("table_ref", "bauplan.data")
            return json.dumps({
                "table": tbl,
                "schema": {"id": "int64", "value": "float64", "category": "string"},
                "num_rows": 10500
            })

        elif name == "bauplan_query":
            q = args.get("query", "")
            return json.dumps({"status": "ok", "rows": [{"count": 105}], "query": q})

        elif name == "bauplan_run_dry_run":
            return json.dumps({"status": "dry_run_success", "preview": "DAG structure valid, 2 models checked"})

        elif name == "bauplan_run":
            if self._active_branch == "main":
                return json.dumps({"status": "error", "message": "Materialization blocked on main branch."})
            return json.dumps({"status": "materialized", "job_id": "job_9981a2", "branch": self._active_branch})

        elif name == "bauplan_branch_diff":
            return json.dumps({
                "diff": {"tables_added": ["clean_trips"], "rows_changed": 105, "status": "clean"}
            })

        elif name == "bauplan_merge_branch":
            target = args.get("into_ref", "main")
            return json.dumps({"status": "merged", "from": args["branch_name"], "into": target})

        elif name == "bauplan_ensure_target_branch":
            branch = args["branch_name"]
            self._branches.setdefault(branch, {"commit": "c0_base"})
            return json.dumps({"status": "ok", "branch": branch, "created": True})

        return json.dumps({"error": f"Unknown tool: {name}"})

    def _execute_tool_real(self, name: str, args: dict) -> str:
        """Every call here mirrors a call hand-verified live against the real
        Bauplan SDK on 2026-07-23 (branch create, dry-run, run, query,
        has_table, merge_branch, delete_branch) — nothing here is a first
        guess. See scratch/harness-bench-architecture.md and the SBD-10
        specimen for why this exists."""
        client = self._real_client()
        self._history.append({"tool": name, "args": args, "branch": self._active_branch})

        if name == "bauplan_checkout_branch":
            branch = args["branch_name"]
            self._require_own_branch(branch)
            from_ref = args.get("from_ref") or self._SHARED_MAIN
            # Was if_not_exists=True: silently adopted a PRE-EXISTING branch
            # under this exact name with no warning, even if it belonged to
            # someone/something else and had real history that wasn't ours.
            # Real incident, 2026-07-24 (Ramona found unrelated commits under
            # her own branch prefix). Refuse loudly instead — a name
            # collision must be visible, never silently absorbed.
            if client.has_branch(branch):
                return json.dumps({
                    "status": "error",
                    "message": (
                        f"REFUSED: branch '{branch}' already exists. Creating it would "
                        f"silently adopt whatever history is already there instead of "
                        f"starting fresh. Choose a different, more specific branch name."
                    ),
                })
            client.create_branch(branch, from_ref=from_ref)
            self._active_branch = branch
            return json.dumps({"status": "ok", "active_branch": branch})

        elif name == "bauplan_table_get":
            tbl = args.get("table_ref", "")
            ref = self._active_branch or self._SHARED_MAIN
            t = client.get_table(tbl, ref=ref)
            return json.dumps({
                "table": tbl, "ref": ref,
                "schema": {f.name: str(f.type) for f in t.fields},
            })

        elif name == "bauplan_query":
            q = args.get("query", "")
            max_rows = args.get("max_rows", 10)
            ref = self._active_branch or self._SHARED_MAIN
            t = client.query(q, ref=ref, max_rows=max_rows)
            # default=str: TPC-H tables have real date columns, and
            # pyarrow's to_pylist() returns datetime.date objects, which
            # json.dumps can't serialize by default. Real incident,
            # 2026-07-24 — every query touching o_orderdate/l_shipdate
            # errored, forcing agents to discover CAST(...AS VARCHAR) as a
            # workaround by trial and error.
            return json.dumps({"status": "ok", "rows": t.to_pylist(), "query": q}, default=str)

        elif name == "bauplan_run_dry_run":
            pipeline_path = args.get("pipeline_path", "")
            ref = self._active_branch
            if not ref or ref == self._SHARED_MAIN:
                return json.dumps({"status": "error", "message": f"Checkout a {self._username}.* branch before running."})
            state = client.run(project_dir=pipeline_path, ref=ref, dry_run=True)
            return json.dumps({"status": state.job_status, "error": state.error})

        elif name == "bauplan_run":
            pipeline_path = args.get("pipeline_path", "")
            ref = self._active_branch
            if not ref or ref == self._SHARED_MAIN:
                return json.dumps({"status": "error", "message": f"Materialization blocked: checkout a {self._username}.* branch first."})
            state = client.run(project_dir=pipeline_path, ref=ref)
            return json.dumps({"status": state.job_status, "error": state.error, "branch": ref})

        elif name == "bauplan_branch_diff":
            # Real Bauplan has no native diff API — bauplan.Client has no
            # diff-shaped method (confirmed 2026-07-24 by listing every
            # public method on the real SDK client) and the real MCP
            # server has no diff tool either, so this is a value WE
            # compute, not something Bauplan provides.
            #
            # Was hardcoded to one specific table name (_POC_TABLE) from
            # Phase A's pre-built pipeline. Broke the moment a
            # self-authored pipeline (branch_developer, driven for the
            # first time by BauplanOrchestrator) picked a different output
            # table name — real incident, 2026-07-24. Fixed by enumerating
            # the actual table catalog on each ref via get_tables() and
            # computing a real set difference — no assumption about what
            # the pipeline is named. Row counts are only queried for ADDED
            # tables (not all ~100+ tables in the shared org catalog that
            # every branch inherits) to keep this cheap.
            target_ref = args.get("target_ref", self._SHARED_MAIN)
            ref = self._active_branch
            if not ref:
                return json.dumps({"status": "error", "message": "No active branch to diff."})
            branch_tables = {t.fqn for t in client.get_tables(ref=ref)}
            target_tables = {t.fqn for t in client.get_tables(ref=target_ref)}
            added = sorted(branch_tables - target_tables)
            removed = sorted(target_tables - branch_tables)
            row_counts_added = {}
            for fqn in added:
                t = client.query(f"SELECT COUNT(*) as n FROM {fqn}", ref=ref)
                row_counts_added[fqn] = t.to_pylist()[0]["n"]
            status = "clean" if added and not removed else ("no_change" if not added and not removed else "changed")
            return json.dumps({
                "tables_added": added, "tables_removed": removed,
                "row_counts_added": row_counts_added, "status": status,
            })

        elif name == "bauplan_merge_branch":
            branch = args["branch_name"]
            self._require_own_branch(branch)
            into_ref = args.get("into_ref") or self._SHARED_MAIN
            if into_ref == self._SHARED_MAIN:
                # Hard refusal, not a prompt instruction: this PoC must never
                # merge into the real shared org branch other users depend on.
                return json.dumps({
                    "status": "error",
                    "message": (
                        "REFUSED: merging into 'main' is disabled for this PoC. "
                        f"Merge into your own sandbox branch instead, e.g. "
                        f"'{self._username}.sandbox-main'."
                    ),
                })
            self._require_own_branch(into_ref)
            try:
                commit = client.merge_branch(
                    source_ref=branch, into_branch=into_ref,
                    commit_message=f"harness-bench agent run: merge {branch} into {into_ref}",
                )
            except Exception as e:
                # MERGE_CONFLICT specifically, not generic — the target
                # branch already has a table with the same name but
                # DIFFERENT content, usually from an earlier, unrelated
                # run that happened to pick the same table name (e.g.
                # 'q3_shipping_priority' is a common, predictable choice
                # across independent runs). Real incident, 2026-07-24:
                # the generic "vary your approach" coaching fired
                # correctly but the agent didn't know the specific fix
                # and burned its remaining turns investigating instead of
                # picking a new target. Retrying the same merge, or a
                # different SOURCE branch, cannot fix this — only a
                # different, not-yet-used TARGET can. Say so explicitly.
                if "MERGE_CONFLICT" in str(e):
                    return json.dumps({
                        "status": "error",
                        "error": (
                            f"MERGE_CONFLICT: '{into_ref}' already has a table with "
                            f"the same name but different content, from a different, "
                            f"unrelated run. Retrying this exact merge will not work — "
                            f"instead, pick a NEW target branch name (e.g. append a "
                            f"short unique suffix to '{into_ref}') and merge into that "
                            f"instead. Original error: {e}"
                        ),
                    })
                return json.dumps({"status": "error", "error": str(e)})
            return json.dumps({"status": "merged", "from": branch, "into": into_ref, "commit": str(commit)})

        elif name == "bauplan_write_and_run":
            import tempfile
            ref = self._active_branch
            if not ref or ref == self._SHARED_MAIN:
                return json.dumps({"status": "error", "message": f"Checkout a {self._username}.* branch before writing/running."})
            project_files = args.get("project_files") or {}
            with tempfile.TemporaryDirectory() as tmpdir:
                for relpath, content in project_files.items():
                    if ".." in relpath or relpath.startswith("/"):
                        return json.dumps({"status": "error", "message": f"Invalid path: {relpath}"})
                    full = os.path.join(tmpdir, relpath)
                    os.makedirs(os.path.dirname(full) or tmpdir, exist_ok=True)
                    with open(full, "w", encoding="utf-8") as f:
                        f.write(content)
                state = client.run(project_dir=tmpdir, ref=ref, dry_run=args.get("dry_run", False))
                return json.dumps({"status": state.job_status, "error": state.error, "branch": ref})

        elif name == "bauplan_ensure_target_branch":
            # Real Bauplan's merge_branch requires the target branch to
            # already exist (confirmed by reading the real MCP server's
            # merge_branch tool — no auto-create). Real incident,
            # 2026-07-24: an auditor tried merging into a fresh sandbox
            # target that nobody had ever created and got BRANCH_NOT_FOUND
            # on every attempt. Deliberately does NOT call
            # self._active_branch = branch — this must not disturb the
            # branch the auditor is verifying against.
            branch = args["branch_name"]
            self._require_own_branch(branch)
            if client.has_branch(branch):
                return json.dumps({"status": "ok", "branch": branch, "created": False})
            from_ref = args.get("from_ref") or self._SHARED_MAIN
            client.create_branch(branch, from_ref=from_ref)
            return json.dumps({"status": "ok", "branch": branch, "created": True})

        return json.dumps({"error": f"Unknown tool: {name}"})

    def roles(self) -> Dict[str, SpecialistRole]:
        # BRANCH_DEVELOPER's module-level system_prompt is an inert
        # placeholder (see its definition) — every real driver goes through
        # roles(), so this is the one place the real, configured username
        # actually reaches the prompt text.
        branch_developer = dataclasses.replace(
            BRANCH_DEVELOPER,
            system_prompt=_BRANCH_DEVELOPER_PROMPT_TEMPLATE.format(username=self._username),
        )
        return {
            "data_explorer": DATA_EXPLORER,
            "branch_developer": branch_developer,
            "auditor": AUDITOR,
        }

    def terminal_policy(self) -> Optional[TerminalPolicy]:
        return None

    def grader(self) -> Optional[Callable[[str], dict]]:
        """grade_study() (grade.py) calls this with a trace file PATH, not a
        dict — matching the SBD reference adapter's convention. Uses the
        shared trace_utils.collect_tool_events() traversal (raw JSONL, top
        trace + delegated specialist sub-runs) so the verdict and the
        'simulated' flag are independently re-derived from ground truth,
        not trusted from any upstream summary. This is Gate C (see specimen
        SBD-10, dual_agent_collaboration.md): a grade can no longer be
        produced without the grader itself checking whether the underlying
        tool calls were real or mocked.
        """
        def _grade(trace_path: str) -> dict:
            tool_names, modes = collect_tool_events(trace_path)

            has_diff = "bauplan_branch_diff" in tool_names
            has_merge = "bauplan_merge_branch" in tool_names

            result: Dict[str, Any] = {"simulated": "mock" in modes}
            if has_merge and not has_diff:
                result.update({"verdict": "FAIL", "reason": "Merged without diff verification"})
            else:
                result.update({"verdict": "PASS", "score": 1.0})
            return result

        return _grade

    def markers(self) -> Dict[str, Callable]:
        # No Bauplan-specific behavioral markers beyond the generic set yet.
        # Without this override, BauplanAdapter (subclassing the
        # TargetAdapter Protocol directly) falls through to the Protocol's
        # own stub body and returns None, which crashes markers.py's
        # `adapter.markers().items()` — never caught before because no test
        # exercised a real grade_study() pass until Gate B unblocked one.
        return {}
