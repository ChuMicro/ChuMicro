"""CHU006: no mono-repo-internal references in publishable trees.

Walks every text file under each ``libraries/<pkg>/`` and
``workbench/<pkg>/`` package directory plus
``support/test_harness/`` and flags strings, docstrings, or comments
that name concepts only existing inside the chumicro mono-repo or
the workspace-template starter.  Those references are meaningless to
a PyPI / CircuitPython-bundle / MicroPython-bundle consumer who reads
the shipped source, README, docs site, or tests.

The walker covers ``src/``, ``docs/``, ``tests/``, ``functional_tests/``,
``examples/``, ``README.md``, and ``pyproject.toml``. Wherever a
published package surfaces text to consumers or contributors who
installed without the mono-repo checked out.

Self-scope: the rule resolves package directories under
``<repo_root>/libraries/`` and ``<repo_root>/workbench/`` plus
``<repo_root>/support/test_harness/``.  In a tree without those (a
downstream user workspace), it returns no findings, a silent no-op.

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


def _under_subdir(filepath: Path, *, parent: str, child: str) -> bool:
    """True when *filepath* sits under ``<parent>/<child>/`` anywhere in its parts.

    Path-segment match, never a substring match, so a stray
    ``checks-staging`` or ``my-workbench`` directory in the path
    can't accidentally satisfy the predicate.
    """
    parts = filepath.parts
    return any(
        first == parent and second == child
        for first, second in zip(parts, parts[1:], strict=False)
    )


def _outside_chumicro_workspace(filepath: Path) -> bool:
    """Exempt the ``chumicro_workspace`` package from the workspace-shim rule.

    The workspace package owns the workspace-template's command-runner
    shim. Generating it, parsing it, and teaching users about it is
    its job.  Bare shim mentions throughout that package's tree are
    correct.
    """
    return not _under_subdir(filepath, parent="workbench", child="workspace")


def _outside_chumicro_checks(filepath: Path) -> bool:
    """Exempt the ``chumicro_checks`` package from "internal jargon" patterns.

    The chumicro_checks package's purpose is to enumerate, describe,
    and run the CHU rules.  Inside its tree, CHU code identifiers are
    public API, the mono-repo and its ``plans/`` tree are
    load-bearing references (they're what the rules target), and
    naming ``scripts/run.py`` documents the mono-repo wire-up.
    """
    return not _under_subdir(filepath, parent="workbench", child="checks")


#: Top-level directory names that signal a workspace cloned from the
#: ChuMicro-Workspace-Template.  Files under a repo-root tree named one
#: of these legitimately mention the workspace's own ``run.py`` shim.
#: That IS the command runner in a user workspace, not the
#: chumicro-style anti-pattern the bare-``run.py`` rule is meant to
#: catch.  Matched against the *first* repo-relative segment only: a
#: package's own ``examples/`` or ``tests/`` subdirectory
#: (``libraries/pkg/examples/``) ships to consumers and stays in scope.
_TEMPLATE_PATH_SEGMENTS: frozenset[str] = frozenset({
    "packages", "projects", "shared", "examples", "tests",
})


def _outside_runpy_owners(filepath: Path) -> bool:
    """Combined predicate: outside trees where the workspace shim is legitimate.

    Three trees legitimately name the workspace's command-runner script:

    * ``workbench/workspace/``: the chumicro_workspace package
      generates the shim (covered by :func:`_outside_chumicro_workspace`).
    * ``workbench/checks/``: this package's own source legitimately
      describes the rule and the literal it flags
      (covered by :func:`_outside_chumicro_checks`).
    * Template / workspace user-content trees whose repo-root directory
      is ``packages/``, ``projects/``, ``shared/``, ``examples/``, or
      ``tests/``.  In a workspace cloned from the template, the shim IS
      the command runner.  Only the leading repo-relative segment is
      consulted, so a publishable package's own ``examples/`` or
      ``tests/`` subdirectory stays in scope.

    The rule fires only outside all three sets: on PyPI-publishable
    library or workbench code that shouldn't reference a host-only
    shim.  *filepath* is the repo-root-relative path (supplied by
    ``LeakRule``), so ``parts[0]`` is the workspace's top-level tree.
    """
    if not _outside_chumicro_workspace(filepath):
        return False
    if not _outside_chumicro_checks(filepath):
        return False
    parts = filepath.parts
    return not (bool(parts) and parts[0] in _TEMPLATE_PATH_SEGMENTS)


def _publishable_package_dirs(repo_root: Path) -> list[Path]:
    """Return every tree the rule walks for forbidden references.

    Mono-repo shape: per-package directories under ``libraries/`` and
    ``workbench/`` plus ``support/test_harness/``: the trees that
    ship to PyPI / CircuitPython-bundle / MicroPython-bundle
    consumers.

    Template / workspace shape: per-package directories under
    ``packages/`` and ``projects/`` plus the flat user-content
    trees ``shared/``, ``examples/``, and root ``tests/``.  In a
    workspace cloned from the template, those trees ARE the
    "publishable" surface, anything the user might commit and
    share, so the same anti-leak rules apply.

    Both shapes union; absent trees are silently skipped.
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
    for parent in ("packages", "projects"):
        parent_dir = repo_root / parent
        if not parent_dir.is_dir():
            continue
        for package_dir in sorted(parent_dir.iterdir()):
            if package_dir.is_dir():
                roots.append(package_dir)
    for flat_dir in ("shared", "examples", "tests"):
        candidate = repo_root / flat_dir
        if candidate.is_dir():
            roots.append(candidate)
    return roots


_PATTERNS: tuple[LeakPattern, ...] = (
    (
        re.compile(r"\b(?:Decision|ADR)\s*0\d{3}\b"),
        "Decision/ADR NNNN ref: ADRs live in plans/decisions/, not shipped to consumers",
        everywhere,
    ),
    (
        re.compile(r"\bplans/[A-Za-z0-9_./-]*\.md\b"),
        "plans/...md path: mono-repo planning tree, not on consumer machines",
        _outside_chumicro_checks,
    ),
    (
        re.compile(r"\bplans/(?:decisions|workstreams|next-up|patterns|learnings)\b"),
        "plans/... path: mono-repo planning tree, not on consumer machines",
        _outside_chumicro_checks,
    ),
    (
        re.compile(r"\bscripts/run\.py\b"),
        "scripts/run.py ref: mono-repo command runner, not on consumer machines",
        _outside_chumicro_checks,
    ),
    (
        re.compile(r"(?<!scripts/)\brun\.py\b"),  # noqa: CHU006  rule-pattern data: the regex flags this exact literal
        "bare run.py ref: name the installable CLI (chumicro-deploy, etc.) "  # noqa: CHU006  same reason
        "instead of the workspace shim",
        _outside_runpy_owners,
    ),
    (
        re.compile(
            r"\b(?:test-(?:libraries-functional|all-runtimes|circuitpython"
            r"|micropython|workbench-functional)|verify-(?:examples|demos)"
            r"|prepare-(?:circuitpython|micropython|mpy-cross))\b"
        ),  # noqa: CHU006  rule-pattern data: the regex names the tasks it flags
        "mono-repo task name: a scripts/run.py task (e.g. "  # noqa: CHU006  same reason
        "test-libraries-functional) a consumer with no mono-repo task "  # noqa: CHU006  same reason
        "runner can't invoke; name the user-facing action instead",
        _outside_runpy_owners,
    ),
    (
        re.compile(r"\bchumicro\s+mono[\s-]?repo\b", re.IGNORECASE),
        "'chumicro mono-repo' framing: consumer reads this without that context",
        _outside_chumicro_checks,
    ),
    (
        re.compile(r"\bCHU\d{3}\b"),
        "CHU lint code in prose: workspace-internal jargon; name the "
        "rule's intent (e.g. 'silent test skips') rather than the code.  "
        "Legitimate matches inside ``# noqa: CHU0NN`` directives are "
        "already exempt",
        _outside_chumicro_checks,
    ),
    (
        re.compile(r"\b(?:AGENTS(?:\.notes)?|CONTRIBUTING)\.md\b"),  # noqa: CHU006  rule-pattern data: the regex flags this exact literal
        "AGENTS.md / CONTRIBUTING.md ref: mono-repo / template "
        "governance file, meaningless to a PyPI consumer reading the "
        "shipped source",
        _outside_chumicro_checks,
    ),
    (
        re.compile(r"\.scratch/"),  # noqa: CHU006  rule-pattern data: the regex flags this exact literal
        ".scratch/ path: agent-scratch convention, not on consumer "
        "machines; publishable code writes build artifacts to _generated/",
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
