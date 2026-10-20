"""Tests for the generic harness engine using the FakeAdapter."""
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from harnessbench.runner.orchestrator import Orchestrator
from harnessbench.runner.specialist import run_specialist, SpecialistResult
from harnessbench.tests.fake_adapter import FakeAdapter
from harnessbench import trace


@pytest.fixture(autouse=True)
def _isolate_trace_dir(tmp_path, monkeypatch):
    """Every test gets its own trace dir."""
    monkeypatch.setenv("AGENT_STUDY_DIR", str(tmp_path))
    monkeypatch.setenv("AGENT_TRACE_PREFIX", "test_trace")


def _mock_llm_response(content: str = "", tool_calls=None, usage=None):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    return resp


def test_orchestrator_short_circuits_on_config_builder_failure():
    """If config_builder fails, poll + analyzer must not run."""
    adapter = FakeAdapter()
    from harnessbench.runner import orchestrator
    with patch.object(orchestrator, "run_specialist") as mock_run_spec:
        mock_run_spec.side_effect = [
            SpecialistResult(role="librarian", outcome="ok",
                             output={"build": "not in corpus"},
                             sub_run_id="lib-run", turns_used=2),
            SpecialistResult(role="config_builder", outcome="gave_up", output=None,
                             sub_run_id="cb-run", turns_used=15, error="stuck"),
        ]
        result = Orchestrator(adapter=adapter, goal="test", model="test/model").run()

    assert result.outcome == "config_builder_failed"
    assert result.experiment_id is None
    assert mock_run_spec.call_count == 2


def test_orchestrator_happy_path():
    adapter = FakeAdapter()
    from harnessbench.runner import orchestrator
    with patch.object(orchestrator, "run_specialist") as mock_run_spec:
        mock_run_spec.side_effect = [
            SpecialistResult(role="librarian", outcome="ok",
                             output={"build": "not in corpus"},
                             sub_run_id="lib", turns_used=2),
            SpecialistResult(role="config_builder", outcome="ok",
                             output={"experiment_id": "aabb0002"},
                             sub_run_id="cb", turns_used=5),
            SpecialistResult(role="analyzer", outcome="ok",
                             output={"analysis": "FINAL ANSWER: DuckDB wins"},
                             sub_run_id="an", turns_used=3),
        ]
        result = Orchestrator(adapter=adapter, goal="test goal", model="test/model").run()

    assert result.outcome == "complete"
    assert result.experiment_id == "aabb0002"
    assert result.analysis == "FINAL ANSWER: DuckDB wins"


def test_api_directory_structure(tmp_path, monkeypatch):
    """Verify that runs_dir uses a clean slug and follows the hierarchical convention."""
    from harnessbench import api
    monkeypatch.setattr(api, "check_environment", lambda c, t: {"status": "ok"})
    
    # Mock load_adapter to return a fake adapter
    adapter = FakeAdapter()
    monkeypatch.setattr(api, "load_adapter", lambda t: adapter)
    
    # Write a dummy contract
    contract_path = tmp_path / "test_study.yaml"
    contract_path.write_text("goal: test\nmodels: ['m1']\ncells: {'base': {}}\nreplications: 1")
    
    # Mock datetime to control the timestamp
    class MockDatetime:
        @classmethod
        def now(cls):
            from datetime import datetime
            return datetime(2026, 7, 12, 12, 0, 0)
    monkeypatch.setattr(api, "datetime", MockDatetime)
    
    # Mock load_contract to return a fixed study_id
    monkeypatch.setattr(api, "load_contract", lambda p: ("abcd1234", {"models": ["m1"], "cells": {"base": {}}, "replications": 1, "goal": "test"}))
    
    # Mock the MonolithDriver to do nothing but return a result
    class DummyDriver:
        def __init__(self, *args, **kwargs):
            self.trace = MagicMock()
        def run(self):
            return MagicMock(outcome="complete")
    monkeypatch.setattr(api, "MonolithDriver", DummyDriver)
    
    # Target string with spaces and slashes
    target_string = "mcp:stdio:uvx mcp-server-motherduck --db-path /some/path/db.duckdb"
    
    # Run the benchmark
    res = api.run_benchmark(str(contract_path), target_string)
    
    runs_dir = res["runs_dir"]
    
    # The target_slug should extract 'mcp-server-motherduck'
    assert "mcp-server-motherduck" in runs_dir
    # It should not contain absolute paths or slashes from the arguments
    assert "--db-path" not in runs_dir
    assert "/some/path" not in runs_dir
    
    # The structure must be runs/{target_slug}/{timestamp}_{study_id}/{study_name}
    parts = runs_dir.split(os.sep)
    assert parts[-1] == "test_study"
    assert parts[-2] == "20260712_120000_abcd1234"
    assert parts[-3] == "mcp-server-motherduck"


def test_hooks_gate_refusal_and_allow():
    from harnessbench.hooks import build_hooks, HookState
    hooks = build_hooks([
        {"require_before": {"tool": "submit", "requires": "get_template"}},
        {"max_calls": {"tool": "list_suites", "limit": 1}},
    ])
    state = HookState()

    # submit before get_template -> refused by the gate
    refusals = [h("submit", {}, state) for h in hooks]
    assert any(r and "require_before" in r for r in refusals)

    # after get_template succeeds, submit passes every hook
    state.record_success("get_template")
    assert all(h("submit", {}, state) is None for h in hooks)

    # second list_suites call is refused by max_calls
    assert all(h("list_suites", {}, state) is None for h in hooks)
    state.record_call("list_suites")
    assert any(h("list_suites", {}, state) for h in hooks)


def test_build_hooks_rejects_unknown_kind():
    from harnessbench.hooks import build_hooks
    import pytest
    with pytest.raises(ValueError):
        build_hooks([{"telepathy": {}}])
