"""CHU033: no ``async`` / ``await`` / asyncio in first-party package code.

The cooperative-concurrency model is generators (``def`` + ``yield from``)
driven by the runner, not coroutines.  ``async`` / ``await`` and the
``asyncio`` module are banned across ``libraries/``, ``support/``, and
``workbench/``.  On a device the reasons are concrete: ``await`` is not
byte-identical across MicroPython and CircuitPython, the only ``asyncio``
path on CircuitPython has a broken stream layer, and a coroutine-bound
event loop fights the tick-based runner.  The host-side workbench tools
are held to the same rule so the codebase carries one concurrency model;
``functional_tests/`` is the lone carve-out, since its hardware-driving
servers reach asyncio through a PyPI package (the websocket echo server
does) and never run on a device.

Flags, via AST (so the same keywords inside a string literal, for
example a boot-shim error message that *rejects* ``async def run``, are
not hit):
``async def``, ``await``, ``async with``, ``async for``, and
``import`` / ``from`` of ``asyncio`` / ``uasyncio`` / ``_asyncio``.

``scripts/`` is not scanned: it is loose dev tooling, not a packaged
tree.  Suppress with ``# noqa: CHU033`` for a genuine host-only exception.
"""

from __future__ import annotations

import ast
from pathlib import Path

from chumicro_checks._ast import parse_or_syntax_finding
from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule
from chumicro_checks._walker import iter_text_files

_RULE_CODE = "CHU033"

#: Top-level packaged trees the ban covers (the device libraries plus the
#: host-side workbench tools).
_SCOPED_ROOTS: tuple[str, ...] = ("libraries", "support", "workbench")

#: Module names whose import is banned.  A dotted import counts when its
#: first segment is one of these (``asyncio.tasks`` -> ``asyncio``).
_BANNED_MODULES: frozenset[str] = frozenset({"asyncio", "uasyncio", "_asyncio"})


def _in_scope(filepath: Path, repo_root: Path) -> bool:
    """Return whether *filepath* sits in a tree the ban covers.

    ``.py`` files under ``libraries/`` / ``support/`` / ``workbench/``,
    minus any ``functional_tests/`` directory (host-only).
    """
    if filepath.suffix != ".py":
        return False
    try:
        parts = filepath.relative_to(repo_root).parts
    except ValueError:
        return False
    if not parts or parts[0] not in _SCOPED_ROOTS:
        return False
    return "functional_tests" not in parts


def _banned_import_name(name: str) -> bool:
    """Return whether dotted import *name* names a banned asyncio module."""
    return name.split(".", 1)[0] in _BANNED_MODULES


def _violations(tree: ast.Module) -> list[tuple[int, str]]:
    """Return ``(lineno, what)`` for every banned async construct in *tree*."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            found.append((node.lineno, "async def"))
        elif isinstance(node, ast.Await):
            found.append((node.lineno, "await"))
        elif isinstance(node, ast.AsyncWith):
            found.append((node.lineno, "async with"))
        elif isinstance(node, ast.AsyncFor):
            found.append((node.lineno, "async for"))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if _banned_import_name(alias.name):
                    found.append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None and _banned_import_name(node.module):
                found.append((node.lineno, f"from {node.module} import ..."))
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
    for lineno, what in _violations(tree):
        line = source_lines[lineno - 1] if lineno <= len(source_lines) else ""
        if line_suppresses(line, _RULE_CODE):
            continue
        findings.append(
            Finding(
                path=filepath,
                line=lineno,
                code=_RULE_CODE,
                message=(
                    f"{what} is banned; use generators (def + yield from) "
                    f"driven by the runner, not coroutines"
                ),
            )
        )
    return findings


class CHU033_NoAsyncAwait(Rule):
    code = _RULE_CODE
    description = (
        "no async / await / asyncio in first-party package code: use generators"
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


CHU033 = CHU033_NoAsyncAwait()
