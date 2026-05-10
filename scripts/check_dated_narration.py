"""Lint code comments for dated narration and workstream-phase pointers.

Code comments document the *why* of current code, nothing else.
Dated incidents, removed-code framing, and workstream-phase
pointers belong in the commit message, the ADR body, or the
workstream file — all reachable via ``git log`` and ``plans/``.
Leaving them in source files makes the comment rot the moment the
context drifts and shows up as noise to a cold reader who has no
way to resolve "Phase 5 of the workspace-ecosystem workstream" or
"F4 of the 2026-05-06 verification pass".

The walker covers every ``.py`` and ``.md`` file under
``libraries/``, ``workbench/``, ``support/``, and ``scripts/``.
``plans/`` is journal-shaped by intent and excluded.  Build /
cache artefacts (``__pycache__``, ``site``, ``build``, ``dist``,
``*.egg-info``, ``.pytest_cache``, ``.mypy_cache``,
``.ruff_cache``, ``.tox``, ``.venv``, ``node_modules``) are
skipped.

Flagged shapes:

* ``Surfaced YYYY-MM-DD`` / ``Discovered YYYY-MM-DD`` /
  ``Observed YYYY-MM-DD`` / ``Captured YYYY-MM-DD`` /
  ``Caught YYYY-MM-DD`` — dated incidents.
* ``verified live YYYY-MM-DD`` / ``verified on hardware YYYY-MM-DD`` —
  dated verifications.
* ``live-tested on … YYYY-MM-DD`` / ``bench-tested on … YYYY-MM-DD`` —
  dated verifications.
* ``Phase N of … workstream`` / ``Step N of … workstream`` /
  ``Slice N of … workstream`` / ``workstream Phase N`` —
  workstream-phase pointers.
* ``FN of the YYYY-MM-DD verification`` /
  ``YYYY-MM-DD verification (pass|finding)`` /
  ``verification finding #N, YYYY-MM-DD`` —
  dated verification findings (workstream-internal F-numbered notes).
* ``in the <hyphen-named> (pass|audit|sweep|bake)`` — workstream-named
  phase tags ("in the deploy-audit pass").  Single-word "pass" /
  "audit" usages ("in the same pass", "security audit") still pass
  because the regex requires at least one hyphen.
* ``Earlier versions`` / ``Previously this`` / ``Previously the`` /
  ``We used to`` / ``Used to be`` — removed-code framing.

Suppression: ``# noqa: CHU012`` on the offending line, or
``<!-- noqa: CHU012 -->`` for Markdown.  Use sparingly — a
suppression is a claim that the dated framing genuinely is the
*why* of current code (e.g. a workaround pinned to a specific
firmware version); the lint will believe you, the reviewer should
not.

Usage::

    python scripts/check_dated_narration.py
    python scripts/check_dated_narration.py [paths...]
    python scripts/run.py lint            # runs alongside ruff
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from repo_layout import ROOT

_RULE_CODE = "CHU012"


_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b(?:Surfaced|Discovered|Observed|Captured|Caught|shipped|landed) "
            r"\d{4}-\d{2}-\d{2}\b",
        ),
        "dated incident — move to commit message or workstream file",
    ),
    (
        re.compile(r"\bverified (?:live|on hardware) \d{4}-\d{2}-\d{2}\b", re.IGNORECASE),
        "dated verification — move to commit message or workstream file",
    ),
    (
        re.compile(
            r"\b(?:live-tested|bench-tested) on [^\n]{1,40}\d{4}-\d{2}-\d{2}\b",
            re.IGNORECASE,
        ),
        "dated verification — move to commit message or workstream file",
    ),
    (
        re.compile(r"\b(?:Phase|Step|Slice)\s+\d+[a-z]?\b[^\n]{0,80}\bworkstream\b"),
        "workstream-phase pointer — move to commit message or workstream file",
    ),
    (
        re.compile(r"\bworkstream\s+Phase\s+\d+[a-z]?\b"),
        "workstream-phase pointer — move to commit message or workstream file",
    ),
    (
        # Slice N — "Slice" is workstream-only jargon in this codebase
        # (no procedural meaning), so match every numbered occurrence.
        re.compile(r"\bSlice\s+\d+[a-z]?\b"),
        "workstream-phase pointer — move to commit message or workstream file",
    ),
    (
        # Phase|Step N when NOT followed by a colon — procedural numbered
        # steps ("# Step 1: put the board in bootloader mode") use the
        # colon and stay clean.  Workstream-pointer shapes ("Phase 7
        # Layer-3 caught this", "(Phase 2a — status)", "Phase 4
        # follow-up") don't, so they get flagged.
        re.compile(r"\b(?:Phase|Step)\s+\d+[a-z]?\b(?!\s*:)"),
        "workstream-phase pointer — move to commit message or workstream file",
    ),
    (
        # Item N — the numbered work-item shape used by multi-item
        # workstreams (deploy-multi-board-and-fskit-followups Item 1,
        # Item 4 caveat, etc.).  No procedural usage exists in this
        # codebase, so match every numbered occurrence.
        re.compile(r"\bItem\s+\d+[a-z]?\b"),
        "workstream-phase pointer — move to commit message or workstream file",
    ),
    (
        # F-numbered workstream finding paired with an ISO date — covers
        # "F4 of the 2026-05-06 verification", "(F5, 2026-05-06)",
        # "F5 layout (2026-05-06)", "F6 — port-holder diagnosis
        # (2026-05-06 verification)" — anything where an F\d+ tag
        # appears within ~80 chars of an ISO date on the same line.
        re.compile(r"\bF\d+\b[^\n]{0,80}\b\d{4}-\d{2}-\d{2}\b"),
        "dated verification finding — move to commit message or workstream file",
    ),
    (
        re.compile(r"\bverification\s+finding\s+#?\d+(?:,\s*\d{4}-\d{2}-\d{2})?\b"),
        "dated verification finding — move to commit message or workstream file",
    ),
    (
        re.compile(r"\b\d{4}-\d{2}-\d{2}\s+verification\s+(?:pass|finding)\b"),
        "dated verification pass — move to commit message or workstream file",
    ),
    (
        re.compile(r"\bRegression for \d{4}-\d{2}-\d{2}\b"),
        "dated incident — move to commit message or workstream file",
    ),
    (
        re.compile(r"\bin the [a-z]+-[a-z]+(?:\s+[a-z]+){0,2}\s+(?:pass|audit|sweep|bake)\b"),
        "workstream-phase pointer — move to commit message or workstream file",
    ),
    (
        re.compile(r"\b(?:Earlier versions|Previously,?\s+th(?:is|e)|We used to|Used to be)\b"),
        "removed-code framing — move to commit message or workstream file",
    ),
)

_SCANNED_SUFFIXES = (".py", ".md")

_NOQA_PATTERNS = (
    re.compile(r"#\s*noqa(?::\s*([A-Z0-9, ]+))?"),
    re.compile(r"<!--\s*noqa(?::\s*([A-Z0-9, ]+))?\s*-->"),
)

_EXCLUDED_DIRECTORY_NAMES = frozenset({
    "__pycache__",
    "dist",
    "build",
    "site",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "node_modules",
})

#: Files whose own contents legitimately contain the forbidden patterns
#: (the lint's source carries them as regex literals; the lint's tests
#: carry them as fixture strings).  The new-package paths are listed so
#: the old script doesn't flag the migrated rule's source while both
#: implementations coexist; the entries here drop when this script is
#: retired.
_SELF_EXEMPT_RELPATHS = frozenset({
    Path("scripts/check_dated_narration.py"),
    Path("scripts/tests/test_check_dated_narration.py"),
    Path("workbench/checks/src/chumicro_checks/rules/chu012.py"),
    Path("workbench/checks/tests/test_chu012.py"),
})


def _strip_noqa(line: str) -> str:
    """Return *line* with any ``noqa`` directive removed."""
    for noqa_re in _NOQA_PATTERNS:
        line = noqa_re.sub("", line)
    return line


def _is_suppressed(line: str) -> bool:
    """Return True when *line* carries a ``CHU012``-suppressing noqa."""
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


def _is_self_exempt(filepath: Path) -> bool:
    """Return True when *filepath* is the lint's own source or test file."""
    try:
        relative = filepath.relative_to(ROOT)
    except ValueError:
        return False
    return relative in _SELF_EXEMPT_RELPATHS


def _scan_roots() -> list[Path]:
    """Return the directory roots scanned recursively.

    Covers every package directory under ``libraries/`` and
    ``workbench/`` plus ``support/`` and ``scripts/``.  ``plans/``
    is journal-shaped by intent and intentionally excluded.
    """
    roots: list[Path] = []
    for parent_name in ("libraries", "workbench"):
        parent_dir = ROOT / parent_name
        if not parent_dir.is_dir():
            continue
        for package_dir in sorted(parent_dir.iterdir()):
            if package_dir.is_dir():
                roots.append(package_dir)
    for top_level in ("support", "scripts"):
        top_dir = ROOT / top_level
        if top_dir.is_dir():
            roots.append(top_dir)
    return roots


def check_file(filepath: Path) -> list[str]:
    """Return formatted lint errors for *filepath* (empty when clean)."""
    if _is_self_exempt(filepath):
        return []
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
        for pattern, message in _PATTERNS:
            if pattern.search(scrubbed):
                errors.append(f"{relative}:{line_number}: {_RULE_CODE} {message}")
                break
    return errors


def _iter_files(path: Path) -> list[Path]:
    """Return every scannable file under *path* in deterministic order."""
    if path.is_file():
        if path.suffix not in _SCANNED_SUFFIXES:
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
        out.append(candidate)
    return out


def check_paths(paths: list[str]) -> int:
    """Check the given paths for dated-narration patterns."""
    all_errors: list[str] = []
    for path_str in paths:
        for filepath in _iter_files(Path(path_str)):
            all_errors.extend(check_file(filepath))

    if all_errors:
        for error in all_errors:
            print(error)
        print(
            f"\nFound {len(all_errors)} dated-narration / workstream-phase "
            f"pointer(s) in code comments.",
        )
        print(
            "Code comments document the *why* of current code.  Dated "
            "incidents, removed-code framing, and workstream-phase pointers "
            "belong in the commit message, the ADR body, or the workstream "
            "file — all reachable via git log and plans/.",
        )
        print(f"Fix: rephrase or add '# noqa: {_RULE_CODE}' to suppress.")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Optional paths to scan.  Defaults to the recursive walk
            over ``libraries/``, ``workbench/``, ``support/``, and
            ``scripts/``.
    """
    if argv:
        paths = argv
    else:
        paths = [str(root) for root in _scan_roots()]
    return check_paths(paths)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or None))
