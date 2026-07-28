"""CHU036: device code must not use subscript dunders as attributes.

``obj.__setitem__(k, v)`` / ``obj.__getitem__(k)`` / ``obj.__delitem__(k)``
work on CPython, where every built-in type exposes its dunders as
attributes.  CircuitPython and MicroPython do not: on a board,
``list.__setitem__`` raises ``AttributeError: 'list' object has no
attribute '__setitem__'``.  The idiom slips past ``verify-examples``,
which only import-checks, so it surfaces only when the line runs on a
device (a QoS-1 publish callback did exactly this and stormed both an
RP2040 and an ESP32-S2).

The call form ``x.__setitem__(k, v)`` and a bare reference ``h =
x.__setitem__`` both fail: the ``AttributeError`` is raised at the
attribute access, whether it is called inline or captured and called
later.  A ``super()`` / ``self`` / ``cls`` receiver is exempt, since those
bind a user-defined class, which does expose its own dunders on-device
(and if the class did not define the dunder the access would already
fail on CPython, which the host suites catch).

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
    """Return whether *node* is a ``super()`` / ``super(Cls, self)`` call."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "super"
    )


#: Receiver names that always bind a user-defined class, never a built-in.
#: A user class (unlike list / dict / bytearray) exposes its own subscript
#: dunders as attributes on CircuitPython / MicroPython, so ``self`` / ``cls``
#: receivers are safe.  If the enclosing class did not define the dunder the
#: access would already fail on CPython, so the host suites catch that.
_SAFE_RECEIVER_NAMES = frozenset({"self", "cls"})


def _has_safe_receiver(receiver: ast.expr) -> bool:
    """Return whether *receiver*'s subscript dunders are attribute-accessible
    on-device.

    ``super()`` delegates to a user-defined parent method rather than a
    built-in attribute; ``self`` / ``cls`` bind a user-defined class, which
    exposes its own dunders.  Any other receiver (a bare name, a subscript,
    another attribute) could be a built-in list / dict / bytearray, which
    does not, so it stays in scope.
    """
    if _is_super_call(receiver):
        return True
    return isinstance(receiver, ast.Name) and receiver.id in _SAFE_RECEIVER_NAMES


def _banned_dunder_lines(tree: ast.AST) -> list[int]:
    """Return the line of every ``<receiver>.<banned dunder>`` reference.

    Catches both the call form ``x.__setitem__(k, v)`` and a bare attribute
    reference such as ``handler = x.__setitem__``.  Both raise
    ``AttributeError`` on a built-in receiver on-device, whether the
    attribute is invoked immediately or captured and called later.
    Receivers whose dunders are attribute-accessible on-device are excluded
    (see :func:`_has_safe_receiver`).
    """
    lines: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in _BANNED_DUNDERS
            and not _has_safe_receiver(node.value)
        ):
            lines.append(node.lineno)
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
        for line_number in _banned_dunder_lines(tree):
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
                        "device code uses a subscript dunder as an "
                        "attribute; CircuitPython / MicroPython don't expose "
                        "it on built-in types (AttributeError on-device, "
                        "whether called inline or captured for later). "
                        "Use obj[key] = value / obj[key] / del obj[key]"
                    ),
                )
            )
        return findings


CHU036 = CHU036_DeviceDunderSubscript()
