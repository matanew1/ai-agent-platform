#!/usr/bin/env bash
# .claude/hooks/validate.sh
#
# Wired into .claude/settings.json for two events:
#   PreToolUse  (matcher: Bash)       -> block obviously dangerous commands
#   PostToolUse (matcher: Write|Edit) -> non-blocking formatting/lint check
#
# Hook contract: Claude Code sends a JSON payload on stdin describing the
# tool call. Exit 0 = allow / no feedback. On PreToolUse, exit 2 blocks the
# tool call and feeds stderr back to Claude as the reason. On PostToolUse,
# exit 2 cannot undo the already-run tool but stderr is still surfaced to
# Claude as feedback.
set -euo pipefail

payload="$(cat)"

python3 - "$payload" <<'PYEOF'
import json
import os
import re
import subprocess
import sys

payload = json.loads(sys.argv[1])
event = payload.get("hook_event_name", "")
tool_name = payload.get("tool_name", "")
tool_input = payload.get("tool_input", {}) or {}

DANGEROUS_BASH_PATTERNS = [
    r"\brm\s+-rf\s+/(\s|$)",          # rm -rf /
    r"\brm\s+-rf\s+~(\s|$)",          # rm -rf ~
    r"\brm\s+-rf\s+\*(\s|$)",         # rm -rf *
    r"\bgit\s+push\s+.*--force\b.*\b(main|master)\b",
    r"\bgit\s+push\s+.*-f\b.*\b(main|master)\b",
    r"\bdrop\s+database\b",
    r"\bmongo(sh)?\s+.*--eval\s+.*drop",
    r":\(\)\{\s*:\|:&\s*\};:",        # fork bomb
    r"\bchmod\s+-R\s+777\s+/",
]


def block(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.exit(2)


if event == "PreToolUse" and tool_name == "Bash":
    command = tool_input.get("command", "")
    for pattern in DANGEROUS_BASH_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            block(
                "Blocked by .claude/hooks/validate.sh: command matches a "
                f"destructive pattern ({pattern!r}). If this is genuinely "
                "intended, run it manually outside Claude Code."
            )
    sys.exit(0)

if event == "PostToolUse" and tool_name in ("Write", "Edit"):
    file_path = tool_input.get("file_path", "")
    if not file_path.endswith(".py"):
        sys.exit(0)
    if not os.path.exists(file_path):
        sys.exit(0)

    # Non-blocking: surface lint issues as feedback, don't fail the build.
    try:
        result = subprocess.run(
            ["uv", "run", "ruff", "check", file_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        sys.exit(0)  # uv/ruff not available yet (e.g. fresh project) - skip silently

    if result.returncode != 0 and result.stdout.strip():
        sys.stderr.write(
            "ruff check found issues in " + file_path + ":\n" + result.stdout
        )
        # Informational only - do not block on lint issues.
    sys.exit(0)

sys.exit(0)
PYEOF
