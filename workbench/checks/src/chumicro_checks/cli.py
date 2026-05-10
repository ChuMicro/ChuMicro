"""``chumicro-checks`` command-line interface.

Discovers the repo root (the nearest ancestor with a ``pyproject.toml``
or ``.git``), runs every registered rule whose code is not in the
ignore set, and prints findings in the standard
``<path>:<line>: <code> <message>`` shape.

Exit codes::

    0   no findings
    1   one or more findings
    2   usage error (unknown rule code, bad config)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from chumicro_checks import registered_rules


def _find_repo_root(start: Path) -> Path:
    """Walk parents of *start* looking for a ``.git`` or ``pyproject.toml``.

    Falls back to *start* itself if neither marker is found before
    the filesystem root.
    """
    candidate = start.resolve()
    for directory in (candidate, *candidate.parents):
        if (directory / ".git").exists() or (directory / "pyproject.toml").exists():
            return directory
    return candidate


def _parse_codes(raw: str | None) -> set[str]:
    """Split a comma-separated rule-code list into a normalised set."""
    if not raw:
        return set()
    return {token.strip().upper() for token in raw.split(",") if token.strip()}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chumicro-checks",
        description=(
            "Workspace-internal lint rules (CHU0NN).  Run from the "
            "repo root, or pass --root to point at one explicitly."
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repo root to lint (default: nearest ancestor with .git or pyproject.toml).",
    )
    parser.add_argument(
        "--select",
        default=None,
        help="Comma-separated rule codes to run (default: every registered rule).",
    )
    parser.add_argument(
        "--ignore",
        default=None,
        help="Comma-separated rule codes to skip.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List every registered rule and exit.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``chumicro-checks`` console script."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    rules = registered_rules()

    if args.list:
        if not rules:
            print("(no rules registered)")
            return 0
        for code, rule in sorted(rules.items()):
            print(f"{code}  {rule.description}")
        return 0

    select = _parse_codes(args.select)
    ignore = _parse_codes(args.ignore)

    unknown = (select | ignore) - set(rules)
    if unknown:
        print(
            f"chumicro-checks: unknown rule code(s): {', '.join(sorted(unknown))}",
            file=sys.stderr,
        )
        return 2

    repo_root = (args.root or _find_repo_root(Path.cwd())).resolve()

    active_codes = (select or set(rules)) - ignore
    findings = []
    for code in sorted(active_codes):
        findings.extend(rules[code].check(repo_root))

    if not findings:
        return 0

    for finding in findings:
        print(finding.render(root=repo_root))
    return 1
