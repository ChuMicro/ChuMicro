#!/usr/bin/env python3
"""Preflight: confirm the `claude` CLI the skill shells out to is present, logged in, and the RIGHT account.

The evaluation runs as a `claude -p` subprocess, which uses the `claude` CLI's OWN authentication -- not the
account of the session you launched the skill from. If you are signed into the Claude app/IDE as one account
but the `claude` CLI on PATH is logged in as another (different org, model access, subscription, billing),
the clean-room evaluation silently runs under the wrong account. This reports the CLI's logged-in account
(`claude auth status`) so a mismatch is caught up front, and `--expect-email` flags it outright when the
orchestrator passes the session's account.

It also reports the resolved CLI path, version, and OS user (config/auth live under that user's ~/.claude).

Usage: preflight.py [--expect-email <session-account-email>]   # exit 1 if missing / not logged in
       from preflight import require_claude
"""
import getpass
import json
import shutil
import subprocess
import sys


def _auth_status(path):
    """Parse `claude auth status` JSON, or return {} if unavailable (e.g. older CLI / API-key auth)."""
    try:
        r = subprocess.run([path, "auth", "status"], capture_output=True, text=True, timeout=30)
        out = (r.stdout or "").strip()
        start = out.find("{")
        return json.loads(out[start:]) if start >= 0 else {}
    except Exception:  # noqa: BLE001
        return {}


def check(expect_email=None):
    """Return (ok, info). ok is False when claude is missing, unrunnable, or not logged in."""
    path = shutil.which("claude")
    info = {"user": getpass.getuser(), "claude_path": path, "version": None,
            "logged_in": None, "email": None, "auth_method": None, "org": None,
            "subscription": None, "warnings": []}
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

    auth = _auth_status(path)
    info["logged_in"] = auth.get("loggedIn")
    info["email"] = auth.get("email")
    info["auth_method"] = auth.get("authMethod")
    info["org"] = auth.get("orgName")
    info["subscription"] = auth.get("subscriptionType")

    if info["logged_in"] is False:
        info["warnings"].append("the `claude` CLI is NOT logged in — run `claude auth login` (or set an API key) before running the skill.")
        return False, info
    if info["logged_in"] is None and not auth:
        info["warnings"].append("could not read `claude auth status` — cannot confirm the CLI's account; verify it manually.")
    if expect_email and info["email"] and info["email"].lower() != expect_email.lower():
        info["warnings"].append(
            f"ACCOUNT MISMATCH: the session runs as {expect_email}, but the `claude` CLI is logged in as "
            f"{info['email']} ({info['org']}). The clean-room `claude -p` work would run under the CLI's "
            f"account, not yours. Reconcile before running (e.g. `claude auth login` as {expect_email}).")
    return True, info


def require_claude(expect_email=None):
    """Driver guard: abort with a clear message if claude is missing / unrunnable / not logged in."""
    ok, info = check(expect_email)
    if not ok:
        sys.exit("PREFLIGHT FAILED: " + " ".join(info["warnings"]))
    return info


def main():
    expect_email = None
    if "--expect-email" in sys.argv:
        expect_email = sys.argv[sys.argv.index("--expect-email") + 1]
    ok, info = check(expect_email)
    print("=== audit-code preflight ===")
    print(f"  claude path:       {info['claude_path'] or '(not found)'}")
    print(f"  claude version:    {info['version'] or '(n/a)'}")
    print(f"  OS user:           {info['user']}")
    print(f"  CLI logged in:     {info['logged_in']}")
    print(f"  CLI account:       {info['email'] or '(unknown)'}  [{info['auth_method'] or '?'}, {info['subscription'] or '?'}]")
    print(f"  CLI org:           {info['org'] or '(unknown)'}")
    if expect_email:
        print(f"  session account:   {expect_email}")
    if info["warnings"]:
        for w in info["warnings"]:
            print(f"  WARNING: {w}")
    else:
        print("  OK: CLI present, logged in, account confirmed.")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
