#!/usr/bin/env python3
"""PostToolUse gate: an agent edit to the webui picker's renderer or validator re-runs
validate_picker.py immediately, so a structure, JS-syntax, namespace-drift, or validity
regression surfaces in the same turn as the edit instead of waiting for a hand-run.
Wired in .claude/settings.json (hooks → PostToolUse on Edit|Write|MultiEdit).

Reads the hook event JSON from stdin and exits 0 untouched for every other file. On a gate
failure the validator's findings go to stderr with exit 2, which Claude Code feeds back to
the editing agent as blocking feedback.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHED = re.compile(r"webui/(render_picker|validate_picker)\.py$")


def main():
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    file_path = (event.get("tool_input") or {}).get("file_path", "")
    if not WATCHED.search(file_path.replace(os.sep, "/")):
        sys.exit(0)
    repo_root = os.path.abspath(os.path.join(HERE, os.pardir))
    result = subprocess.run([sys.executable, os.path.join(HERE, "validate_picker.py")],
                            capture_output=True, text=True, cwd=repo_root, timeout=120)
    if result.returncode != 0:
        sys.stderr.write("validate_picker.py failed after this edit; fix before moving on:\n"
                         + result.stdout + result.stderr)
        sys.exit(2)
    print("validate_picker.py: all gates green after this edit")


if __name__ == "__main__":
    main()
