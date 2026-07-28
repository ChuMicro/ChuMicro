"""``chumicro-checks`` command-line interface.

Discovers the repo root (the nearest ancestor with a ``pyproject.toml``
or ``.git``), loads ``[tool.chumicro-checks]`` config from that file,
runs every registered rule whose code is not in the active ignore
set, and prints findings in the standard
``<path>:<line>: <code> <message>`` shape.

Resolution order (most specific wins):

1. CLI ``--select``: if given, only those codes run.
2. CLI ``--ignore``: codes to skip on top of (1) or the registry default.
3. ``[tool.chumicro-checks].ignore``: repo-level default ignore list.

So ``--select CHU006`` runs CHU006 ignoring everything else and
ignoring config. ``--ignore CHU012`` adds CHU012 to whatever the
config already skips. Running with no flags applies just the
config's defaults.

Exit codes::

    0   no findings
    1   one or more findings
    2   usage error: an unknown ``--select`` / ``--ignore`` rule code,
        or an auto-discovered root with no workspace marker that linted
        nothing

A malformed ``pyproject.toml`` is not caught here: ``load_config``
lets ``tomllib.TOMLDecodeError`` propagate, so the interpreter exits 1
with the parse traceback rather than this ``2``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from chumicro_checks import registered_rules
from chumicro_checks._config import load_config


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


def _is_workspace_root(path: Path) -> bool:
    """Return whether *path* looks like a real workspace / repo root.

    A workspace root carries a ``.git`` checkout or the ``workspace.yml``
    marker.  Every package directory in the mono-repo has a
    ``pyproject.toml`` but neither of those, so nearest-ancestor
    discovery run from inside a package lands on the package, not the
    workspace, a green exit against a tree with no ``libraries/`` /
    ``plans/`` / ``AGENTS.md`` to lint.  This distinguishes the two.
    """
    return (path / ".git").exists() or (path / "workspace.yml").is_file()


def _parse_codes(raw: str | None) -> set[str]:
    """Split a comma-separated rule-code list into a normalized set."""
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

    cli_select = _parse_codes(args.select)
    cli_ignore = _parse_codes(args.ignore)

    unknown_cli = (cli_select | cli_ignore) - set(rules)
    if unknown_cli:
        print(
            f"chumicro-checks: unknown rule code(s): {', '.join(sorted(unknown_cli))}",
            file=sys.stderr,
        )
        return 2

    repo_root = (args.root or _find_repo_root(Path.cwd())).resolve()

    # Nearest-ancestor discovery from inside a package directory lands on
    # that package (it has a pyproject.toml), not the workspace.  When
    # the root was auto-discovered and carries no workspace marker, say
    # so on stderr so a green exit isn't mistaken for a clean workspace.
    root_is_suspect = args.root is None and not _is_workspace_root(repo_root)
    if root_is_suspect:
        print(
            f"chumicro-checks: resolved workspace root to {repo_root}, which "
            f"carries no workspace marker (.git or workspace.yml).  If this is "
            f"not the workspace root, run from it or pass --root.",
            file=sys.stderr,
        )

    config = load_config(repo_root)

    # CLI --select overrides config's ignore list entirely.
    # Otherwise CLI --ignore extends the config's ignore.
    if cli_select:
        active_codes = cli_select - cli_ignore
    else:
        active_codes = set(rules) - (config.ignore | cli_ignore)

    findings = []
    for code in sorted(active_codes):
        findings.extend(rules[code].check(repo_root))

    if not findings:
        # A suspect root that produced no findings almost certainly
        # linted nothing; exit non-zero so the empty pass isn't read as
        # a clean workspace.
        return 2 if root_is_suspect else 0

    for finding in findings:
        print(finding.render(root=repo_root))
    return 1
