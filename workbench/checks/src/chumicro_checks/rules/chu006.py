"""CHU006 — no mono-repo-internal references in publishable trees.

Walks every text file under each ``libraries/<pkg>/`` and
``workbench/<pkg>/`` package directory plus
``support/test_harness/`` and flags strings, docstrings, or comments
that name concepts only existing inside the chumicro mono-repo or
the workspace-template starter.  Those references are meaningless to
a PyPI / CircuitPython-bundle / MicroPython-bundle consumer who reads
the shipped source, README, docs site, or tests.

The walker covers ``src/``, ``docs/``, ``tests/``, ``functional_tests/``,
``examples/``, ``README.md``, and ``pyproject.toml`` — wherever a
published package surfaces text to consumers or contributors who
installed without the mono-repo checked out.

Self-scope: the rule resolves package directories under
``<repo_root>/libraries/`` and ``<repo_root>/workbench/`` plus
``<repo_root>/support/test_harness/``.  In a tree without those (a
downstream user workspace), it returns no findings — silent no-op.

Suppression: ``# noqa: CHU006`` on the offending line, or
``<!-- noqa: CHU006 -->`` for Markdown.
"""

from __future__ import annotations

import re
from pathlib import Path

from chumicro_checks.rules._leak_rule import (
    LeakPattern,
    LeakRule,
    everywhere,
)

_RULE_CODE = "CHU006"


def _outside_chumicro_workspace(filepath: Path) -> bool:
    """Exempt the ``chumicro_workspace`` package from the workspace-shim rule.

    The workspace package owns the workspace-template's command-runner
    shim — generating it, parsing it, and teaching users about it is
    its job.  Bare shim mentions throughout that package's tree are
    correct.
    """
    return "workbench/workspace/" not in filepath.as_posix()


def _outside_chumicro_checks(filepath: Path) -> bool:
    """Exempt the ``chumicro_checks`` package from "internal jargon" patterns.

    The chumicro_checks package's purpose is to enumerate, describe,
    and run the CHU rules.  Inside its tree, CHU code identifiers are
    public API, the mono-repo and its ``plans/`` tree are
    load-bearing references (they're what the rules target), and
    naming ``scripts/run.py`` documents the mono-repo wire-up.
    """
    return "workbench/checks/" not in filepath.as_posix()


def _publishable_package_dirs(repo_root: Path) -> list[Path]:
    """Return every package directory under ``libraries/`` and
    ``workbench/`` plus ``support/test_harness/``.
    """
    roots: list[Path] = []
    for parent in ("libraries", "workbench"):
        parent_dir = repo_root / parent
        if not parent_dir.is_dir():
            continue
        for package_dir in sorted(parent_dir.iterdir()):
            if package_dir.is_dir():
                roots.append(package_dir)
    test_harness_root = repo_root / "support" / "test_harness"
    if test_harness_root.is_dir():
        roots.append(test_harness_root)
    return roots


_PATTERNS: tuple[LeakPattern, ...] = (
    (
        re.compile(r"\bDecision\s*0\d{3}\b"),
        "Decision NNNN ref — ADRs live in plans/decisions/, not shipped to consumers",
        everywhere,
    ),
    (
        re.compile(r"\bplans/[A-Za-z0-9_./-]*\.md\b"),
        "plans/...md path — mono-repo planning tree, not on consumer machines",
        _outside_chumicro_checks,
    ),
    (
        re.compile(r"\bplans/(?:decisions|workstreams|next-up|patterns|learnings)\b"),
        "plans/... path — mono-repo planning tree, not on consumer machines",
        _outside_chumicro_checks,
    ),
    (
        re.compile(r"\bscripts/run\.py\b"),
        "scripts/run.py ref — mono-repo command runner, not on consumer machines",
        _outside_chumicro_checks,
    ),
    (
        re.compile(r"(?<!scripts/)\brun\.py\b"),  # noqa: CHU006  rule-pattern data: the regex flags this exact literal
        "bare run.py ref — name the installable CLI (chumicro-deploy, etc.) "  # noqa: CHU006  same reason
        "instead of the workspace shim",
        _outside_chumicro_workspace,
    ),
    (
        re.compile(r"\bchumicro\s+mono[\s-]?repo\b", re.IGNORECASE),
        "'chumicro mono-repo' framing — consumer reads this without that context",
        _outside_chumicro_checks,
    ),
    (
        re.compile(r"\bCHU\d{3}\b"),
        "CHU lint code in prose — workspace-internal jargon; name the "
        "rule's intent (e.g. 'silent test skips') rather than the code.  "
        "Legitimate matches inside ``# noqa: CHU0NN`` directives are "
        "already exempt",
        _outside_chumicro_checks,
    ),
)

_SCANNED_SUFFIXES: tuple[str, ...] = (
    ".py",
    ".toml",
    ".md",
    ".template",
    ".txt",
    ".cfg",
    ".ini",
)


CHU006 = LeakRule(
    code=_RULE_CODE,
    description="no mono-repo-internal references in publishable trees",
    scan_roots_for=_publishable_package_dirs,
    patterns=_PATTERNS,
    suffixes=_SCANNED_SUFFIXES,
)
