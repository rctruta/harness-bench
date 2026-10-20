"""Baseline vs gated: does mechanical tool gating change outcomes?

MEASURED from the 2026-07-15 MotherDuck pilot: 3 tasks x 4 models x 2 cells.
Ground truth derived live from the seeded DB, not recalled.
"""
import json, glob, os, re, collections

# Ground truth is READ from the file the seed script emits — never
# reconstructed here. A previous version hand-wrote these queries and got the
# top-region one wrong (spurious join), scoring 8 correct answers as failures.
_GT_PATH = "data/motherduck_study_ground_truth.json"
if not os.path.exists(_GT_PATH):
    raise SystemExit(f"missing {_GT_PATH} — run scripts/make_motherduck_study_db.py first")
_gt_raw = json.load(open(_GT_PATH))
GT = {k: (tuple(v["value"]) if isinstance(v["value"], list) else v["value"])
      for k, v in _gt_raw.items()}
print("ground truth (read from disk, not reconstructed):")
for k, v in GT.items():
    print(f"  {k}: {v}   <- {_gt_raw[k]['query'][:70]}")
print()

def num_in(text):
    """All numbers in the final answer, normalised (commas/$ stripped)."""
    t = (text or "").replace(",", "").replace("$", "")
    return [float(x) for x in re.findall(r"\d+\.?\d*", t)]

def correct(task, final):
    if final is None: return False
    nums = num_in(final)
    if task == "md_top_region":
        region, val = GT[task]
        return region.lower() in (final or "").lower() and any(abs(n-val) < 0.05 for n in nums)
    target = GT[task]
    return any(abs(n - target) < 0.05 for n in nums)

rows = []
for d in sorted(glob.glob("runs/motherduck-study/*/md_*")):
    task = os.path.basename(d)
    for f in sorted(glob.glob(f"{d}/trace_*.jsonl")):
        b = os.path.basename(f)
        cell = "gated" if "_gated_" in b else "baseline"
        model = b.split("trace_")[1].split(f"_{cell}_")[0]
        ev = [json.loads(l) for l in open(f)]
        turns = sum(1 for e in ev if e.get("event") == "model_response")
        calls = sum(1 for e in ev if e.get("event") == "tool_call")
        tok = 0
        for e in ev:
            if e.get("event") == "model_response":
                u = e.get("usage") or {}
                tok += (u.get("prompt_tokens", 0) or 0) + (u.get("completion_tokens", 0) or 0)
        refusals = sum(1 for e in ev if e.get("event") == "tool_result"
                       and "REFUSED by gate" in str(e.get("result") or ""))
        end = next((e for e in ev if e.get("event") == "run_end"), {})
        fa = next((e for e in reversed(ev) if e.get("event") == "final_answer"), None)
        final = fa.get("content") if fa else None
        # unprompted adoption of typed discovery tools (baseline question in the contract)
        used_typed = any(e.get("event") == "tool_call" and e.get("name") in ("list_tables","list_columns") for e in ev)
        rows.append(dict(task=task, model=model, cell=cell, turns=turns, calls=calls,
                         tokens=tok, refusals=refusals, outcome=end.get("outcome"),
                         correct=correct(task, final), typed=used_typed))

hdr = f"{'task':<18}{'model':<22}{'cell':<10}{'ok':<4}{'turns':>6}{'calls':>6}{'tok':>8}{'refus':>6}  {'outcome'}"
print(hdr); print("-"*len(hdr))
for r in sorted(rows, key=lambda r:(r['task'], r['model'], r['cell'])):
    print(f"{r['task']:<18}{r['model'][:21]:<22}{r['cell']:<10}"
          f"{'Y' if r['correct'] else '.':<4}{r['turns']:>6}{r['calls']:>6}{r['tokens']:>8}{r['refusals']:>6}  {r['outcome']}")

print("\n=== AGGREGATE by cell ===")
agg = collections.defaultdict(list)
for r in rows: agg[r["cell"]].append(r)
print(f"{'cell':<10}{'correct':>10}{'mean turns':>12}{'mean calls':>12}{'mean tokens':>13}{'refusals':>10}")
for cell in ("baseline","gated"):
    v = agg[cell]; n=len(v)
    print(f"{cell:<10}{sum(r['correct'] for r in v)}/{n:<8}"
          f"{sum(r['turns'] for r in v)/n:>12.1f}{sum(r['calls'] for r in v)/n:>12.1f}"
          f"{sum(r['tokens'] for r in v)/n:>13,.0f}{sum(r['refusals'] for r in v):>10}")

print("\n=== PAIRED by (task, model): baseline -> gated ===")
pairs = collections.defaultdict(dict)
for r in rows: pairs[(r['task'], r['model'])][r['cell']] = r
flips = collections.Counter()
for k, p in sorted(pairs.items()):
    if len(p) != 2: continue
    b, g = p['baseline'], p['gated']
    flip = ('Y' if b['correct'] else '.') + '->' + ('Y' if g['correct'] else '.')
    flips[flip] += 1
    print(f"  {k[0]:<18}{k[1][:21]:<22} {flip}   turns {b['turns']}->{g['turns']}  "
          f"tok {b['tokens']:,}->{g['tokens']:,}  refusals={g['refusals']}")
print("\n  flip summary:", dict(flips))

print("\n=== unprompted use of typed discovery tools (baseline cells only) ===")
for r in sorted([r for r in rows if r['cell']=='baseline'], key=lambda r:(r['task'],r['model'])):
    print(f"  {r['task']:<18}{r['model'][:21]:<22} typed_tools={'YES' if r['typed'] else 'no'}")
