#!/usr/bin/env python3
"""REPO-SPECIFIC (ChuMicro) apply gate for the audit skills — THE PORTING SEAM.

`apply_fix.py runtests` (shared by audit-code and audit-branch) runs the universal pytest gate,
then consults this file for an extra repo-specific gate. The contract is one function:

    gate_command(path) -> (argv, reason) | None

Given the repo-relative (or absolute) path of the file an applied fix edited, return the extra
command to run plus a one-line reason the user sees, or None when the universal gate suffices.
The command runs from the repo root; its exit code gates the fix like pytest's does.

Porting these skills to another repo means replacing or deleting THIS FILE ONLY — the skill
bodies and pipeline scripts never encode repo policy. Delete it and the universal pytest gate is
all that runs; replace it (e.g. a Gradle multiplatform check for a Kotlin repo) and the apply
loop picks the new policy up unchanged.

This repo's policy: a fix landing under `libraries/<name>/` or `support/<name>/` also gates on
that package's cross-runtime suite — CPython green is necessary but not sufficient for code that
ships to MicroPython and CircuitPython (a patch can be CPython-idiomatic and illegal on the
device runtimes: `typing` imports, `__slots__`, iterator allocations in hot loops).
"""
import os

CROSS_RUNTIME_ROOTS = ("libraries", "support")


def gate_command(path):
    """The extra gate for a fix that edited `path`, or None when pytest alone suffices."""
    parts = os.path.normpath(path).split(os.sep)
    for root in CROSS_RUNTIME_ROOTS:
        if root in parts and parts.index(root) + 1 < len(parts):
            package = parts[parts.index(root) + 1]
            # .venv/bin/python resolves against the repo root the caller runs the command from;
            # the workspace venv carries the deps scripts/run.py needs, system python3 may not
            return (
                [".venv/bin/python", "scripts/run.py", "test-all-runtimes", "--libraries", package],
                f"{root}/{package} ships to MicroPython + CircuitPython — "
                f"CPython green alone does not validate the fix",
            )
    return None
