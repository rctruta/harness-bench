# AGENTS.md

Shared contract for every agent that touches this repo (Claude Code, Gemini
in-IDE, and any future agent). Ramona is the human owner; agents are
delegates. This file exists because multiple agents work on the same repo
concurrently and one uncommitted file can invisibly diverge the world.

Both agents read this file every session. Follow it — the alternative is
the "different versions everywhere" state that produced this document.

---

## The one rule: main is the truth

`origin/main` is the only source of truth. Local state — untracked files,
uncommitted edits, half-finished experiments — is not shared with the other
agent until it lands on main. Any state that lives only on your local
machine is invisible to your counterpart.

### At the start of every turn that will modify files

```bash
git pull origin main
```

If you started a turn without pulling, and you're about to write code, pull
first. This costs nothing when everything is up to date.

### At the end of every turn that created or modified files

```bash
git add -A
git commit -m "clear message"
git push origin main
```

In the **same turn** as the change — not "later," not "when I'm done for the
day." Every user-facing response that ships modified files ends with the
push.

### Never leave state behind

`git status` at the end of your turn should be clean:

```
$ git status
nothing to commit, working tree clean
```

Untracked files are not "in progress" — they're invisible. If the file is
worth keeping, commit it. If it's not, delete it. There is no third state.

### Branches for exploratory work

If a change is exploratory and shouldn't hit `main` (e.g., a broken
experiment WIP, a rewrite you're mid-thinking), work on a named branch and
push there. The rule still applies: the branch must exist on `origin`,
not just locally.

```bash
git switch -c wip/<clear-topic-name>
# ...edits...
git add -A && git commit -m "..." && git push -u origin wip/<clear-topic-name>
```

---

## One-time setup on each checkout

The repo ships a `pre-push` hook that refuses to push while the working
tree is dirty. Enable it once per checkout:

```bash
git config core.hooksPath .githooks
```

Do this in every worktree / clone. It replaces GitHub-side CI as the
enforcement point for the sync discipline (CI can't see uncommitted files;
this hook can).

If the hook refuses your push with `working tree has uncommitted or
untracked files`, that's the enforcement working. Commit or discard the
loose files, then push again.
