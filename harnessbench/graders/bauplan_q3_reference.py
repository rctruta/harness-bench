"""Derive Q3 ground truth from the pipeline that defines it — never transcribed.

The published Q3 result came from
`data/bauplan_pipelines/q3_shipping_priority/models.py`. That file is the
authoritative definition of the computation: the SQL body, AND the input
filters, which live in the `bauplan.Model(...)` decorator arguments rather
than the SQL. Transcribing either into the grader is the defect class
`graders/base.py` RULE 1 exists to prevent (the grader had a hand-copied
10-row GROUND_TRUTH dict until 2026-07-27).

This module AST-parses that file and rebuilds a runnable query: table names,
column projections, filters and the aggregation all come FROM the file. Only
the CTE scaffolding that binds them is generated here, and it is mechanical
glue, not a restatement of the computation.
"""
from __future__ import annotations

import ast
import os
from typing import Dict, List, Optional

PIPELINE_MODELS_PY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "bauplan_pipelines", "q3_shipping_priority", "models.py",
)


class ReferenceExtractionError(RuntimeError):
    pass


def _const(node) -> Optional[str]:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def extract_reference(models_py: str = PIPELINE_MODELS_PY) -> Dict:
    """Returns {'sql': str, 'inputs': {alias: {table, columns, filter}}}."""
    if not os.path.exists(models_py):
        raise ReferenceExtractionError(f"pipeline source not found: {models_py}")
    tree = ast.parse(open(models_py).read())

    fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)), None)
    if fn is None:
        raise ReferenceExtractionError("no model function found in pipeline source")

    # 1. the SQL body: the `query = "..."` assignment inside the function
    sql = None
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "query":
                    sql = _const(node.value)
    if not sql:
        raise ReferenceExtractionError("no `query = \"...\"` assignment found")

    # 2. the inputs: each parameter defaulting to bauplan.Model(...)
    inputs: Dict[str, Dict] = {}
    args = fn.args.args
    defaults = fn.args.defaults
    for arg, default in zip(args[len(args) - len(defaults):], defaults,
                            strict=True):
        if not (isinstance(default, ast.Call) and getattr(default.func, "attr", None) == "Model"):
            continue
        table = _const(default.args[0]) if default.args else None
        cols: List[str] = []
        filt = None
        for kw in default.keywords:
            if kw.arg == "columns" and isinstance(kw.value, ast.List):
                cols = [c.value for c in kw.value.elts if isinstance(c, ast.Constant)]
            elif kw.arg == "filter":
                filt = _const(kw.value)
        if table:
            inputs[arg.arg] = {"table": table, "columns": cols, "filter": filt}

    if not inputs:
        raise ReferenceExtractionError("no bauplan.Model inputs found")
    return {"sql": sql, "inputs": inputs}


def build_reference_query(models_py: str = PIPELINE_MODELS_PY) -> str:
    """Compose a single query runnable against the canonical ref."""
    ref = extract_reference(models_py)
    ctes = []
    for alias, spec in ref["inputs"].items():
        cols = ", ".join(spec["columns"]) if spec["columns"] else "*"
        where = f" WHERE {spec['filter']}" if spec["filter"] else ""
        ctes.append(f"{alias} AS (SELECT {cols} FROM {spec['table']}{where})")
    return "WITH " + ",\n     ".join(ctes) + "\n" + ref["sql"]


def derive_ground_truth(client, ref: str = "main") -> Dict[int, float]:
    """Run the reference query against the source of record. {orderkey: revenue}."""
    q = build_reference_query()
    tbl = client.query(q, ref=ref)
    return {r["l_orderkey"]: round(r["revenue"], 2) for r in tbl.to_pylist()}
