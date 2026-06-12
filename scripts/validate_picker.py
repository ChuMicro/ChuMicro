"""Gate the shared picker tool (`.github/skills/_shared/picker/`) from `scripts/run.py`.

A PostToolUse hook re-runs the static validator on every agent edit to the picker, but an edit
made outside an agent session — a hand patch, a merge, a rebase — slips past that hook. This
task is the catch-all gate for those: it runs the same checks the hook does, plus the headless
behavior smoke, so a regression in the picker's HTML, CSS, JS namespaces, or live JS contract
surfaces in preflight rather than in a session that renders a broken page.

Two children run in order against one rendered fixture:

  1. validate_picker.py  — static gates (render, structure, js, drift, vnu). vnu and the node js
     gate skip loudly when their binary is missing; the pure-Python gates always run.
  2. validate_picker_smoke.py — drives the rendered page in headless chromium and asserts the
     live JS contract. Skips loudly (exit 3) when playwright or chromium is absent, so a fresh
     checkout without those heavy host-only deps does not fail the gate.

The task is non-interactive: it prints one transcript and returns a distinct exit code per
failure mode (workbench CLI convention). It never prompts.

Exit codes:
  0  every gate passed (smoke skips are reported but not fatal);
  1  a static gate failed (validate_picker.py found a real violation);
  2  the behavior smoke failed (the live JS contract broke);
  3  the picker tool is missing or a child crashed unexpectedly (usage / environment error).
"""

from __future__ import annotations

import sys

from repo_layout import ROOT
from shared import run_command

PICKER_DIR = ROOT / ".github" / "skills" / "_shared" / "picker"
VALIDATOR = PICKER_DIR / "validate_picker.py"
SMOKE = PICKER_DIR / "validate_picker_smoke.py"

# validate_picker_smoke.py's own loud-skip exit (playwright or chromium absent). Distinct from
# its FAIL exit (2) so a missing browser binary never reads as a broken JS contract.
SMOKE_SKIP_EXIT = 3


def validate_picker() -> int:
    """Run the static picker validator then the behavior smoke; return a distinct exit code.

    A static-gate failure (1) preempts the smoke — a page that fails its markup or namespace
    checks is not worth driving in a browser. A smoke skip (the deps are absent) is printed and
    treated as non-fatal; a smoke failure (2) means the live JS contract broke.
    """
    if not VALIDATOR.exists() or not SMOKE.exists():
        print(f"validate-picker: picker tool not found under {PICKER_DIR}", flush=True)
        return 3

    print("=== picker static gates (validate_picker.py) ===", flush=True)
    static_code = run_command([sys.executable, str(VALIDATOR)])
    if static_code != 0:
        print(f"validate-picker: static gates failed (exit {static_code})", flush=True)
        return 1

    print("\n=== picker behavior smoke (validate_picker_smoke.py) ===", flush=True)
    smoke_code = run_command([sys.executable, str(SMOKE)])
    if smoke_code == SMOKE_SKIP_EXIT:
        print("validate-picker: behavior smoke skipped (playwright/chromium absent) — "
              "static gates passed", flush=True)
        return 0
    if smoke_code != 0:
        print(f"validate-picker: behavior smoke failed (exit {smoke_code})", flush=True)
        return 2

    print("validate-picker: all picker gates passed", flush=True)
    return 0
