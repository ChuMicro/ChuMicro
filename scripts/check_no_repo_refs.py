"""Lint shipped src/ for chumicro-internal references that don't belong on PyPI.

Walks every text file under ``libraries/*/src/``, ``workbench/*/src/``,
and ``support/test_harness/src/`` and flags strings, docstrings, or
comments that name concepts only existing inside the chumicro mono-repo
or the chumicro-workspace-template starter.  Those references are
meaningless to a PyPI / CircuitPython-bundle consumer who reads the
shipped source.

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


def _outside_chumicro_workspace(filepath: Path) -> bool:
    """Pattern fires everywhere except inside ``workbench/workspace/src/``.

    The ``chumicro_workspace`` package owns the workspace-template's
    ``run.py`` shim — generating it, parsing it, and teaching users
    about it is its job.  Bare ``run.py`` mentions there are correct.
    Anywhere else, ``run.py`` is the workspace shim's command name
    leaking into a package that shouldn't know about it.
    """
    return "workbench/workspace/src" not in filepath.as_posix()


_PATTERNS: tuple[tuple[re.Pattern[str], str, Callable[[Path], bool]], ...] = (
    (
        re.compile(r"\bDecision\s*0\d{3}\b"),
        "Decision NNNN ref — ADRs live in plans/decisions/, not shipped to consumers",
        _everywhere,
    ),
    (
        re.compile(r"\bplans/[A-Za-z0-9_./-]*\.md\b"),
        "plans/...md path — mono-repo planning tree, not on consumer machines",
        _everywhere,
    ),
    (
        re.compile(r"\bplans/(?:decisions|workstreams|next-up|patterns|learnings)\b"),
        "plans/... path — mono-repo planning tree, not on consumer machines",
        _everywhere,
    ),
    (
        re.compile(r"\bscripts/run\.py\b"),
        "scripts/run.py ref — mono-repo command runner, not on consumer machines",
        _everywhere,
    ),
    (
        re.compile(r"(?<!scripts/)\brun\.py\b"),
        "bare run.py ref — name the installable CLI (chumicro-deploy, etc.) "
        "instead of the workspace shim",
        _outside_chumicro_workspace,
    ),
    (
        re.compile(r"\bchumicro\s+mono[\s-]?repo\b", re.IGNORECASE),
        "'chumicro mono-repo' framing — consumer reads this without that context",
        _everywhere,
    ),
)

#: File suffixes scanned.  ``.py`` covers source; ``.toml`` covers config
#: templates that ship in payloads; ``.template`` / ``.md.template`` cover
#: workbench payloads materialized into user workspaces; ``.md`` catches
#: README-shaped docs that ship inside ``src/`` payload trees.
_SCANNED_SUFFIXES = (".py", ".toml", ".md", ".template", ".txt", ".cfg", ".ini")

_NOQA_PATTERNS = (
    re.compile(r"#\s*noqa(?::\s*([A-Z0-9, ]+))?"),
    re.compile(r"<!--\s*noqa(?::\s*([A-Z0-9, ]+))?\s*-->"),
)

#: Roots whose contents are temporarily skipped while a parallel
#: refactor catches up.  Drop entries here once the refactor lands and
#: those files have been cleansed of mono-repo references.
_SKIPPED_ROOTS: tuple[Path, ...] = ()


def _scan_roots() -> list[Path]:
    """Return the directory roots to scan.

    Includes every package's ``src/`` under ``libraries/``,
    ``workbench/``, and ``support/test_harness/``.
    """
    roots: list[Path] = []
    for parent in ("libraries", "workbench"):
        parent_dir = ROOT / parent
        if not parent_dir.is_dir():
            continue
        for package_dir in sorted(parent_dir.iterdir()):
            src_dir = package_dir / "src"
            if src_dir.is_dir():
                roots.append(src_dir)
    test_harness_root = ROOT / "support" / "test_harness" / "src"
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
        for pattern, message, applies_to in _PATTERNS:
            if not applies_to(filepath):
                continue
            if pattern.search(line):
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
        if any(part in ("__pycache__", ".egg-info") for part in parts):
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
        print(f"\nFound {len(all_errors)} mono-repo reference(s) in shipped src/.")
        print(
            "These ship to PyPI / CircuitPython-bundle consumers — "
            "they shouldn't reference internal-only concepts.",
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
