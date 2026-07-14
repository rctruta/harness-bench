"""Static cost report for a skills directory.

Usage: python scripts/skill_surface_report.py <skills_dir> > report.md

Derives every number from the files themselves: per-skill token estimates
(bytes/4), the metadata-channel cost a spec-compliant host carries per turn,
pairwise description collision (Jaccard over word sets), and body redundancy
(Jaccard over 5-gram shingles). Token figures are estimates; re-derive with a
model tokenizer before publishing exact counts.
"""
import os
import re
import sys
from itertools import combinations

STOP = set("a an the and or of to for in on with is are be use when this that "
           "you your it as by from at any".split())


def parse_skill(path):
    txt = open(path, encoding="utf-8", errors="replace").read()
    m = re.search(r"^---\n(.*?)\n---", txt, re.S)
    desc = name = ""
    if m:
        dm = re.search(r"description:\s*(.+?)(?:\n\w|\n---|\Z)", m.group(1), re.S)
        nm = re.search(r"name:\s*(\S+)", m.group(1))
        desc = " ".join(dm.group(1).split()) if dm else ""
        name = nm.group(1) if nm else ""
    return txt, name, desc


def words(s):
    return {w for w in re.findall(r"[a-z']+", s.lower()) if w not in STOP}


def shingles(s, n=5):
    toks = re.findall(r"\S+", s.lower())
    return {" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a | b else 0.0


def main(root):
    skills = []
    for d in sorted(os.listdir(root)):
        sk = os.path.join(root, d, "SKILL.md")
        if not os.path.isfile(sk):
            continue
        txt, name, desc = parse_skill(sk)
        extra_files = sum(len(fns) for _, _, fns in os.walk(os.path.join(root, d))) - 1
        skills.append({
            "dir": d, "name": name or d, "desc": desc,
            "body_tok": len(txt) // 4, "desc_tok": len(desc) // 4,
            "extra_files": extra_files,
            "words": words(desc), "shingles": shingles(txt),
        })

    total_body = sum(s["body_tok"] for s in skills)
    meta_cost = sum(s["desc_tok"] + len(s["name"]) // 4 for s in skills)

    print(f"# Static skill-surface report: `{os.path.abspath(root)}`\n")
    print(f"- **Skills:** {len(skills)}")
    print(f"- **Total body size:** ~{total_body:,} tokens (bytes/4 estimate)")
    print(f"- **Metadata channel (name+description, what a lazy-loading host "
          f"carries every turn):** ~{meta_cost:,} tokens")
    print(f"- **Always-loaded worst case (all bodies in prompt):** "
          f"~{total_body:,} tokens/turn\n")

    print("## Per-skill inventory\n")
    print("| skill | ~body tokens | ~desc tokens | extra files |")
    print("|---|---|---|---|")
    for s in sorted(skills, key=lambda s: -s["body_tok"]):
        print(f"| {s['name']} | {s['body_tok']:,} | {s['desc_tok']} | {s['extra_files']} |")

    print("\n## Description collision (top pairs, Jaccard over content words)\n")
    print("High overlap means description-based routing must distinguish "
          "near-identical triggers.\n")
    print("| pair | Jaccard |")
    print("|---|---|")
    pairs = sorted(((jaccard(a["words"], b["words"]), a["name"], b["name"])
                    for a, b in combinations(skills, 2)), reverse=True)
    for j, a, b in pairs[:12]:
        print(f"| {a} ↔ {b} | {j:.2f} |")

    print("\n## Body redundancy (top pairs, Jaccard over 5-gram shingles)\n")
    print("| pair | Jaccard |")
    print("|---|---|")
    bpairs = sorted(((jaccard(a["shingles"], b["shingles"]), a["name"], b["name"])
                     for a, b in combinations(skills, 2)), reverse=True)
    for j, a, b in bpairs[:12]:
        print(f"| {a} ↔ {b} | {j:.2f} |")

    prevention = [s for s in skills if re.search(
        r"gotcha|pitfall|avoid|mistake|never|don't", s["dir"] + " " + s["desc"], re.I)]
    print("\n## Prevention-class skills (guidance that must act BEFORE the error)\n")
    for s in prevention:
        print(f"- **{s['name']}** (~{s['body_tok']:,} tok): {s['desc'][:120]}")
    ptok = sum(s["body_tok"] for s in prevention)
    print(f"\n{len(prevention)} skills, ~{ptok:,} tokens. Delivered on-demand "
          f"(MCP prompts), these are consulted only after the mistake they exist "
          f"to prevent — the delivery channel inverts their purpose.")


if __name__ == "__main__":
    main(sys.argv[1])
