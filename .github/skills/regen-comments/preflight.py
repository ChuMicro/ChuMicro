#!/usr/bin/env python3
"""Preflight: confirm the `claude` CLI the skill shells out to is present, runnable, and the right install.

Every grounding/writing/verify layer runs as a `claude -p` subprocess, so a missing or wrong `claude` on
PATH fails the whole skill with confusing errors. This reports the resolved `claude` path, its version, and
the OS user the subprocess will run as (config + auth live under that user's ~/.claude, so a mismatch — e.g.
running under sudo, or a different `claude` shadowing PATH — silently changes which account/model access is
used). `require_claude()` is called at the top of every driver; running this file prints the full report.

Usage: preflight.py            # print the report (exit 1 if claude is missing/unrunnable)
       from preflight import require_claude
"""
import getpass
import shutil
import subprocess
import sys


def check():
    """Return (ok, info_dict). ok is False only when claude is missing or `claude --version` fails."""
    path = shutil.which("claude")
    info = {"user": getpass.getuser(), "claude_path": path, "version": None, "warnings": []}
    if not path:
        info["warnings"].append("`claude` is not on PATH — the skill shells out to `claude -p` and cannot run without it.")
        return False, info
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30)
        info["version"] = (r.stdout or r.stderr).strip()
        if r.returncode != 0:
            info["warnings"].append(f"`claude --version` exited {r.returncode}: {info['version']}")
            return False, info
    except Exception as e:  # noqa: BLE001
        info["warnings"].append(f"could not run `claude --version`: {e}")
        return False, info
    return True, info


def require_claude():
    """Driver guard: abort with a clear message if claude is missing/unrunnable."""
    ok, info = check()
    if not ok:
        sys.exit("PREFLIGHT FAILED: " + " ".join(info["warnings"]))
    return info


def main():
    ok, info = check()
    print("=== regen-comments preflight ===")
    print(f"  OS user (claude runs as): {info['user']}")
    print(f"  claude path:              {info['claude_path'] or '(not found)'}")
    print(f"  claude version:           {info['version'] or '(n/a)'}")
    if info["warnings"]:
        for w in info["warnings"]:
            print(f"  WARNING: {w}")
    print("  Confirm the path + version match the session you launched the skill from (same account/auth, "
          "same model access). If not, fix PATH before running.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
