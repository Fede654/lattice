# Integration branch

`feat/integration` is the version of Lattice this fork actually runs. It is
upstream `main` plus the branches listed below, in the order given.

It is a **derived branch**. Nothing is authored here except the integration
commits at the end. Every feature is written on its own branch first, so that
each stays independently reviewable and independently upstreamable.

## Branches integrated

| Order | Branch | What it adds |
|-------|--------|--------------|
| 1 | `feat/aggregate` | `lattice aggregate` — the dashboard across every project: discovery, a project scope filter on the existing dashboard, and an All-projects board |
| 2 | `feat/completion` | `lattice completion` — shell completion for bash/zsh/fish, with callbacks for task IDs, statuses, actors, resources, sessions and relationship types |
| 3 | `fix/init-agent-file-injection` | `lattice init` stops writing `CLAUDE.md`, `agents.md` and `AGENTS.md`. `setup-claude-skill` becomes the integration path: it syncs the installed skill to the bundled one (re-run after upgrading), registers a `SessionStart` hook that announces a board when a session opens inside one, and takes `--repo` for a skill committed with the repository. `setup-claude` prints a notice pointing at the skill and is documented as legacy |
| 4 | `fix/replay-empty-collections` | replay accepts a recorded `[]` where a field was never set. Without it, boards written by 0.2.0 cannot be materialised at all — 4 task logs across this workspace were unreadable |

### Adopted from upstream, unmerged there

| Upstream branch | What it gives | Why it is here |
|---|---|---|
| `fix/lattice-review-model-pin` | pins spawned `claude` reviewers to a fixed model; `$LATTICE_REVIEW_CLAUDE_MODEL` overrides | a review fleet otherwise inherits whatever default the operator is driving that day — cost nobody chose |

### Authored here

Commits that need more than one feature to exist, so they belong to no source
branch. They are always last.

- **completion for the aggregate commands** — `complete_project_name` and the
  wiring on `lattice aggregate`. It cannot live on `feat/completion`, which
  must not reference a command that does not exist upstream, nor on
  `feat/aggregate`, which must not depend on completion.

## Upstream branches reviewed and declined

Surveyed 2026-08-21 across all 28 upstream branches. These carry unmerged work
that was considered and left out; recording the verdict stops the same survey
being repeated.

| Branch | Verdict |
|---|---|
| `feat/LAT-210-alerts-mechanism` | 24 commits, 5452 lines, 4 months stale, conflicts in `agent_spawn`. Too large and too old to carry against a moving base |
| `fix/LAT-262-auto-review` | surfacing transient auto-review failures; conflicts in `review_cmds.py` and `core/review.py`. Worth revisiting if upstream merges it |
| `feat/LAT-219-worktree-cli-routing` | a richer worktree API (`find_root(prefer_worktree=)`, a worktree init guard). Genuinely useful for worktree-heavy work, but it changes a signature both features here call |
| `feat/LAT-205-agent-spawn-primitive` | ~83% already in main; the remainder conflicts |
| `chore/mypy-relax` | relaxes `strict = true`. Declined: mypy passes strict on this branch today, so the gate is real rather than nominal |
| `chore/skill-freshness-reject-epic-spike` | small skill-doc fixes; conflicts in `worktree-guide.md` |
| `val/20260309` | a 417-line design spec with no implementation. Reference only |
| `feat/shell-completion` | our own PR #2 work, pushed to the upstream repo and left there when the PR was withdrawn. Stale even against the fork copy it came from (7 commits, pre-review). Superseded by `feat/completion`, which was rebuilt on current main. It cannot be deleted from here — it lives on `Stage-11-Agentics/lattice`, where this account has no push access |

Already squash-merged into upstream `main`, so there is nothing to take:
`LAT-186`, `LAT-211`, `LAT-220-tags-on-cards`, `LAT-263-comment-file`,
`LAT-266`, `WRK-13-utf8-windows`, `sub-agent-cadence-rule`,
`claude-runtime-gitignore`. Note `git cherry` does **not** detect these —
upstream squash-merges, so compare content, not commits.

## Rules

1. **Rebase, never merge.** `feat/integration` is rebased onto upstream
   `main`; it never merges it. History stays linear and every commit remains
   attributable to the branch it came from.
2. **No feature work here.** If a change belongs to one feature, it goes on
   that feature's branch and this branch is rebuilt. The only commits authored
   here are the ones listed above, and they are always last.
3. **Every feature branch stays independently upstreamable.** Each is based on
   upstream `main` alone, touches as little of the original as possible, and
   carries no dependency on a sibling branch.
4. **Every commit is green.** The suite passes at each commit, not merely at
   the tip, so a bisect is meaningful. Green means `pytest`, `ruff check` **and
   `mypy src/lattice/`** — mypy gates upstream CI, so a branch that fails it is
   not upstreamable.
5. **Conflicts are resolved in favour of keeping both.** The recurring one is
   command registration in `cli/main.py`, where two branches each add a line;
   the resolution is both lines, never one.
6. **Rebuilt, not patched.** When upstream moves or a feature branch changes,
   `feat/integration` is discarded and rebuilt by the recipe below. It is never
   fixed up in place — that is how a derived branch silently stops matching its
   sources.

## Rebuild

On this machine the whole cycle — fetch, rebuild, gate, push, reinstall the
tool, refresh the Claude Code skill — is `~/REPOS/scripts/lattice-upgrade.sh`
(not published; a plain directory, not a repo). The recipe below is what it
runs, kept here so the branch stays buildable without it.

```bash
git fetch origin                     # upstream: Stage-11-Agentics/lattice
git checkout -B feat/integration origin/main

git cherry-pick $(git rev-list --reverse origin/main..feat/aggregate)
# cli/main.py conflict: keep both registration lines
git cherry-pick $(git rev-list --reverse origin/main..feat/completion)
git cherry-pick $(git rev-list --reverse origin/main..fix/init-agent-file-injection)
# cli/main.py conflict: keep both registration lines
git cherry-pick $(git rev-list --reverse origin/main..fix/replay-empty-collections)

# then, in order: adopted-from-upstream commits, then authored-here commits
# (cherry-pick them from the previous integration branch, by subject)

uv run pytest -q && uv run ruff check src/ tests/ && uv run mypy src/lattice/
git push fork feat/integration --force-with-lease
```

## Adding a feature

1. Branch from `origin/main`, not from `feat/integration`.
2. Build it, with tests, keeping the diff against upstream minimal.
3. Add a row to the table above.
4. Rebuild `feat/integration`.

## Upstream

Contributions go from the **feature branch** to upstream, never from here.
`feat/integration` carries local choices upstream has not accepted and may
never accept; sending it as a pull request would mix them together.
