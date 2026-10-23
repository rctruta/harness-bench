"""Opt-in gate for tests that spend money.

`test_bauplan_benchmark_run` called litellm.completion() for real against
three providers -- gemini-2.5-flash, claude-haiku-4-5 and gpt-4o-mini --
across a six-cell matrix, every time the suite ran. The Bauplan tool was
mocked; the models were not. It took 57-76 seconds, failed in the full suite
on 2026-10-22 and passed in isolation, which is what a provider rate limit
looks like. The pre-push hook runs this suite.

So a paid test is now deselected unless asked for:

    pytest                     free, deterministic, no provider touched
    pytest --run-paid          includes the tests that spend

NOT an interactive "this costs money, continue?" prompt. pytest captures
stdin, so input() raises OSError rather than waiting, and a test that waits
for a human cannot run in a hook or in CI at all. An explicit flag carries
the same intent and works everywhere.

The bargain that goes with the flag: a test allowed to spend must earn it.
`paid` tests assert on every cell they paid for, not on a lower bound.
"""
import pytest

PAID_FLAG = "--run-paid"
PAID_MARK = "paid"


def pytest_addoption(parser):
    parser.addoption(
        PAID_FLAG, action="store_true", default=False,
        help="run tests that make real, billable model calls",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        f"{PAID_MARK}: makes real billable model calls; needs {PAID_FLAG}",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption(PAID_FLAG):
        return
    skip = pytest.mark.skip(
        reason=f"spends money on live providers; run with {PAID_FLAG}")
    for item in items:
        if PAID_MARK in item.keywords:
            item.add_marker(skip)
