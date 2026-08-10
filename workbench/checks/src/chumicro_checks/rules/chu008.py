"""CHU008: no upstream-derivative framing in workspace-template trees.

Targets the [ChuMicro-Workbench-Template](https://github.com/ChuMicro/ChuMicro-Workbench-Template)
starter repo and downstream user workspaces cloned from it.  Flags
prose / config / docstrings that frame the user's workspace as a
derivative of an upstream chumicro mono-repo: leftover ``Decision NNNN``
/ ``ADR NNNN`` pointers, ``plans/...md`` paths, ``scripts/run.py``
references, the "chumicro mono-repo" framing.  Those references are coherent inside
the chumicro mono-repo (where ADRs are co-located) but meaningless in
a workspace cloned from the template.

Walker covers user-content trees: ``packages/``, ``projects/``,
``examples/``, ``shared/``, ``tests/``, plus root-level files that
ship in the template (``README.md``, ``AGENTS.md``, ``CONTRIBUTING.md``,
``pyproject.toml``, ``workspace.yml``, ``devices.yml``,
``chumicro-dev.toml``).

Self-scope: the rule fires only when the repo has the
template-workspace shape, detected by presence of ``packages/`` at
the repo root.  In the chumicro mono-repo (which has ``libraries/``
and ``workbench/`` instead), CHU008 returns no findings, a silent
no-op.

Suppression: ``# noqa: CHU008`` on the offending line, or
``<!-- noqa: CHU008 -->`` for Markdown.
"""

from __future__ import annotations

import re
from pathlib import Path

from chumicro_checks.rules._leak_rule import (
    LeakPattern,
    LeakRule,
    everywhere,
)

_RULE_CODE = "CHU008"

#: Subdirectories of a template-shaped repo that hold user content.
_TEMPLATE_SUBDIRS: tuple[str, ...] = (
    "packages",
    "projects",
    "examples",
    "shared",
    "tests",
)

#: Root-level files that ship in the template / downstream workspace
#: and can leak upstream-derivative framing in their prose or config.
_TEMPLATE_ROOT_FILES: tuple[str, ...] = (
    "README.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "pyproject.toml",
    "workspace.yml",
    "devices.yml",
    "chumicro-dev.toml",
)


def _template_repo_scan_roots(repo_root: Path) -> list[Path]:
    """Return scan roots when *repo_root* has the workspace-template shape.

    Detection heuristic: ``packages/`` at root is the template's
    defining shape.  Mono-repos have ``libraries/`` and never use
    ``packages/`` for the same purpose.
    """
    if not (repo_root / "packages").is_dir():
        return []
    roots: list[Path] = []
    for dir_name in _TEMPLATE_SUBDIRS:
        candidate = repo_root / dir_name
        if candidate.is_dir():
            roots.append(candidate)
    for filename in _TEMPLATE_ROOT_FILES:
        candidate = repo_root / filename
        if candidate.is_file():
            roots.append(candidate)
    return roots


_PATTERNS: tuple[LeakPattern, ...] = (
    (
        re.compile(r"\b(?:Decision|ADR)\s*0\d{3}\b"),
        "Decision/ADR NNNN ref: ADRs live in the chumicro mono-repo, not in a "
        "user workspace.  Inline the relevant rationale instead of pointing "
        "at the ADR number",
        everywhere,
    ),
    (
        re.compile(r"\bplans/[A-Za-z0-9_./-]*\.md\b"),
        "plans/...md path: mono-repo planning tree; users don't have it",
        everywhere,
    ),
    (
        re.compile(r"\bplans/(?:decisions|workstreams|next-up|patterns|learnings)\b"),
        "plans/... path: mono-repo planning tree; users don't have it",
        everywhere,
    ),
    (
        re.compile(r"\bscripts/run\.py\b"),
        "scripts/run.py ref: mono-repo command runner; users have run.py "  # noqa: CHU006  rule-pattern data: this message describes what the rule flags
        "(without the scripts/ prefix) in their workspace root",
        everywhere,
    ),
    (
        re.compile(r"\bchumicro\s+mono[\s-]?repo\b", re.IGNORECASE),
        "'chumicro mono-repo' framing: users don't see their workspace as "
        "a derivative of an upstream",
        everywhere,
    ),
)

_SCANNED_SUFFIXES: tuple[str, ...] = (
    ".py",
    ".md",
    ".toml",
    ".yml",
    ".yaml",
    ".txt",
    ".cfg",
    ".ini",
)


CHU008 = LeakRule(
    code=_RULE_CODE,
    description="no upstream-derivative framing in workspace-template trees",
    scan_roots_for=_template_repo_scan_roots,
    patterns=_PATTERNS,
    suffixes=_SCANNED_SUFFIXES,
)
