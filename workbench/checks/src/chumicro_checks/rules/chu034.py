"""CHU034: device-staging primitives are ``chumicro_deploy``-internal.

Exactly one orchestrator places a code payload on a board:
``Deployer.deploy_diff()``.  It is built from three lower-level
transport primitives: ``deploy_files`` (write the payload and run its
entrypoint) and the diff-reconcile pair ``list_files_in_scope`` +
``delete_files`` (find and remove the stale files a fresh deploy
replaces).  Those three are called only from inside the
``chumicro_deploy`` package that owns the orchestrator.  A call to any
of them from any other first-party module is a second device-staging
path, the exact drift that lets a command grow its own delete scope or
its own write-then-run sequence that diverges from the one pipeline.
Every consumer stages code by calling ``Deployer.deploy_diff()``.

The harness-over-REPL staging contract (``stage``), the once-per-session
entrypoint clear (``clear_entrypoints``), and the standalone destructive
erase (``wipe_filesystem``) are a separate, legitimate axis and are not
reserved here.

Flags, via AST, every ``<obj>.deploy_files(...)`` /
``<obj>.delete_files(...)`` / ``<obj>.list_files_in_scope(...)`` call in
``.py`` files under ``libraries/``, ``support/``, and ``workbench/``,
except the ``workbench/deploy/`` tree (the ``chumicro_deploy`` package,
where the primitives live and are orchestrated).  Matching is by method
name, so the reserved names must not be reused for an unrelated method
in scope; suppress a genuine exception with ``# noqa: CHU034``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from chumicro_checks._ast import parse_or_syntax_finding
from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule
from chumicro_checks._walker import iter_text_files

_RULE_CODE = "CHU034"

#: Top-level packaged trees the reservation covers.
_SCOPED_ROOTS: tuple[str, ...] = ("libraries", "support", "workbench")

#: The blessed home: the two-part path prefix of the ``chumicro_deploy``
#: package tree, which defines and orchestrates the primitives.
_BLESSED_PREFIX: tuple[str, str] = ("workbench", "deploy")

#: Transport method names reserved to the one deploy pipeline.  Each is
#: a step ``Deployer.deploy_diff()`` performs; a direct call elsewhere is
#: a competing staging path.
_RESERVED_PRIMITIVES: frozenset[str] = frozenset(
    {"deploy_files", "delete_files", "list_files_in_scope"},
)


def _in_scope(filepath: Path, repo_root: Path) -> bool:
    """Return whether *filepath* sits in a tree the reservation covers.

    ``.py`` files under ``libraries/`` / ``support/`` / ``workbench/``,
    minus the ``workbench/deploy/`` package that owns the primitives.
    """
    if filepath.suffix != ".py":
        return False
    try:
        parts = filepath.relative_to(repo_root).parts
    except ValueError:
        return False
    if not parts or parts[0] not in _SCOPED_ROOTS:
        return False
    return parts[:2] != _BLESSED_PREFIX


def _violations(tree: ast.Module) -> list[tuple[int, str]]:
    """Return ``(lineno, method)`` for every reserved-primitive call."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _RESERVED_PRIMITIVES
        ):
            found.append((node.lineno, node.func.attr))
    return found


def _check_file(filepath: Path, repo_root: Path) -> list[Finding]:
    if not _in_scope(filepath, repo_root):
        return []
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    tree, syntax_findings = parse_or_syntax_finding(text, filepath, _RULE_CODE)
    if tree is None:
        return syntax_findings
    source_lines = text.splitlines()
    findings: list[Finding] = []
    for lineno, method in _violations(tree):
        line = source_lines[lineno - 1] if lineno <= len(source_lines) else ""
        if line_suppresses(line, _RULE_CODE):
            continue
        findings.append(
            Finding(
                path=filepath,
                line=lineno,
                code=_RULE_CODE,
                message=(
                    f"{method}() is a device-staging primitive reserved to "
                    f"chumicro_deploy; stage code through "
                    f"Deployer.deploy_diff() instead of calling it directly"
                ),
            )
        )
    return findings


class CHU034_OneDeviceStagingPath(Rule):
    code = _RULE_CODE
    description = (
        "device-staging primitives are chumicro_deploy-internal: "
        "stage code through Deployer.deploy_diff()"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        findings: list[Finding] = []
        for root_name in _SCOPED_ROOTS:
            root = repo_root / root_name
            if not root.is_dir():
                continue
            for filepath in iter_text_files(root, suffixes=(".py",)):
                findings.extend(_check_file(filepath, repo_root))
        return findings


CHU034 = CHU034_OneDeviceStagingPath()
