"""CHU030: demo drivers may only reach for the deploy_api, and must pin flash mode.

``demos/<name>/driver.py`` is the front door for an agent or human
running a demo against real hardware.  Two contracts
hold for any file under ``demos/<name>/`` (driver or otherwise):

1. **Forbidden imports.**  A demo file may not reach across the
   workspace boundary into the deploy plumbing.  That's exactly the
   duplication ``chumicro_workspace.deploy_api`` exists to absorb.
   The demo's surface is the public API + a small allow-list of
   host helpers, never the internal modules below it.

2. **`deploy_mode="flash"` enforcement.**  A demo's whole point is to
   show how a real project deploys; if a per-device ``deploy_mode: ram``
   override in the user's ``devices.yml`` flips the demo to RAM mode,
   the demo is no longer demonstrating the production path.  Any
   ``deploy_project(...)`` call inside a demo file must pass
   ``deploy_mode="flash"`` as a literal.  Non-literal values (e.g.
   ``deploy_mode=args.mode``) are allowed (the demo author has taken
   explicit responsibility) but missing the kwarg entirely is not (the
   default of ``None`` defers to devices.yml).

Forbidden imports:

- ``chumicro_deploy`` and any submodule.
- ``chumicro_workspace.pipeline``
- ``chumicro_workspace.deploy_source``
- ``chumicro_workspace.import_graph``
- ``chumicro_workspace.device_orchestration``
- ``chumicro_workspace.device_runner``

Allowed imports (in addition to the stdlib):

- ``chumicro_workspace.deploy_api`` (the public API).
- ``chumicro_workspace.markers`` (for ``Marker`` / ``MarkerTimeoutError``
  type imports in ``except`` clauses).
- ``chumicro_pytest_device.fixtures.*`` (the Mosquitto spawner, the
  LAN-IP detector: host helpers, not deploy plumbing).
- Any device-side library imported as a CPython counterparty
  (``chumicro_mqtt``, ``chumicro_sockets``, ``chumicro_http_server``,
  etc.) plus their substrate (``chumicro_timing``, ``chumicro_config``).

Self-scope: ``<repo_root>/demos``.  Absent (a downstream workspace),
no findings.

Suppression: ``# noqa: CHU030`` on the offending line.
"""

from __future__ import annotations

import ast
from pathlib import Path

from chumicro_checks._ast import parse_or_syntax_finding
from chumicro_checks._finding import Finding
from chumicro_checks._rule import Rule

_RULE_CODE = "CHU030"
_NOQA_TAG = "noqa: " + _RULE_CODE

#: Module names (or prefixes) demos may not import.  An import like
#: ``from chumicro_deploy.X import Y`` matches the ``chumicro_deploy``
#: prefix; a bare ``import chumicro_deploy`` matches the exact name.
_FORBIDDEN_PREFIXES: tuple[tuple[str, str], ...] = (
    ("chumicro_deploy", "chumicro_workspace.deploy_api.deploy_project"),
    ("chumicro_workspace.pipeline",
     "chumicro_workspace.deploy_api (composes runtime_config internally)"),
    ("chumicro_workspace.deploy_source",
     "chumicro_workspace.deploy_api (handles staging internally)"),
    ("chumicro_workspace.import_graph",
     "chumicro_workspace.deploy_api (walks imports internally)"),
    ("chumicro_workspace.device_orchestration",
     "chumicro_workspace.deploy_api.deploy_project"),
    ("chumicro_workspace.device_runner",
     "chumicro_workspace.deploy_api.deploy_project "
     "(DeployedProject wraps DeviceBootstrapRunner)"),
)


def _is_forbidden_module(module_name: str) -> tuple[bool, str]:
    """Return ``(is_forbidden, suggested_replacement)`` for *module_name*."""
    for prefix, replacement in _FORBIDDEN_PREFIXES:
        if module_name == prefix or module_name.startswith(prefix + "."):
            return True, replacement
    return False, ""


def _line_has_noqa(source_lines: list[str], lineno: int) -> bool:
    """Return ``True`` when the offending line carries the ``# noqa`` tag."""
    if lineno < 1 or lineno > len(source_lines):
        return False
    return _NOQA_TAG in source_lines[lineno - 1]


def _is_deploy_project_call(node: ast.Call) -> bool:
    """Return ``True`` when *node* is a call to ``deploy_project(...)``.

    Matches both ``deploy_project(...)`` (after a from-import) and
    ``deploy_api.deploy_project(...)`` (after a module import).
    """
    func = node.func
    if isinstance(func, ast.Name) and func.id == "deploy_project":
        return True
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "deploy_project"
    ):
        return True
    return False


def _check_deploy_mode_kwarg(node: ast.Call) -> str | None:
    """Return an error message when the ``deploy_mode`` kwarg is wrong, else None.

    Rules:
    - Missing kwarg: error (the default of None defers to devices.yml).
    - Literal `"flash"`: ok.
    - Literal anything else: error.
    - Non-literal (e.g. `args.mode`): allowed.
    """
    deploy_mode_arg: ast.AST | None = None
    for keyword in node.keywords:
        if keyword.arg == "deploy_mode":
            deploy_mode_arg = keyword.value
            break

    if deploy_mode_arg is None:
        return (
            "deploy_project(...) in a demo must pass deploy_mode=\"flash\" "
            "explicitly; the None default defers to devices.yml resolution, "
            "which can flip the demo to RAM mode."
        )

    if isinstance(deploy_mode_arg, ast.Constant):
        if deploy_mode_arg.value == "flash":
            return None
        return (
            f"deploy_project(deploy_mode={deploy_mode_arg.value!r}) in a "
            f"demo must pass deploy_mode=\"flash\"; demos exist to show "
            f"the production-shaped path."
        )

    # Non-literal value (Name / Attribute / etc.): the demo author has
    # taken explicit responsibility for the runtime decision.  Allowed.
    return None


def _check_file(filepath: Path) -> list[Finding]:
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    source_lines = text.splitlines()

    tree, syntax_findings = parse_or_syntax_finding(text, filepath, _RULE_CODE)
    if tree is None:
        return syntax_findings

    findings: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                forbidden, replacement = _is_forbidden_module(alias.name)
                if forbidden and not _line_has_noqa(source_lines, node.lineno):
                    findings.append(
                        Finding(
                            path=filepath,
                            line=node.lineno,
                            code=_RULE_CODE,
                            message=(
                                f"demo imports {alias.name!r}: use "
                                f"{replacement} instead"
                            ),
                        ),
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            forbidden, replacement = _is_forbidden_module(node.module)
            if forbidden:
                if not _line_has_noqa(source_lines, node.lineno):
                    findings.append(
                        Finding(
                            path=filepath,
                            line=node.lineno,
                            code=_RULE_CODE,
                            message=(
                                f"demo imports from {node.module!r}: use "
                                f"{replacement} instead"
                            ),
                        ),
                    )
                continue
            # ``from chumicro_workspace import pipeline`` imports a
            # forbidden submodule as a member of an allowed parent
            # package: ``node.module`` alone is fine, so test each
            # member's qualified ``parent.member`` name too.
            for alias in node.names:
                qualified = f"{node.module}.{alias.name}"
                member_forbidden, replacement = _is_forbidden_module(qualified)
                if member_forbidden and not _line_has_noqa(
                    source_lines, node.lineno,
                ):
                    findings.append(
                        Finding(
                            path=filepath,
                            line=node.lineno,
                            code=_RULE_CODE,
                            message=(
                                f"demo imports {qualified!r}: use "
                                f"{replacement} instead"
                            ),
                        ),
                    )
        elif isinstance(node, ast.Call) and _is_deploy_project_call(node):
            message = _check_deploy_mode_kwarg(node)
            if message is not None and not _line_has_noqa(
                source_lines, node.lineno,
            ):
                findings.append(
                    Finding(
                        path=filepath,
                        line=node.lineno,
                        code=_RULE_CODE,
                        message=message,
                    ),
                )

    return findings


class CHU030_DemoSurfaceContract(Rule):
    code = _RULE_CODE
    description = (
        "demo drivers may import only chumicro_workspace.deploy_api "
        "(plus fixtures + counterparty libs) and must pass "
        "deploy_mode=\"flash\" to deploy_project()"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        demos = repo_root / "demos"
        if not demos.is_dir():
            return []
        findings: list[Finding] = []
        for filepath in sorted(demos.rglob("*.py")):
            findings.extend(_check_file(filepath))
        return findings


CHU030 = CHU030_DemoSurfaceContract()
