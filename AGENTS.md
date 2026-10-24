# AGENTS.md — Agent Contract & Gate Map

> **Workspace Policy for `harness-bench`.** Humans and AI coding delegates share this repository.
> Every enforceable rule below is backed by a local gate or remote policy mechanism.

---

## Standard Engineering Practices (No One-Offs)

- All code, scripts, linters, and configurations must adhere to standard engineering practices.
- Do not create ad-hoc, brittle single-use scripts, custom regex parsers, or bespoke governance mechanisms where industry-standard tooling exists (e.g., use `pre-commit`, `ruff`, `gitleaks`, `pytest`, `unittest`).
- **Gate engines are immutable mechanism:** The scripts in `.gates/` are generic engines. All project-specific configuration (paths, thresholds, exclusions) must be declared in `pyproject.toml` (under `[tool.gates]`) or `.gates.toml`. Never edit the Python code in `.gates/` to change project layout or policy.

---

## 1. Local & Remote Gates

- **Local Gate (`.githooks/pre-push`):**
  - Refuses to push a dirty working tree (including untracked files).
  - Runs `pytest` on Python changes; push aborts if any test fails.
- **Remote Gate (GitHub Branch Protection):**
  - `main` is the source of truth; do not commit directly to `main`.
  - Feature work must happen on topic branches (`feat/...` or `fix/...`) via Pull Requests.

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
- **Private material stays outside the repository.** Personal notes, summaries of
  chat conversations, local machine paths, and unpublished work are never copied in, referenced by
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

---

## 2. Fresh Clone Setup

If working in a fresh clone, activate git hooks:

```bash
git config core.hooksPath .githooks
uv sync
```

---

## 3. Rules a gate now enforces

Each of these is enforced mechanically by git hooks:

- **No value is written twice.** If a value lives in a data file or contract, code reads it;
  code does not restate it. `.gates/no_hardcoding.py` compares the two after
  normalising entities, dashes, case and years, and refuses the commit.
- **No tracked file carries a credential or one machine's absolute path.**
  The `gitleaks` hook in `.pre-commit-config.yaml` runs gitleaks' default
  rules plus the home-directory rule in `.gitleaks.toml`.
- **A gate scans itself.** No gate may exempt its own directory. The escape
  valve is the `allow:` block in `FACTS.yaml`, which is a decision visible in
  the diff rather than an invisible skip-list entry.
- **Local notes live outside the worktree.** `scratch/` is a symlink to a
  directory outside the repository, and `.gates/scratch_external.py` asserts
  it. git refuses to stage through a symlink (`fatal: pathspec is beyond a
  symbolic link`).
- **A publishing surface declares its own rules.**
  `.gates/check_publish_contract.py` reads `publish_contract.toml`, where each
  surface names the file whose presence means it is in play.
- **A tracked Python file must at least parse.** The `check-ast` hook in
  `.pre-commit-config.yaml`.
- **Lint findings are defects, not style.** The `ruff-check` hook runs the
  rule set selected in `ruff.toml` (`E9`, `F`, `B`) and reports without
  editing.
- **An untested gate is theatre.** `.gates/tests/prove_gates.sh` makes each gate
  fire on a planted violation and stay quiet on a clean tree. Run it after
  touching any gate.

---

## 4. Engineering Standards

- **Declarative Configuration:** Keep all gate settings in `pyproject.toml` under `[tool.gates]`. Gate engines in `.gates/` are immutable mechanism.
- **Tests must assert content and invariants, not only shapes.**
- **Paid API tests are opt-in:** Tests that make billable provider calls are marked `paid` and run only with `pytest --run-paid`. Deterministic tests run by default in hooks and CI.

---

## 5. Documentation Triggers (When to Update README)

Do NOT update the README for internal bug fixes, refactorings, or minor code edits.
Review and update the README and agent instructions ONLY when a change crosses an external boundary:
1. **CLI / Entrypoints:** A command, CLI flag, or runner script is added, renamed, or removed.
2. **Dependencies & Toolchain:** A dependency, interpreter version, or external tool requirement is changed in `pyproject.toml`.
3. **Environment & Configuration:** A new environment variable, configuration table, or setup prerequisite is introduced.
4. **Repository Layout:** A top-level directory or primary data pipeline is added, moved, or removed.
If none of these boundaries was crossed, leave the README untouched.
