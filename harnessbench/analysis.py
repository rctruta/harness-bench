"""Mode-safe trace loading for analysis.

WHY THIS EXISTS
---------------
`expect_mode` (contracts.py) + `check_environment()` (api.py) already stop a
run from EXECUTING in the wrong mode. That gate works — it was added after
SBD-12, where an adapter silently defaulted to mock and burned real spend on
fabricated data, and it has held since.

It does not protect ANALYSIS. On 2026-07-30, answering a maintainer's question
about a filed issue, a query globbed `runs/**/*.jsonl`, aggregated mock and
real traces together, and produced:

    cell_1_bauplan_skills_default_r1   57 traces   0% parse errors
    cell_2_compiled_code_gates_r1      57 traces   0% parse errors
    cell_1_skills_full_r1              12 traces  50% parse errors

The conclusion drawn was "skills prevent the error." It was false. The two
57-trace cells were **entirely mock** (353 and 305 mock tool results, zero
real). A mock target cannot produce a real parse error, so their 0% carried no
information. The single real-mode cell was the only one that could exhibit the
failure at all.

The defect class is familiar: a guard that sits one layer below where the
error happens. Execution was gated; aggregation was not. The near-miss was a
wrong claim about the user's own data, about to be sent to the maintainer of
the software under test.

RULE
----
An aggregate over traces of mixed modes is meaningless and this module will
not produce one silently. Callers either restrict to one mode, or explicitly
opt in to mixing and receive the composition alongside the result.
"""
from __future__ import annotations

import glob
import json
from collections import Counter
from dataclasses import dataclass, field


class MixedModeError(RuntimeError):
    """Raised when an aggregate would span both mock and real traces."""


@dataclass
class TraceSet:
    """Traces plus the mode composition they were drawn from.

    The composition travels WITH the data, so a caller cannot report a rate
    without also having the information needed to know whether the rate means
    anything.
    """
    paths: list[str]
    modes: Counter = field(default_factory=Counter)

    @property
    def is_mixed(self) -> bool:
        return len([m for m, n in self.modes.items() if n and m]) > 1

    def describe(self) -> str:
        parts = ", ".join(f"{m or 'unlabelled'}={n}" for m, n in
                          sorted(self.modes.items(), key=lambda kv: -kv[1]))
        return f"{len(self.paths)} traces (tool_result modes: {parts or 'none'})"


def trace_mode(path: str) -> str | None:
    """The single execution mode of one trace file.

    Returns 'real', 'mock', or None when the trace records no mode at all
    (older traces predate the field). A trace containing BOTH is reported as
    'real': a run that touched the real target even once cannot be treated as
    a simulation, and the conservative direction is to over-report realness
    rather than let a real observation hide inside a mock aggregate.
    """
    seen = set()
    try:
        with open(path) as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("event") == "tool_result":
                    seen.add(rec.get("mode"))
    except OSError:
        return None
    if "real" in seen:
        return "real"
    if "mock" in seen:
        return "mock"
    return None


def load_traces(
    pattern: str,
    *,
    mode: str | None = "real",
    allow_mixed: bool = False,
    exclude_substrings: tuple[str, ...] = (),
) -> TraceSet:
    """Collect trace paths, refusing to silently mix execution modes.

    Args:
        pattern: glob, e.g. 'runs/**/*.jsonl'.
        mode: keep only traces of this mode. Defaults to 'real' — the safe
            default, because the overwhelmingly common analysis mistake is
            counting simulated runs as evidence. Pass None with
            allow_mixed=True to opt out deliberately.
        allow_mixed: permit an aggregate spanning modes. The composition is
            still attached to the result.
        exclude_substrings: drop paths containing any of these.

    Raises:
        MixedModeError: if the selection spans modes and allow_mixed is False.
    """
    paths = [
        p for p in glob.glob(pattern, recursive=True)
        if not any(s in p for s in exclude_substrings)
    ]

    by_mode: dict[str, list[str]] = {}
    composition: Counter = Counter()
    for p in paths:
        m = trace_mode(p)
        composition[m] += 1
        by_mode.setdefault(m or "unlabelled", []).append(p)

    if mode is not None:
        kept = by_mode.get(mode, [])
        return TraceSet(paths=kept, modes=Counter({mode: len(kept)}))

    distinct = [m for m in by_mode if m in ("real", "mock")]
    if len(distinct) > 1 and not allow_mixed:
        detail = ", ".join(f"{m}={len(by_mode[m])}" for m in sorted(by_mode))
        raise MixedModeError(
            f"selection spans execution modes ({detail}). A rate computed "
            f"across mock and real traces is not interpretable: a mock target "
            f"cannot exhibit a real failure, so mock traces dilute any failure "
            f"rate toward zero. Pass mode='real' (or 'mock'), or "
            f"allow_mixed=True if you genuinely intend to combine them."
        )

    return TraceSet(paths=paths, modes=composition)


def require_real(ts: TraceSet) -> TraceSet:
    """Assert a TraceSet contains only real-mode traces.

    For the final step before a number is quoted publicly. Loud by design.
    """
    bad = {m: n for m, n in ts.modes.items() if m != "real" and n}
    if bad:
        raise MixedModeError(
            f"expected real-mode traces only, found {bad}. "
            f"Do not quote a rate derived from this set."
        )
    return ts
