"""YAML Contract loader and validator.

Strict separation of data from execution: contracts declare the matrix
(models, cells, replications, goals, budgets) statically. The runner
loads the contract and executes the cells.
"""
import hashlib
import os
import re
import yaml


# Matches a goal that tells the agent to write results INTO one named
# destination. Deliberately narrow: it requires an explicit write verb AND
# a quoted literal destination, so ordinary goal prose (source tables,
# namespaces, expected values) does not trip it.
_WRITE_TARGET_RE = re.compile(
    r"\b(?:merge|publish|write|commit|push|save|materiali[sz]e)\b[^.\n]{0,80}?"
    r"\binto\b\s*[`'\"]([A-Za-z0-9][\w.\-/]{2,})[`'\"]",
    re.IGNORECASE,
)


def find_pinned_write_target(goal: str):
    """The single literal destination a goal pins, if any. Public so tests
    and callers can check a goal without loading a whole contract."""
    m = _WRITE_TARGET_RE.search(goal or "")
    return m.group(1) if m else None


def load_contract(path: str) -> tuple:
    """Returns (study_id, contract_dict). study_id is content-addressed
    from the file's exact bytes."""
    with open(path, "rb") as f:
        raw = f.read()
    study_id = hashlib.sha256(raw).hexdigest()[:8]
    contract = yaml.safe_load(raw)

    for key in ("driver", "replications", "goal", "cells"):
        if key not in contract:
            raise ValueError(f"study contract missing required key: '{key}'")

    # Optional: a contract can declare the execution mode it requires. If set,
    # check_environment() (api.py) refuses to start unless the constructed
    # adapter's .mode matches — BEFORE any run/spend. Added 2026-07-23 after
    # a real incident: an adapter silently defaulted to mock mode for a
    # 'real' experiment and burned real spend on fabricated data before
    # anyone noticed (specimen SBD-12). Adapters without a .mode attribute
    # (most of them — mode is only meaningful for targets with a real/mock
    # distinction) are exempt; this only fires when both sides declare an
    # opinion.
    if "expect_mode" in contract and contract["expect_mode"] not in ("real", "mock"):
        raise ValueError(f"'expect_mode' must be 'real' or 'mock', got {contract['expect_mode']!r}")

    # Per-replication write isolation (specimen SBD-14). A contract with
    # replications > 1 whose goal pins ONE literal write destination makes
    # every replication write to the same place. Independent agents
    # converge on predictable output names, so replication 2+ collides
    # with replication 1's artifacts — and the platform is right to
    # object. Real incident 2026-07-24: 24 replications across three
    # batches all merged into one branch; reps 2+ hit genuine
    # MERGE_CONFLICTs and a paid 6-run batch could not answer the question
    # it was run for. Refusing loudly rather than auto-deriving a
    # per-rep name: silently rewriting the goal text an agent is given
    # would be exactly the kind of invisible fallback this harness exists
    # to catch. Set 'allow_shared_write_target: true' when replications
    # are genuinely meant to share one destination.
    if int(contract.get("replications", 1)) > 1 and not contract.get("allow_shared_write_target"):
        pinned = find_pinned_write_target(contract.get("goal", ""))
        if pinned:
            raise ValueError(
                f"contract sets replications={contract['replications']} but its goal pins a "
                f"single write target {pinned!r}. Every replication would write to the same "
                f"destination, so replications after the first collide with their own "
                f"predecessors' artifacts and measure the collision, not the thing under test "
                f"(specimen SBD-14). Fix: give each replication its own destination (e.g. "
                f"'{pinned}-r1', '{pinned}-r2', ...) by running one contract per replication, "
                f"or let the agent choose its own target name. If replications are genuinely "
                f"meant to share one destination, set 'allow_shared_write_target: true'."
            )

    if "models" in contract:
        if not isinstance(contract["models"], list) or not contract["models"]:
            raise ValueError("'models' must be a non-empty list")
    elif "model" in contract:
        contract["models"] = [contract["model"]]
    else:
        raise ValueError("study contract missing required key: 'model' (or 'models')")

    for cell_name, cell in contract["cells"].items():
        if "flags" not in cell:
            raise ValueError(f"cell '{cell_name}' missing 'flags'")

        # Fail at load time, not mid-study: run_benchmark() (api.py) opens
        # inject_files paths verbatim, relative to the CWD the CLI is run
        # from — this check uses the identical resolution so a pass here
        # guarantees the runtime open() will not raise FileNotFoundError
        # partway through a (possibly paid) run.
        inject_files = (cell.get("flags") or {}).get("inject_files") or []
        missing = [p for p in inject_files if not os.path.exists(p)]
        if missing:
            raise ValueError(
                f"cell '{cell_name}' references inject_files that do not "
                f"exist (resolved relative to CWD): {missing}"
            )

    return study_id, contract
