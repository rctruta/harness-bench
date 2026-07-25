"""YAML Contract loader and validator.

Strict separation of data from execution: contracts declare the matrix
(models, cells, replications, goals, budgets) statically. The runner
loads the contract and executes the cells.
"""
import hashlib
import os
import yaml


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
