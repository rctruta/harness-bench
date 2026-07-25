"""Bauplan MCP surface, mirrored — tool names/descriptions/params extracted
mechanically (AST) from the real, public source at
github.com/BauplanLabs/bauplan-mcp-server, 2026-07-23. NOT synthetic.

Why a mirror instead of the live server: Bauplan's real MCP requires full
OAuth 2.0 (browser-based API-key authorization -> signed JWT), not a static
bearer token — verified live (401, then traced to
mcp_bauplan/auth/api_key_oauth.py). A headless harness can't complete that
flow without a human clicking through it once. This adapter reproduces
their real, published tool surface — same names, same descriptions, same
on-demand get_instructions/code_run design — backed by direct SDK calls
(the same auth already proven in Phase A/B), so the experiment measures the
real interface design without requiring interactive OAuth.

Only tools this PoC's task plausibly needs have real execution behind them
(see _IMPLEMENTED). The rest are present in tools() for honest schema-size
parity with the real 31-tool surface, but execute_tool() refuses them
loudly rather than fabricating a result — same discipline as BauplanAdapter
(see specimen SBD-10).
"""
import json
import os
from typing import Any, Callable, Dict, List, Optional

from harnessbench.adapter import SpecialistRole, TargetAdapter, TerminalPolicy

# Mechanically extracted from the real MCP server source (name -> (description, params)).
# Params exclude 'bauplan_client' (server-injected, not agent-visible) and 'ctx'.
_REAL_TOOLS: Dict[str, Dict[str, Any]] = {
    "apply_table_creation_plan": {"desc": "Apply a table creation plan produced by plan_table_creation.", "params": ["plan", "args", "priority", "client_timeout"]},
    "cancel_job": {"desc": "Cancel a Bauplan job by ID.", "params": ["job_id"]},
    "code_run": {"desc": "Run a Bauplan project from source files provided directly by the client.", "params": ["project_files", "ref", "namespace", "parameters", "dry_run", "client_timeout", "detach", "strict"]},
    "create_branch": {"desc": "Create a writable, zero-copy development branch from an existing branch, tag, or commit ref.", "params": ["branch", "from_ref"]},
    "create_namespace": {"desc": "Create a namespace on a writable Bauplan branch.", "params": ["namespace", "branch"]},
    "create_table": {"desc": "Create an Iceberg table from files matched by an S3 URI.", "params": ["table", "search_uri", "branch", "namespace", "partitioned_by", "replace"]},
    "create_tag": {"desc": "Create a stable catalog tag pointing to a branch, tag, or commit ref.", "params": ["tag", "from_ref"]},
    "delete_branch": {"desc": "Delete a writable Bauplan branch.", "params": ["branch"]},
    "delete_namespace": {"desc": "Delete a namespace from a writable Bauplan branch.", "params": ["namespace", "branch"]},
    "delete_table": {"desc": "Delete a table from a writable Bauplan branch.", "params": ["table", "branch", "namespace"]},
    "delete_tag": {"desc": "Delete a Bauplan catalog tag by name.", "params": ["tag"]},
    "get_branch": {"desc": "Get one catalog branch by name.", "params": ["branch"]},
    "get_branches": {"desc": "List catalog branches, optionally filtered by name or user.", "params": ["name", "user", "limit"]},
    "get_commits": {"desc": "List commits for a branch, tag, or commit ref.", "params": ["ref", "message_filter", "author_username", "author_email", "date_start", "date_end", "limit"]},
    "get_instructions": {"desc": "Get task-oriented Bauplan usage guidance for a specific workflow.", "params": ["use_case"]},
    "get_job": {"desc": "Get detailed context for one Bauplan job, including status, logs, and code snapshot when available.", "params": ["job_id"]},
    "get_jobs": {"desc": "List Bauplan jobs with optional filters for IDs, users, kinds, statuses, and creation time.", "params": ["job_ids", "job_kinds", "statuses", "user_names", "start_time", "end_time", "limit"]},
    "get_namespace": {"desc": "Retrieve a single Bauplan namespace by name at a ref.", "params": ["namespace", "ref"]},
    "get_namespaces": {"desc": "List namespaces on a branch, tag, or commit ref.", "params": ["ref", "namespace", "limit"]},
    "get_table": {"desc": "Get metadata and schema fields for one table on a branch, tag, or commit ref.", "params": ["ref", "table", "namespace"]},
    "get_tables": {"desc": "List Iceberg tables visible on a branch, tag, or commit ref.", "params": ["ref", "namespace", "table", "include_schema", "limit"]},
    "get_tag": {"desc": "Retrieve a single Bauplan tag by name.", "params": ["tag"]},
    "get_tags": {"desc": "List tags in the catalog, optionally filtered by name.", "params": ["filter_by_name", "limit"]},
    "get_user_info": {"desc": "Get the authenticated Bauplan user's username and display name.", "params": []},
    "import_data": {"desc": "Import files matched by an S3 URI into an existing table on a writable branch.", "params": ["table", "search_uri", "branch", "namespace"]},
    "merge_branch": {"desc": "Merge a source ref into a target Bauplan branch.", "params": ["source_ref", "into_branch", "commit_message", "commit_body"]},
    "plan_table_creation": {"desc": "Generate a YAML table creation plan from files matched by an S3 URI.", "params": ["table", "search_uri", "branch", "namespace", "partitioned_by", "replace"]},
    "project_run": {"desc": "Run a Bauplan project already present on the server filesystem.", "params": ["project_dir", "ref", "namespace", "parameters", "dry_run", "client_timeout", "detach", "strict"]},
    "revert_table": {"desc": "Restore a table on a target branch from its state at another branch, tag, or commit ref.", "params": ["table", "source_ref", "into_branch", "namespace", "replace", "commit_body"]},
    "run_query": {"desc": "Execute a read-only SQL query and return a bounded JSON result set.", "params": ["query", "ref", "namespace", "max_rows"]},
    "run_query_to_csv": {"desc": "Execute a SQL query and write scalar results to a server-local CSV file.", "params": ["path", "query", "ref", "namespace", "client_timeout"]},
}

# Real, on-demand instruction files, copied verbatim from the MCP server's
# own instructions/ directory (data/bauplan_mcp_instructions/).
_INSTRUCTIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "bauplan_mcp_instructions",
)
_USE_CASES = ("pipeline", "data", "repair", "wap", "test", "sdk")

_IMPLEMENTED = {
    "get_tables", "get_table", "run_query", "create_branch", "merge_branch",
    "get_branches", "code_run", "get_instructions", "get_jobs", "get_job",
}


class BauplanMcpMirrorAdapter(TargetAdapter):
    _SHARED_MAIN = "main"

    def __init__(self):
        self.mode = "real"  # SDK-backed, same as BauplanAdapter's real path
        self._active_branch: Optional[str] = None
        self._client = None
        # No hardcoded username — see BauplanAdapter.__init__ for the same
        # fix and why. This adapter has no mock mode, so always fail fast.
        self._username = os.getenv("BAUPLAN_USERNAME")
        if not self._username:
            raise RuntimeError(
                "BAUPLAN_USERNAME is not set. Real Bauplan runs need a real "
                "username to scope branch ownership — set it in .env."
            )

    @property
    def name(self) -> str:
        return "bauplan_mcp_mirror"

    def _real_client(self):
        if self._client is None:
            import bauplan
            self._client = bauplan.Client()
        return self._client

    def healthcheck(self) -> None:
        info = self._real_client().info()
        if not getattr(info, "user", None):
            raise RuntimeError("Bauplan MCP mirror healthcheck: no authenticated user.")

    def _require_own_branch(self, branch: str) -> None:
        prefix = f"{self._username}."
        if not branch.startswith(prefix):
            raise PermissionError(
                f"Refused: '{branch}' is not a {prefix}* branch — this mirror "
                "only operates on branches you own."
            )

    def tools(self, neutral_descriptions: bool = False) -> List[dict]:
        out = []
        for name, spec in _REAL_TOOLS.items():
            props = {p: {"type": "string", "description": f"See Bauplan MCP: {name}.{p}"} for p in spec["params"]}
            out.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": spec["desc"],
                    "parameters": {"type": "object", "properties": props},
                },
            })
        return out

    def execute_tool(self, name: str, args: dict) -> str:
        try:
            return self._execute_tool_inner(name, args)
        except Exception as e:
            # Real SDK calls (client.query, client.run, ...) raise rather
            # than return an error value. Uncaught, that crashes the whole
            # run instead of giving the agent a tool_result it can react to
            # — same bug fixed in BauplanAdapter.execute_tool, 2026-07-24.
            return json.dumps({"status": "error", "error": str(e)})

    def _execute_tool_inner(self, name: str, args: dict) -> str:
        if name not in _REAL_TOOLS:
            return json.dumps({"error": f"Unknown tool: {name}"})
        if name not in _IMPLEMENTED:
            return json.dumps({
                "error": f"'{name}' is not wired for this PoC (out of scope for the "
                         "Q3 branch/verify/merge task). Present in the schema for "
                         "honest token-cost parity with the real 31-tool MCP surface."
            })

        client = self._real_client()

        if name == "get_instructions":
            use_case = (args.get("use_case") or "").lower()
            if use_case not in _USE_CASES:
                return json.dumps({"error": f"use_case must be one of {_USE_CASES}"})
            path = os.path.join(_INSTRUCTIONS_DIR, f"{use_case}.md")
            with open(path, encoding="utf-8") as f:
                return json.dumps({"prompt": f.read()})

        elif name == "get_tables":
            ref = args.get("ref", self._active_branch or self._SHARED_MAIN)
            tables = client.get_tables(ref, filter_by_namespace=args.get("namespace"))
            return json.dumps({"tables": [t.name for t in tables]})

        elif name == "get_table":
            ref = args.get("ref", self._active_branch or self._SHARED_MAIN)
            t = client.get_table(args["table"], ref=ref, namespace=args.get("namespace"))
            return json.dumps({"table": args["table"], "schema": {f.name: str(f.type) for f in t.fields}})

        elif name == "run_query":
            ref = args.get("ref", self._active_branch or self._SHARED_MAIN)
            max_rows = args.get("max_rows", 10)
            t = client.query(args["query"], ref=ref, max_rows=max_rows)
            # default=str: see BauplanAdapter.execute_tool's bauplan_query
            # handler — date columns aren't JSON-serializable by default.
            return json.dumps({"rows": t.to_pylist()}, default=str)

        elif name == "create_branch":
            branch = args["branch"]
            self._require_own_branch(branch)
            from_ref = args.get("from_ref") or self._SHARED_MAIN
            # See BauplanAdapter for why if_not_exists=True was removed
            # (specimen: silent adoption of a pre-existing branch, 2026-07-24).
            if client.has_branch(branch):
                return json.dumps({
                    "status": "error",
                    "message": f"REFUSED: branch '{branch}' already exists. Choose a different name.",
                })
            client.create_branch(branch, from_ref=from_ref)
            self._active_branch = branch
            return json.dumps({"status": "ok", "active_branch": branch})

        elif name == "get_branches":
            branches = client.get_branches(name=args.get("name"), user=args.get("user"))
            return json.dumps({"branches": [b.name for b in branches][:20]})

        elif name == "code_run":
            import tempfile
            ref = args.get("ref") or self._active_branch
            if not ref or ref == self._SHARED_MAIN:
                return json.dumps({"status": "error", "message": f"Refused: checkout a {self._username}.* branch before code_run."})
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
                return json.dumps({"status": state.job_status, "error": state.error})

        elif name == "get_jobs":
            jobs = client.get_jobs(limit=args.get("limit", 10))
            return json.dumps({"jobs": [{"id": j.id, "kind": str(j.kind), "status": str(j.status)} for j in jobs]})

        elif name == "get_job":
            j = client.get_job(args["job_id"])
            return json.dumps({"id": j.id, "status": str(j.status)})

        elif name == "merge_branch":
            branch = args["source_ref"]
            self._require_own_branch(branch)
            into_ref = args.get("into_branch") or self._SHARED_MAIN
            if into_ref == self._SHARED_MAIN:
                return json.dumps({
                    "status": "error",
                    "message": "REFUSED: merging into 'main' is disabled for this PoC. "
                               "Merge into your own sandbox branch instead.",
                })
            self._require_own_branch(into_ref)
            try:
                commit = client.merge_branch(source_ref=branch, into_branch=into_ref,
                                              commit_message=args.get("commit_message") or "agent merge")
            except Exception as e:
                # See BauplanAdapter's merge_branch handler for why this
                # is split out from the generic exception wrapper.
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

        return json.dumps({"error": f"'{name}' listed as implemented but has no handler (adapter bug)"})

    def roles(self) -> Dict[str, SpecialistRole]:
        return {}  # monolith only, matching contract's driver: monolith

    def terminal_policy(self) -> Optional[TerminalPolicy]:
        return None

    def grader(self) -> Optional[Callable[[str], dict]]:
        return None  # set by the contract/study script for this PoC (real ground truth)

    def markers(self) -> Dict[str, Callable]:
        return {}
