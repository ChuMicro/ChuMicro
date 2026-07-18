"""CHU036: device code must not call subscript dunders as attributes.

``obj.__setitem__(k, v)`` / ``obj.__getitem__(k)`` / ``obj.__delitem__(k)``
work on CPython, where every built-in type exposes its dunders as
attributes.  CircuitPython and MicroPython do not: on a board,
``list.__setitem__`` raises ``AttributeError: 'list' object has no
attribute '__setitem__'``.  The idiom slips past ``verify-examples``,
which only import-checks, so it surfaces only when the line runs on a
device (a QoS-1 publish callback did exactly this and stormed both an
RP2040 and an ESP32-S2).

Use subscript syntax instead: ``obj[k] = v`` / ``obj[k]`` / ``del obj[k]``.
When a lambda needs the assignment, promote it to a named function whose
body can hold the statement.

Scope: device-shipped code only.  Every ``libraries/<name>/src/`` file
(always deployed) plus any file declaring ``__chumicro_runtimes__`` with
``circuitpython`` or ``micropython`` (device examples, apps).  Host-side
code (workbench tooling, scripts, demo drivers, tests) is left alone,
since the attribute form works fine on CPython there.

Self-scope: walks ``libraries/``, ``workbench/``, ``projects/``,
``examples/``, and ``demos/`` under *repo_root*; absent trees are a
silent no-op.

Suppression: ``# noqa: CHU036`` on the offending line.
"""

from __future__ import annotations

import ast
from pathlib import Path

from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule
from chumicro_checks._walker import iter_text_files

_RULE_CODE = "CHU036"

#: Subscript dunders that map to `[]` syntax and are unavailable as
#: attributes on built-in types under CircuitPython / MicroPython.
_BANNED_DUNDERS = frozenset({"__setitem__", "__getitem__", "__delitem__"})

#: Trees that may hold device-shipped code.
_SCAN_ROOTS = ("libraries", "workbench", "projects", "examples", "demos")


def _is_device_file(scope_path: Path, text: str) -> bool:
    """Return whether *scope_path* (repo-relative) ships to a device.

    True for any ``libraries/<name>/src/`` file (always deployed) and for
    any file declaring ``__chumicro_runtimes__`` with a device runtime.
    Host tooling (``workbench/<name>/src/``, scripts, demo drivers) is
    not device code and reads False.
    """
    parts = scope_path.parts
    if len(parts) >= 3 and parts[0] == "libraries" and parts[2] == "src":
        return True
    if "__chumicro_runtimes__" in text and (
        "circuitpython" in text or "micropython" in text
    ):
        return True
    return False


def _is_super_call(node: ast.expr) -> bool:
    """Return whether *node* is a ``super()`` call."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "super"
    )


def _banned_calls(tree: ast.AST) -> list[int]:
    """Return the line of every offending ``x.<banned dunder>(...)`` call.

    ``super().__setitem__(...)`` is excluded: inside a dunder override it
    delegates to a user-defined parent method (not a built-in attribute),
    which is the correct idiom and works on-device.
    """
    lines: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _BANNED_DUNDERS
            and not _is_super_call(node.func.value)
        ):
            lines.append(node.func.lineno)
    return lines


class CHU036_DeviceDunderSubscript(Rule):
    code = _RULE_CODE
    description = (
        "device code must use subscript syntax, not .__setitem__ / "
        ".__getitem__ / .__delitem__ (unavailable on CircuitPython / "
        "MicroPython built-ins)"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        findings: list[Finding] = []
        seen: set[Path] = set()
        for root_name in _SCAN_ROOTS:
            root = repo_root / root_name
            for filepath in iter_text_files(root, suffixes=(".py",)):
                if filepath in seen:
                    continue
                seen.add(filepath)
                findings.extend(self._check_file(filepath, repo_root))
        return findings

    def _check_file(self, filepath: Path, repo_root: Path) -> list[Finding]:
        try:
            text = filepath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        try:
            scope_path = filepath.relative_to(repo_root)
        except ValueError:
            scope_path = filepath
        if not _is_device_file(scope_path, text):
            return []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []

        source_lines = text.splitlines()
        findings: list[Finding] = []
        for line_number in _banned_calls(tree):
            line = (
                source_lines[line_number - 1]
                if 0 < line_number <= len(source_lines)
                else ""
            )
            if line_suppresses(line, self.code):
                continue
            findings.append(
                Finding(
                    path=filepath,
                    line=line_number,
                    code=self.code,
                    message=(
                        "device code calls a subscript dunder as an "
                        "attribute; CircuitPython / MicroPython don't expose "
                        "it on built-in types (AttributeError on-device). "
                        "Use obj[key] = value / obj[key] / del obj[key]"
                    ),
                )
            )
        return findings


CHU036 = CHU036_DeviceDunderSubscript()
