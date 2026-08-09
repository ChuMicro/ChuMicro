"""Check the template's ownership docs against the zone tables.

The workspace template restates the two-zone ownership contract from
:mod:`chumicro_workspace.template_zones` in three prose surfaces: the
``AGENTS.md`` "File ownership" table, the ``CONTRIBUTING.md``  <!-- noqa: CHU006 -->
"``update`` only touches tool-owned files" paragraph, and ``README.md``
lines claiming a directory is tool-owned.
Hand-maintained restatements drift, so this module is the
deterministic check: :func:`collect_zone_doc_drift` parses each
surface and fails loudly when it disagrees with the zone tables.

Contracts checked, per surface:

* ``AGENTS.md``: rows of the "## File ownership" table whose action  <!-- noqa: CHU006 -->
  cell says ``rewrites`` must name exactly the tool-owned paths and
  prefixes; a row saying ``leaves alone`` must not name a tool-owned
  entry.
* ``CONTRIBUTING.md``: the paragraph containing "only touches  <!-- noqa: CHU006 -->
  tool-owned files:" must name every tool-owned entry in backticks,
  and every backticked token after the marker must be a known zone
  entry (tool-owned, declared user-owned, or the ``projects/``
  parent).
* ``README.md``: on any line containing the claim idiom "folder is
  tool-owned", every backticked token ending in ``/`` must be a
  tool-owned directory prefix.

Run it from a template checkout root::

    python -m chumicro_workspace.template_zone_docs .

Exit code ``0`` when the docs match, ``1`` on drift (each finding
printed on its own line), so template CI can gate on it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from chumicro_workspace.template_zones import (
    TOOL_OWNED_PATHS,
    TOOL_OWNED_PREFIXES,
    USER_OWNED_PATHS,
    USER_OWNED_PREFIXES,
)

if TYPE_CHECKING:  # pragma: no cover - type-only
    from collections.abc import Sequence

_AGENTS_FILENAME = "AGENTS.md"  # noqa: CHU006  checked template doc filename
_CONTRIBUTING_FILENAME = "CONTRIBUTING.md"  # noqa: CHU006  checked template doc filename
_README_FILENAME = "README.md"

#: Heading opening the ownership table in the template's agents doc.
_OWNERSHIP_HEADING = "## File ownership"

#: Phrase opening the tool-owned file list in the contributing doc.
_CONTRIBUTING_MARKER = "only touches tool-owned files:"

_BACKTICK_TOKEN = re.compile(r"`([^`]+)`")

#: Every tool-owned zone entry, exact paths and directory prefixes.
_TOOL_OWNED_ENTRIES: frozenset[str] = (
    frozenset(TOOL_OWNED_PATHS) | frozenset(TOOL_OWNED_PREFIXES)
)

#: Tokens the contributing doc's paragraph may name without being
#: tool-owned: the declared user-owned entries plus ``projects/``,
#: the parent directory whose real-project children are user-owned
#: by fallthrough rather than by a declared zone entry.
_CONTRIBUTING_ALLOWED_EXTRAS: frozenset[str] = (
    frozenset(USER_OWNED_PATHS)
    | frozenset(USER_OWNED_PREFIXES)
    | frozenset({"projects/"})
)


def collect_zone_doc_drift(template_root: Path) -> list[str]:
    """Return one finding per disagreement between docs and zone tables.

    Args:
        template_root: Root of a workspace-template checkout holding
            the three checked docs.

    Returns:
        Human-readable findings, empty when every surface matches.
        A checked doc missing from *template_root* is itself a
        finding, never a silent pass.
    """
    findings: list[str] = []
    surfaces = (
        (_AGENTS_FILENAME, _check_agents_ownership_table),
        (_CONTRIBUTING_FILENAME, _check_contributing_list),
        (_README_FILENAME, _check_readme_claims),
    )
    for filename, checker in surfaces:
        path = template_root / filename
        if not path.is_file():
            findings.append(f"{filename}: missing from {template_root}")
            continue
        findings.extend(checker(path.read_text(encoding="utf-8")))
    return findings


def _check_agents_ownership_table(text: str) -> list[str]:
    """Check the "## File ownership" table rows against the zones.

    Parses each table row for its first backticked path token and its
    last cell's action text.  Rows without a backticked first cell
    (the header and separator rows) are skipped.

    Args:
        text: Full text of the template's agents doc.

    Returns:
        Findings: a missing section, an action cell that is neither
        ``rewrites`` nor ``leaves alone``, a ``leaves alone`` row
        naming a tool-owned entry, a tool-owned entry with no
        ``rewrites`` row, or a ``rewrites`` row naming a path the
        zones do not classify tool-owned.
    """
    lines = text.splitlines()
    heading_indexes = [
        index for index, line in enumerate(lines)
        if line.strip() == _OWNERSHIP_HEADING
    ]
    if not heading_indexes:
        return [
            f"{_AGENTS_FILENAME}: no '{_OWNERSHIP_HEADING}' section to "
            "check the ownership table in",
        ]
    findings: list[str] = []
    rewrites: set[str] = set()
    for line in lines[heading_indexes[0] + 1:]:
        if line.startswith("## "):
            break
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 3:
            continue
        token_match = _BACKTICK_TOKEN.search(cells[0])
        if token_match is None:
            continue
        token = token_match.group(1)
        action = cells[-1].lower()
        if "rewrites" in action:
            rewrites.add(token)
        elif "leaves alone" in action:
            if token in _TOOL_OWNED_ENTRIES:
                findings.append(
                    f"{_AGENTS_FILENAME}: ownership table says update "
                    f"leaves `{token}` alone, but the zone tables "
                    "classify it tool-owned",
                )
        else:
            findings.append(
                f"{_AGENTS_FILENAME}: ownership table row for `{token}` "
                f"has unrecognized action {cells[-1]!r} (expected "
                "'rewrites' or 'leaves alone')",
            )
    for missing in sorted(_TOOL_OWNED_ENTRIES - rewrites):
        findings.append(
            f"{_AGENTS_FILENAME}: ownership table has no 'rewrites' row "
            f"for tool-owned `{missing}`",
        )
    for extra in sorted(rewrites - _TOOL_OWNED_ENTRIES):
        findings.append(
            f"{_AGENTS_FILENAME}: ownership table says update rewrites "
            f"`{extra}`, but the zone tables do not classify it "
            "tool-owned",
        )
    return findings


def _check_contributing_list(text: str) -> list[str]:
    """Check the "only touches tool-owned files" paragraph's tokens.

    Locates the paragraph (blank-line delimited, whitespace flattened
    so a list wrapped across lines still parses) containing the
    marker phrase, then compares its backticked tokens after the
    marker to the zone tables.

    Args:
        text: Full text of the template's contributing doc.

    Returns:
        Findings: a missing marker paragraph, a tool-owned entry the
        list omits, or a token no zone table recognizes.
    """
    for paragraph in re.split(r"\n\s*\n", text):
        flattened = " ".join(paragraph.split())
        marker_index = flattened.find(_CONTRIBUTING_MARKER)
        if marker_index == -1:
            continue
        after_marker = flattened[marker_index + len(_CONTRIBUTING_MARKER):]
        tokens = set(_BACKTICK_TOKEN.findall(after_marker))
        findings = [
            f"{_CONTRIBUTING_FILENAME}: tool-owned `{missing}` is "
            "missing from the 'update only touches' list"
            for missing in sorted(_TOOL_OWNED_ENTRIES - tokens)
        ]
        allowed = _TOOL_OWNED_ENTRIES | _CONTRIBUTING_ALLOWED_EXTRAS
        findings.extend(
            f"{_CONTRIBUTING_FILENAME}: 'update only touches' paragraph "
            f"names `{stray}`, which no zone table recognizes"
            for stray in sorted(tokens - allowed)
        )
        return findings
    return [
        f"{_CONTRIBUTING_FILENAME}: no paragraph contains "
        f"'{_CONTRIBUTING_MARKER}'",
    ]


def _check_readme_claims(text: str) -> list[str]:
    """Check readme lines that claim a directory is tool-owned.

    The readme states directory ownership with the idiom "folder is
    tool-owned".  On every line containing that phrase, each
    backticked token ending in ``/`` is read as the claimed directory
    and must be a tool-owned prefix.  Lines about tool-owned *blocks
    inside* user-owned files, or lines that merely mention a
    subdirectory in passing, lack the phrase and are skipped.  A
    claim worded outside the idiom is invisible here; the table and
    list checks on the other two surfaces remain the authoritative
    gates on the zone sets.

    Args:
        text: Full text of the template's readme.

    Returns:
        One finding per claimed directory the zone tables do not
        list as a tool-owned prefix.
    """
    findings: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if "folder is tool-owned" not in line:
            continue
        for token in _BACKTICK_TOKEN.findall(line):
            if not token.endswith("/"):
                continue
            if token not in TOOL_OWNED_PREFIXES:
                findings.append(
                    f"{_README_FILENAME}:{line_number}: claims `{token}` "
                    "is tool-owned, but the zone tables have no such "
                    "tool-owned directory",
                )
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    """Run the drift check against a template checkout root.

    Args:
        argv: Command-line arguments; ``None`` reads ``sys.argv``.

    Returns:
        ``0`` when every doc surface matches the zone tables, ``1``
        when any finding was printed.
    """
    parser = argparse.ArgumentParser(
        prog="python -m chumicro_workspace.template_zone_docs",
        description=(
            "Check the workspace template's ownership docs against "
            "the tool-owned / user-owned zone tables."
        ),
    )
    parser.add_argument(
        "template_root",
        nargs="?",
        default=Path(),
        type=Path,
        help="Template checkout root (defaults to the current directory).",
    )
    arguments = parser.parse_args(argv)
    findings = collect_zone_doc_drift(arguments.template_root)
    for finding in findings:
        print(f"zone-docs: {finding}", file=sys.stderr)
    if findings:
        return 1
    print("zone-docs: ownership docs match the zone tables.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
