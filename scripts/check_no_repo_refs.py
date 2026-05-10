"""Lint published library + workbench trees for mono-repo-internal references.

Walks every text file under each ``libraries/<pkg>/`` and
``workbench/<pkg>/`` package directory plus
``support/test_harness/`` and flags strings, docstrings, or
comments that name concepts only existing inside the chumicro
mono-repo or the chumicro-workspace-template starter.  Those
references are meaningless to a PyPI / CircuitPython-bundle
consumer who reads the shipped source, README, docs site, or
tests.

The walker covers ``src/``, ``docs/``, ``tests/``,
``functional_tests/``, ``examples/``, ``README.md``, and
``pyproject.toml`` — wherever a published package surfaces text
to consumers or contributors who installed without the mono-repo
checked out.  Build / cache artifacts (``__pycache__``, ``site``,
``build``, ``dist``, ``*.egg-info``, ``.pytest_cache``,
``.mypy_cache``, ``.ruff_cache``, ``.tox``, ``.venv``,
``node_modules``) are skipped.

Flagged patterns:

* ``Decision NNNN`` — an ADR pointer; ADRs live in ``plans/decisions/``
  inside the mono-repo and aren't shipped to consumers.
* ``plans/<path>.md`` or ``plans/<dir>/`` — the mono-repo's planning
  tree; not present after ``pip install`` or a CircuitPython-bundle
  install.
* ``scripts/run.py`` — the mono-repo's developer command runner; not
  on consumer machines.
* Bare ``run.py`` (without the ``scripts/`` prefix) — the
  workspace-template's command-runner shim; only the
  ``chumicro_workspace`` package legitimately knows about it (it's
  what generates the shim).  Other packages should name the
  installable CLI (``chumicro-deploy``, ``chumicro-workspace``, etc.)
  instead.
* ``chumicro mono-repo`` / ``chumicro monorepo`` — frames the package
  as a derivative of an upstream repo the consumer doesn't have.

Suppression: ``# noqa: CHU006`` on the offending line, or
``<!-- noqa: CHU006 -->`` for Markdown.

Usage::

    python scripts/check_no_repo_refs.py
    python scripts/check_no_repo_refs.py [paths...]
    python scripts/run.py lint            # runs automatically alongside ruff
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from pathlib import Path

from repo_layout import ROOT

_RULE_CODE = "CHU006"


def _everywhere(_filepath: Path) -> bool:
    """Default scope predicate: pattern fires for every file we scan."""
    return True


def _everywhere_outside_chumicro_workspace(filepath: Path) -> bool:
    """``_everywhere`` minus the ``chumicro_workspace`` package exemption.

    The ``chumicro_workspace`` package owns the workspace-template's
    ``run.py`` shim — generating it, parsing it, and teaching users
    about it is its job.  Bare ``run.py`` mentions throughout that
    package's tree are correct.
    """
    return "workbench/workspace/" not in filepath.as_posix()


def _outside_chumicro_checks(filepath: Path) -> bool:
    """``_everywhere`` minus the ``chumicro_checks`` package exemption.

    The ``chumicro_checks`` package's purpose is to enumerate, describe,
    and run the CHU rules.  Inside its tree, CHU code identifiers are
    public API (not workspace-internal jargon), the mono-repo and its
    ``plans/`` tree are load-bearing references (they're what the rules
    target), and naming ``scripts/run.py`` is necessary to document
    that the mono-repo's lint phase shells out to ``chumicro-checks``.
    """
    return "workbench/checks/" not in filepath.as_posix()


_PATTERNS: tuple[tuple[re.Pattern[str], str, Callable[[Path], bool]], ...] = (
    (
        re.compile(r"\bDecision\s*0\d{3}\b"),
        "Decision NNNN ref — ADRs live in plans/decisions/, not shipped to consumers",
        _everywhere,
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
        re.compile(r"(?<!scripts/)\brun\.py\b"),
        "bare run.py ref — name the installable CLI (chumicro-deploy, etc.) "
        "instead of the workspace shim",
        _everywhere_outside_chumicro_workspace,
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

#: File suffixes scanned.  ``.py`` covers source + tests; ``.toml``
#: covers ``pyproject.toml`` + config templates that ship in payloads;
#: ``.template`` covers workbench payloads materialized into user
#: workspaces; ``.md`` catches README + ``docs/`` + per-test docstring
#: pointer files.
_SCANNED_SUFFIXES = (".py", ".toml", ".md", ".template", ".txt", ".cfg", ".ini")

_NOQA_PATTERNS = (
    re.compile(r"#\s*noqa(?::\s*([A-Z0-9, ]+))?"),
    re.compile(r"<!--\s*noqa(?::\s*([A-Z0-9, ]+))?\s*-->"),
)


def _strip_noqa(line: str) -> str:
    """Return *line* with any ``noqa`` directive removed.

    Pattern matching runs against the scrubbed line so the rule codes
    embedded inside ``# noqa: CHUNNN`` markers don't false-positive
    the prose-CHU rule.  The full (un-scrubbed) line is still used
    for :func:`_is_suppressed` so per-rule suppression continues to
    work exactly as before.
    """
    for noqa_re in _NOQA_PATTERNS:
        line = noqa_re.sub("", line)
    return line

#: Directory names skipped during the recursive walk — build artifacts,
#: cache directories, vendored deps, and IDE / CI scratch.
_EXCLUDED_DIRECTORY_NAMES = frozenset({
    "__pycache__",
    "dist",
    "build",
    "site",            # mkdocs build output
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "node_modules",
})

#: Roots whose contents are temporarily skipped while a parallel
#: refactor catches up.  Drop entries here once the refactor lands and
#: those files have been cleansed of mono-repo references.
_SKIPPED_ROOTS: tuple[Path, ...] = ()


def _scan_roots() -> list[Path]:
    """Return the package roots to scan recursively.

    Includes every package directory under ``libraries/`` and
    ``workbench/`` plus ``support/test_harness/``.  The recursive walk
    in :func:`_iter_files` covers each package's ``src/``, ``docs/``,
    ``tests/``, ``functional_tests/``, ``examples/``, ``README.md``,
    and ``pyproject.toml`` — wherever a published package surfaces
    text to consumers or contributors who installed without the
    mono-repo checked out.
    """
    roots: list[Path] = []
    for parent in ("libraries", "workbench"):
        parent_dir = ROOT / parent
        if not parent_dir.is_dir():
            continue
        for package_dir in sorted(parent_dir.iterdir()):
            if package_dir.is_dir():
                roots.append(package_dir)
    test_harness_root = ROOT / "support" / "test_harness"
    if test_harness_root.is_dir():
        roots.append(test_harness_root)
    return roots


def _is_suppressed(line: str) -> bool:
    """Return True when *line* carries a ``CHU006``-suppressing noqa."""
    for pattern in _NOQA_PATTERNS:
        match = pattern.search(line)
        if match is None:
            continue
        codes = match.group(1)
        if codes is None or codes.strip() == "":
            return True
        if _RULE_CODE in {code.strip() for code in codes.split(",")}:
            return True
    return False


def check_file(filepath: Path) -> list[str]:
    """Return formatted lint errors for *filepath* (empty when clean)."""
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    relative = filepath.relative_to(ROOT) if filepath.is_relative_to(ROOT) else filepath
    errors: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if _is_suppressed(line):
            continue
        scrubbed = _strip_noqa(line)
        for pattern, message, applies_to in _PATTERNS:
            if not applies_to(filepath):
                continue
            if pattern.search(scrubbed):
                errors.append(f"{relative}:{line_number}: {_RULE_CODE} {message}")
                break
    return errors


def _is_skipped(filepath: Path) -> bool:
    """Return True when *filepath* lives under a temporarily-skipped root."""
    try:
        relative = filepath.relative_to(ROOT)
    except ValueError:
        return False
    relative_parts = relative.parts
    for skipped in _SKIPPED_ROOTS:
        skipped_parts = skipped.parts
        if relative_parts[: len(skipped_parts)] == skipped_parts:
            return True
    return False


def _iter_files(path: Path) -> list[Path]:
    """Return every scannable file under *path* in deterministic order."""
    if path.is_file():
        if path.suffix not in _SCANNED_SUFFIXES or _is_skipped(path):
            return []
        return [path]
    if not path.is_dir():
        return []
    out: list[Path] = []
    for candidate in sorted(path.rglob("*")):
        if not (candidate.is_file() and candidate.suffix in _SCANNED_SUFFIXES):
            continue
        parts = candidate.parts
        if any(part in _EXCLUDED_DIRECTORY_NAMES for part in parts):
            continue
        if any(part.endswith(".egg-info") for part in parts):
            continue
        if _is_skipped(candidate):
            continue
        out.append(candidate)
    return out


def check_paths(paths: list[str]) -> int:
    """Check the given paths for forbidden mono-repo references."""
    all_errors: list[str] = []
    for path_str in paths:
        for filepath in _iter_files(Path(path_str)):
            all_errors.extend(check_file(filepath))

    if all_errors:
        for error in all_errors:
            print(error)
        print(
            f"\nFound {len(all_errors)} mono-repo reference(s) in published "
            f"library / workbench trees.",
        )
        print(
            "These ship to PyPI / CircuitPython-bundle consumers — they "
            "shouldn't reference internal-only concepts (Decision NNNN, "
            "plans/...md, scripts/run.py, bare run.py, 'chumicro mono-repo').",
        )
        print(f"Fix: rephrase or add '# noqa: {_RULE_CODE}' to suppress.")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Optional paths to scan.  Defaults to every shipped ``src/``
            tree under the workspace.
    """
    if argv:
        paths = argv
    else:
        paths = [str(root) for root in _scan_roots()]
    return check_paths(paths)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or None))
