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

Commit on a topic branch, staging files by name:

```bash
git switch -c <type>/<topic>      # once, if not already on a topic branch
git add <file> <file>
git commit -m "fix: what changed"
```

In the **same turn** as the change. Do not push unless Ramona asks for it in
the current session; she pushes, opens and merges pull requests. See
*Publishing* below.

### Never leave state behind

`git status` at the end of your turn should be clean:

```
$ git status
nothing to commit, working tree clean
```

Untracked files are not "in progress" — they're invisible. If the file is
worth keeping, commit it. If it's not, delete it. There is no third state.

### Branches for exploratory work

Exploratory work (a broken experiment, a rewrite in progress) goes on a
named local branch. It is pushed only when Ramona asks: this repository is
public, and a pushed branch is published.

```bash
git switch -c wip/<clear-topic-name>
# ...edits...
git add <file> && git commit -m "wip: ..."
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

---

## Publishing: what an agent may and may not do

This repository is public. Anything pushed to it, including branches, commit
messages and pull-request text, can be read by anyone and stays in history.

- **Agents do not publish.** No `git push` unless the owner asks for it in the
  current session, and never to `main`. No merging pull requests, no
  force-push, no rewriting history, no changing repository settings. An agent
  works on a local branch; the owner reviews, pushes and merges.
- **Stage files by name.** Never `git add -A` or `git add .`. Before every
  commit, read `git status` and `git diff --staged` and confirm each path is
  meant to be public.
- **Private material stays outside the repository.** Personal material and
  unpublished work are never copied in, referenced by
  absolute path, or quoted in code, comments, tests, commit messages or PR
  text. Code that needs private data reads its location from an environment
  variable.
- **Commit messages and PR text are public writing.** Use a short
  Conventional Commits subject (`fix: ...`, `docs: ...`, `chore: ...`) that
  says what changed. A body, if any, explains the change technically. No
  session narrative, no account of earlier mistakes, no incident dates, no
  names of people or private documents.
- **The owner reviews before merge:** `git log -p origin/main..HEAD` and the
  PR title. Squash merges use the PR title only, so the commit on `main` says
  exactly what was reviewed.
- **Secrets:** gitleaks runs in pre-commit, and GitHub secret scanning and push
  protection are on. Fix a finding by removing the value. Do not allowlist it
  unless the owner says so.
