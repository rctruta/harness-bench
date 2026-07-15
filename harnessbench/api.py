"""Core API for Harness Bench.

This module exposes the unified logic for the CLI and MCP dual-interfaces.
"""
import litellm
import os
from datetime import datetime
from harnessbench.registry import load_adapter
from harnessbench.contracts import load_contract
from harnessbench.runner.orchestrator import Orchestrator
from harnessbench.runner.monolith import MonolithDriver


def _check_ollama_model(model_name: str) -> tuple[bool, str]:
    """Check if an ollama model is actually pulled locally."""
    import urllib.request
    import json
    
    base_model = model_name.replace("ollama/", "")
    
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode('utf-8'))
            models = [m["name"] for m in data.get("models", [])]
            
            # Ollama lists models with their tags (e.g., 'phi3:latest')
            if base_model not in models and f"{base_model}:latest" not in models:
                return False, f"Model '{base_model}' is not pulled in local Ollama. Run `ollama pull {base_model}`"
            return True, ""
    except Exception as e:
        return False, f"Failed to connect to local Ollama on port 11434: {e}"


def check_environment(contract_path: str, target_name: str) -> dict:
    """Pre-flight check: validates API keys and target health."""
    try:
        study_id, contract = load_contract(contract_path)
    except Exception as e:
        return {"status": "error", "message": f"Failed to load contract: {e}"}

    models = contract.get("models", [])
    if not models:
        return {"status": "error", "message": "Contract has no models defined."}

    # 1. Validate Target Health
    try:
        adapter = load_adapter(target_name)
    except Exception as e:
        return {"status": "error", "message": f"Failed to load adapter '{target_name}': {e}"}

    try:
        adapter.healthcheck()
    except Exception as e:
        return {
            "status": "error",
            "message": f"Target '{target_name}' failed healthcheck: {e}"
        }

    # 2. Validate API Keys via litellm
    for model in models:
        try:
            litellm.validate_environment(model=model)
            
            if model.startswith("ollama/"):
                ok, err = _check_ollama_model(model)
                if not ok:
                    return {"status": "error", "message": err}
        except Exception as e:
            return {
                "status": "error",
                "message": f"Missing required environment variable for model '{model}'. Details: {e}"
            }

    return {"status": "ok", "message": "Environment is ready. Keys and Target are healthy."}


def slugify(text: str) -> str:
    import re
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:30]


def get_target_slug(target_name: str) -> str:
    """Extract a safe folder name from complex target strings."""
    if target_name.startswith("mcp:stdio:"):
        cmd_str = target_name[len("mcp:stdio:"):]
        import shlex
        parts = shlex.split(cmd_str)
        for part in parts:
            if part not in ("uvx", "npx", "python", "-m"):
                return slugify(part)
        return slugify(parts[0])
    return slugify(target_name)


def run_benchmark(contract_path: str, target_name: str, dry_run: bool = False,
                  alias: str = None) -> dict:
    """Runs a study contract against a specific target.

    `alias` names the runs/ subdirectory; it defaults to a slug derived from
    the target string, which is a connection detail, not a name — prefer an
    explicit alias (e.g. 'malloy-publisher').
    """
    check_res = check_environment(contract_path, target_name)
    if check_res["status"] != "ok":
        raise RuntimeError(f"Pre-flight check failed: {check_res['message']}")

    study_id, contract = load_contract(contract_path)
    adapter = load_adapter(target_name)

    study_name = os.path.splitext(os.path.basename(contract_path))[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_slug = slugify(alias) if alias else get_target_slug(target_name)
    
    base_runs_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runs"))
    # New structure: runs/{target_slug}/{timestamp}_{study_id}/{study_name}
    runs_dir = os.path.join(base_runs_dir, target_slug, f"{timestamp}_{study_id}", study_name)
    os.makedirs(runs_dir, exist_ok=True)
    
    import shutil
    import json
    
    shutil.copy(contract_path, os.path.join(runs_dir, "contract.yaml"))
    
    meta = {
        "target": target_name,
        "study_id": study_id,
        "study_name": study_name,
        "timestamp": timestamp,
        "models": contract["models"],
        "cells": list(contract["cells"].keys()),
        "replications": contract["replications"],
    }
    with open(os.path.join(runs_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    os.environ["AGENT_STUDY_DIR"] = runs_dir

    cells = list(contract["cells"])
    models = contract["models"]
    reps = int(contract["replications"])

    if dry_run:
        return {
            "status": "dry_run",
            "study_id": study_id,
            "matrix_size": len(models) * len(cells) * reps,
            "models": models
        }

    outcomes = {}
    for model in models:
        for cell in cells:
            for rep in range(1, reps + 1):
                model_slug = slugify(model)
                os.environ["AGENT_TRACE_PREFIX"] = f"trace_{model_slug}_{cell}_r{rep}"
                
                flags = (contract["cells"].get(cell) or {}).get("flags", {}) if isinstance(contract["cells"], dict) else {}
                system_preamble = None
                inject = flags.get("inject_prompts")
                inject_files = flags.get("inject_files")
                if inject:
                    if not hasattr(adapter, "get_prompt"):
                        raise RuntimeError(
                            f"cell '{cell}' sets inject_prompts but adapter "
                            f"'{adapter.name}' has no prompts channel")
                    bodies = [f"## Skill: {p}\n\n{adapter.get_prompt(p)}" for p in inject]
                elif inject_files:
                    bodies = []
                    for p in inject_files:
                        with open(p, encoding="utf-8") as fh:
                            bodies.append(fh.read())
                if inject or inject_files:
                    system_preamble = (
                        "The following skill guidance applies to this task.\n\n"
                        + "\n\n---\n\n".join(bodies))

                from harnessbench.hooks import build_hooks
                cell_hooks = build_hooks(flags.get("hooks"))

                try:
                    if adapter.roles():
                        driver = Orchestrator(
                            adapter=adapter,
                            goal=contract["goal"],
                            model=model,
                            poll_budget_seconds=float(contract.get("poll_budget_seconds", 180)),
                            runs_dir=runs_dir
                        )
                        architecture = "orchestrator"
                    else:
                        driver = MonolithDriver(
                            adapter=adapter,
                            goal=contract["goal"],
                            model=model,
                            runs_dir=runs_dir,
                            system_preamble=system_preamble,
                            hooks=cell_hooks
                        )
                        architecture = "monolith"

                    study_stamp = {"study_id": study_id, "cell": cell, "rep": rep, "study_model": model,
                                   "inject_prompts": inject or [],
                                   "hooks": flags.get("hooks") or []}
                    driver.trace.prompt_provenance(components={}, ablation_flags={
                        "architecture": architecture, **study_stamp})
                    
                    result = driver.run()
                    outcomes[f"{model}_{cell}_{rep}"] = result.outcome
                except Exception as e:
                    outcomes[f"{model}_{cell}_{rep}"] = f"exception: {e}"

    return {
        "status": "complete",
        "study_id": study_id,
        "runs_dir": runs_dir,
        "outcomes": outcomes
    }
