"""Lint for newline and whitespace problems (CHU002–CHU005).

Walks text files and flags:

- **CHU002** — file does not end with exactly one newline.
- **CHU003** — more than two consecutive blank lines (three+ ``\\n``
  in a row within the file body).
- **CHU004** — trailing whitespace on a line.
- **CHU005** — blank line immediately after a block opener (``def``,
  ``class``, ``if``, ``for``, ``while``, ``with``, ``try``, ``else``,
  ``elif``, ``except``, ``finally``).  Python files only.

Suppression: add ``# noqa: CHUxxx`` on the flagged line (CHU004 and
CHU005 only; CHU002 and CHU003 are structural and cannot be
suppressed per-line).

Usage::

    python scripts/check_whitespace.py [paths...]
    python scripts/run.py lint          # runs automatically alongside ruff
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from repo_layout import ROOT, discover_ruff_paths

_EXTENSIONS = {".py", ".md", ".yml", ".yaml", ".toml", ".txt", ".cfg", ".ini", ".json"}
_SKIP_DIRS = {"__pycache__", "site", ".git", ".tools", "node_modules"}
_SKIP_SUFFIXES = (".egg-info",)


def _is_skipped_part(part: str) -> bool:
    """Return whether a path component should be skipped.

    Args:
        part: Single directory or file name from a path.
    """
    return part in _SKIP_DIRS or part.endswith(_SKIP_SUFFIXES)

# Constructed dynamically so ruff doesn't interpret it as a directive.
_NOQA_TAG = "# " + "noqa"

# Matches lines that open a Python block.  Two flavours:
# 1. Keywords whose syntax requires a trailing expression before the
#    colon (def, class, if, elif, for, while, with, except) — the
#    line must end with ``:`` (ignoring trailing comments/whitespace).
# 2. Stand-alone keywords that *are* the whole statement (else, try,
#    finally) — just the keyword and a colon.
# Requiring the colon at end-of-line avoids false positives on
# docstrings or prose that happen to start with "for" or "if".
_BLOCK_OPENER = re.compile(
    r"^\s*(?:"
    r"(?:def |class |if |elif |for |while |with |except\b).*:"
    r"|"
    r"(?:else|try|finally)\s*:"
    r")\s*(?:#.*)?\s*$"
)

# Matches a ``def`` or ``class`` statement.  Used to allow a blank
# line between a block opener and a nested definition — a common
# pattern in import-fallback blocks and conditional definitions.
_DEFINITION = re.compile(r"^\s*(?:def |class )")


def _has_noqa(line: str, code: str) -> bool:
    """Return whether *line* carries a noqa suppression for *code*.

    Args:
        line: Source line text.
        code: Rule code to check (e.g. ``"CHU004"``).
    """
    tag_pos = line.find(_NOQA_TAG)
    if tag_pos == -1:
        return False
    after = line[tag_pos + len(_NOQA_TAG):]
    return after.strip() == "" or code in after


def _should_check(filepath: Path) -> bool:
    """Return whether *filepath* is a text file we should scan.

    Args:
        filepath: Path to evaluate.
    """
    if filepath.suffix not in _EXTENSIONS:
        return False
    parts = (
        filepath.relative_to(ROOT).parts
        if filepath.is_relative_to(ROOT)
        else filepath.parts
    )
    return not any(_is_skipped_part(part) for part in parts)


def check_file(filepath: Path) -> list[str]:
    """Check a single file for whitespace problems.

    Args:
        filepath: Absolute or relative path to the file.

    Returns:
        List of human-readable error strings.
    """
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    relative = filepath.relative_to(ROOT) if filepath.is_relative_to(ROOT) else filepath
    errors: list[str] = []

    # --- CHU002: file must end with exactly one newline ---
    if text == "":
        # Empty files are fine — no trailing-newline issue.
        pass
    elif not text.endswith("\n"):
        errors.append(f"{relative}:1: CHU002 file does not end with a newline")
    elif text.endswith("\n\n"):
        # Count how many trailing newlines.
        stripped = text.rstrip("\n")
        extra = len(text) - len(stripped)
        errors.append(
            f"{relative}:{len(text.splitlines()) + 1}: CHU002 "
            f"file ends with {extra} newlines instead of 1"
        )

    # --- Per-line checks ---
    lines = text.splitlines(keepends=True)
    consecutive_blank = 0
    is_python = filepath.suffix == ".py"
    prev_was_block_opener = False
    prev_line_text = ""
    in_triple_quote = False

    for line_number, line in enumerate(lines, start=1):
        stripped_line = line.rstrip("\n\r")
        is_blank = stripped_line.strip() == ""

        # Track triple-quoted strings to avoid false CHU005 positives
        # on prose inside docstrings that starts with keywords like
        # "class" or "for".  Count unescaped triple-quote delimiters;
        # an odd count toggles the state.
        if is_python and not is_blank:
            triple_count = stripped_line.count('"""') + stripped_line.count("'''")
            if triple_count % 2 == 1:
                in_triple_quote = not in_triple_quote

        # Track consecutive blank lines for CHU003.
        if is_blank:
            consecutive_blank += 1
        else:
            consecutive_blank = 0

        # CHU003: more than 2 consecutive blank lines.
        if consecutive_blank == 3:
            errors.append(
                f"{relative}:{line_number}: CHU003 "
                f"more than 2 consecutive blank lines"
            )

        # CHU005: blank line immediately after a block opener (Python only).
        # Allowed when the next non-blank line is a ``def`` or ``class``
        # — that pattern (blank line before a nested definition) is
        # idiomatic in import-fallback blocks and conditional definitions.
        # Suppression goes on the block opener line (since the blank line
        # has no code to attach a comment to).
        if is_python and prev_was_block_opener and is_blank:
            if not _has_noqa(prev_line_text, "CHU005"):
                # Look ahead to find the next non-blank line.
                next_content = ""
                for lookahead in lines[line_number:]:
                    candidate = lookahead.strip()
                    if candidate:
                        next_content = candidate
                        break
                if not _DEFINITION.match(next_content):
                    errors.append(
                        f"{relative}:{line_number}: CHU005 "
                        f"blank line after block opener"
                    )

        # Update block-opener tracking for next iteration.
        if is_python and not is_blank and not in_triple_quote:
            prev_was_block_opener = bool(_BLOCK_OPENER.match(stripped_line))
        else:
            prev_was_block_opener = False
        prev_line_text = line

        # CHU004: trailing whitespace (only for files that support noqa).
        if stripped_line != stripped_line.rstrip():
            if is_python and _has_noqa(line, "CHU004"):
                continue
            errors.append(
                f"{relative}:{line_number}: CHU004 trailing whitespace"
            )

    return errors


def check_paths(paths: list[str]) -> int:
    """Check all eligible files under the given paths.

    Args:
        paths: Directories or files to scan.

    Returns:
        Exit code (0 for clean, 1 for violations found).
    """
    all_errors: list[str] = []

    for path_str in paths:
        path = Path(path_str)
        if not path.is_absolute():
            path = ROOT / path
        if path.is_file() and _should_check(path):
            all_errors.extend(check_file(path))
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and _should_check(child):
                    all_errors.extend(check_file(child))

    if all_errors:
        for error in all_errors:
            print(error)
        print(f"\nFound {len(all_errors)} whitespace violation(s).")
        print("Fix: ensure files end with exactly one newline, remove excess")
        print("blank lines, and strip trailing whitespace.")
        print("Rule reference: docs/contributing/style-guide.md (CHU002–CHU005)")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Paths to check. Defaults to the same paths ruff scans.
    """
    paths = argv if argv else [str(path) for path in discover_ruff_paths()]
    return check_paths(paths)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or None))
