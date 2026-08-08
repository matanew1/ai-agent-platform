---
description: Branch, commit, PR, review+fix, merge to main, and cut a release - the full path from working-tree changes to a released version
argument-hint: "[optional: what this change is, if not obvious from the diff]"
---

Ship the current working-tree changes end to end: $ARGUMENTS

This assumes the changes are already made and (ideally) already verified
working - this command's job is landing them, not writing them. If
`!git status` and `!git diff --stat` show nothing, say so and stop.

## Workflow

1. **Branch**
   - `!git branch --show-current`
   - If on `main` (or another shared/protected branch), create a feature
     branch first: `git checkout -b <type>/<short-description>` (e.g.
     `feat/rag-reranker`, `fix/chunk-overlap`) - pick `<type>` the same
     way commit prefixes are chosen in step 2. Never commit directly to
     `main`.
   - Already on a feature branch with these changes in progress? Stay on
     it - don't create a second branch for the same change.

2. **Split into conventional commits**
   - Group the diff by *topic and type*, not into one giant commit -
     `feat`, `fix`, `docs`, `chore`, `refactor`, `test` each get their own
     commit even within the same PR. This isn't just style: it's what
     lets step 6's release generate separate Added/Fixed/Documentation
     changelog sections instead of one undifferentiated block, and what
     lets step 6 decide patch-vs-minor correctly (a `feat` commit
     anywhere in the batch usually means the release deserves
     `--release-as minor`, not the pre-1.0 default patch bump).
   - Commit header format: `type(scope): summary` - `scope` is the
     module/area touched (`tool`, `rag`, `agent`, `llm`, `logging`, ...).
     Body explains *why*, not just what - especially for a `fix`: name
     the failure mode and how it was confirmed fixed (a reproduction that
     failed before, passed after), matching the reasoning already
     expected in this repo's own commit history.
   - `git add <specific files>` per commit, not `git add -A` once - stage
     deliberately per topic.

3. **Verify before pushing**
   - `!uv run ruff format .`
   - `!uv run ruff check .`
   - `!uv run pytest -q`
   - All three clean before anything gets pushed. If something you didn't
     touch is also sitting uncommitted in the working tree, that's still
     in scope to review before it ships - see @.claude/commands/review.md
     rather than silently committing it unreviewed.

4. **Push and open a PR**
   - `!git push -u origin <branch>` (or plain `git push` if the branch
     already tracks upstream).
   - `gh pr create --base main --head <branch> --title "<summary>" --body
     "..."` - body structure: a `## Summary` bullet list (one line per
     commit/topic, not per file), a `## Testing` section naming what was
     verified and how (unit test counts, and any live/manual verification
     performed - be specific: which endpoint, which real service, what
     the actual output was, not just "tested and it works").
   - If a PR for this branch already exists, push updates to it instead
     of opening a second one - `gh pr list --head <branch>` first.

5. **Review and fix**
   - Run `/code-review medium --fix` (or the effort level the user asked
     for) across the diff before merging - every change landed this way
     so far has gone through this step, and it has found real issues
     (e.g. a timestamp formatter coupled to field order by coincidence,
     caught and fixed this way rather than after merge).
   - Re-run step 3's three checks after any fix is applied.
   - Push the fix commit(s) to the same branch/PR - don't merge findings
     silently without them landing in the PR's history.

6. **Merge**
   - `!gh pr checks <number>` - if CI is configured, wait for it green
     before merging; this repo currently has none configured, so a clean
     `mergeStateStatus` (`gh pr view <number> --json
     mergeable,mergeStateStatus`) is sufficient.
   - `gh pr merge <number> --merge --delete-branch` - a real merge commit
     (not squash), so the conventional-commit history from step 2 lands
     on `main` intact; squashing collapses exactly the separation step 2
     was for.
   - Sync local: `git checkout main && git pull --ff-only`, then
     `git branch -d <branch>` and `git fetch --prune origin` to clear the
     stale remote-tracking ref.

7. **Cut a release**
   - This is not optional or only-when-asked - every change that lands on
     `main` this way gets a version bump and changelog entry as part of
     landing it.
   - `npx --yes standard-version --dry-run` first - confirm the bump type
     and the changelog sections it's about to generate look right before
     committing to them.
   - Below `1.0.0`, a `feat` commit only bumps a **patch** by default.
     Pass `--release-as minor` when a `feat` is in the batch and the
     change is a real new capability, not just internal cleanup -
     matches what this repo has actually done at each release so far.
   - Run it for real: `npx --yes standard-version [--release-as minor]`.
   - `git push --follow-tags origin main`.
   - `.versionrc.json` already points the version bump at `pyproject.toml`
     (via `scripts/pyproject-updater.cjs` - there's no `package.json` in
     this repo) and preserves `CHANGELOG.md`'s hand-written preamble via
     its `header` field. Don't recreate either; if a release run ever
     drops the preamble, that config regressed - fix the config, not the
     generated file by hand.

8. **Final verification, on `main`, not just on the branch**
   - `!uv run ruff format --check .`
   - `!uv run ruff check .`
   - `!uv run pytest -q`
   - Confirm the version: `!grep "^version" pyproject.toml`
   - Report the PR URL, the merge commit, the new version tag, and the
     test count - state what was actually verified, not just "done."
