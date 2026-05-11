"""Thin shim around ``chumicro_workspace.verify_examples``.

The real implementation lives in ``chumicro_workspace.example_verify`` so
the workspace-template repo (and any downstream user workspace) can run
the same gate against their own examples.  This shim keeps the existing
``python scripts/run.py verify-examples`` task working with mono-repo
defaults (relative paths shown against the repo root).

See ``plans/decisions/0013-docs-and-examples-standards.md``.
"""

from __future__ import annotations

from pathlib import Path

from chumicro_workspace import verify_examples as _verify_examples
from repo_layout import ROOT


def verify_examples(package_dirs: list[Path]) -> int:
    """Verify examples have valid syntax and resolvable imports."""
    return _verify_examples(package_dirs, display_root=ROOT)
