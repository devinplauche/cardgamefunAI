# Agent Isolation and Integration Rules

These rules apply to every coding or research agent working in this repository.

## Workspace isolation

- Do not edit the primary checkout when another agent may be active.
- Work in a dedicated Git worktree and branch. Worktrees should live beside the
  repository, for example `..\cardgamefunAI-worktrees\<agent-name>`.
- Start from an explicit base commit or branch; do not silently rebase onto a
  moving working tree.
- Before changing files, verify the worktree with `git status --short` and
  `git branch --show-current`.
- Never use `git reset --hard`, `git checkout --`, or broad deletion commands
  to discard someone else's work.

Example setup:

```powershell
git fetch origin
git worktree add -b codex/<task-name> `
  ..\cardgamefunAI-worktrees\<task-name> origin/main
```

## Task boundaries

- Each agent receives one bounded task and an explicit file scope.
- Do not modify files outside that scope without reporting the reason first.
- Avoid concurrent edits to the same file. Split work by module or use a
  read-only review agent before assigning an implementation agent.
- Keep generated logs, benchmarks, caches, and temporary artifacts in the
  agent's worktree or outside the repository. Do not add untracked experiment
  output to the shared checkout.
- Do not change production defaults merely to run an experiment. Use a flag,
  configuration override, or a temporary experiment branch.

## Changes and commits

- A completed agent task must end in one or more focused commits. Do not leave
  edits in a shared worktree for another agent to discover.
- Commit only files belonging to the task; inspect `git diff --check` first.
- Report the commit hash, changed files, tests run, benchmark seeds, and any
  unresolved assumptions.
- The integration owner cherry-picks approved commits into the target branch.
  Agents must not merge, rebase, or force-push the integration branch.

## Verification requirements

At minimum, run the focused tests for the changed module. For bot or engine
changes, also run:

```powershell
python -m py_compile <changed-python-files>
python -m unittest discover -s tests -p "test*.py"
git diff --check
```

Performance changes must be evaluated against the committed control using the
same seat, budget, algorithms, and profiles. Use multiple independent seed
blocks; never promote a change from one lucky seed or a small unpaired sample.
Record both per-block and aggregate results. A candidate that regresses any
profile remains an experiment until the regression is explained and resolved.

## Integration protocol

Only the integration owner may modify the shared target checkout:

1. Inspect the agent commit and diff.
2. Cherry-pick it onto the target branch.
3. Run the full tests and the frozen multi-seed benchmark.
4. Compare against the pre-change control.
5. Keep or revert the whole commit; do not hand-edit around an unexplained
   regression.

Use `git worktree list` to audit active worktrees and remove an agent worktree
only after its branch and commit have been preserved:

```powershell
git worktree remove ..\cardgamefunAI-worktrees\<task-name>
```

Preserve user changes, unrelated agent branches, and untracked files unless the
owner explicitly authorizes their removal.
