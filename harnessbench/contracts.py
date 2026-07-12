"""YAML Contract loader and validator.

Strict separation of data from execution: contracts declare the matrix
(models, cells, replications, goals, budgets) statically. The runner
loads the contract and executes the cells.
"""
import hashlib
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
            
    return study_id, contract
