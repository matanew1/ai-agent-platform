---
name: git-ship
description: Prepare and ship ai-agent-platform changes with a feature branch, scoped conventional commits, review, verification, pull request, and SemVer release. Use when asked to commit, push, open a PR, merge, release, or ship backend changes.
---

# Git ship

Use this for the backend repository only. Inspect both this worktree and
`../ai-agent-platform-web` when the change affects the web client. Never
stage, commit, or discard unrelated work.

## Prepare

1. Inspect `git status --short`, `git diff --stat`, the current branch, and
   `git remote -v`. Stop if there is nothing to ship.
2. If on `main`, create one branch named
   `<type>/<short-description>` (`feat`, `fix`, `docs`, `refactor`, `test`,
   or `chore`). Reuse an existing feature branch for its in-progress change.
3. Group only related files into deliberate commits. Use
   `type(scope): imperative summary`; scopes are module/area names such as
   `chat`, `rag`, `session`, `authentication`, `docs`, or `infra`. Explain a
   non-obvious fix in the commit body. Never use `git add -A` blindly.

## Review and verify

1. Review the staged and unstaged diff with `.claude/agents/code-reviewer.md`;
   use the architect/security agent when the diff changes boundaries, auth,
   external input, MCP, or dependencies. Fix real findings before shipping.
2. Run:
   ```bash
   uv run ruff format --check .
   uv run ruff check .
   uv run pytest -q
   ```
   For a paired web change, also run `npm run build` in
   `../ai-agent-platform-web`.
3. Ask for explicit confirmation before committing, pushing, opening a PR,
   merging, or creating a release. Summarize the branch, planned commits,
   test results, and affected repositories in that confirmation.

## Publish and release

1. Push the confirmed branch and create or update one PR against `main`.
   The PR body must have concise **Summary** and **Testing** sections with
   actual commands/results.
2. Wait for every required PR check to finish green. If one fails, inspect it
   and fix the branch before merging. Do not force-push, rewrite shared
   history, or merge an unreviewed PR.
3. Merge the confirmed PR with a merge commit and delete the remote branch.
   Then switch to `main`, pull with `--ff-only`, and confirm the merge commit
   is present before releasing.
4. Run `npx standard-version --dry-run` first. Confirm the proposed version
   and changelog sections. For a genuine new capability below `1.0.0`, use
   `--release-as minor`; otherwise use the config default. Run the confirmed
   command to update `pyproject.toml`, `CHANGELOG.md`, create the release
   commit, and create its version tag.
5. Run `uv sync` after the release to update `uv.lock` if needed. Amend the
   release commit and force-move only the newly created local version tag to
   that amended commit. Re-run verification on `main`, then push `main` and
   the release tag. Report the PR URL, merge commit, version/tag, and
   verification results.
