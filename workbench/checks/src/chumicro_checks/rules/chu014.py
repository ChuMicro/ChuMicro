"""CHU014: workspace CLI command-table parity.

The ``chumicro-workspace`` README documents every subcommand in a
``| Group | Commands |`` table.  That table drifts every time a
subparser is added or removed without the README catching up: phantom
commands (documented but not registered) and hidden commands
(registered but not documented).  Prose lockstep doesn't catch it;
this rule does.

Two surfaces, compared by top-level command name:

* **Registered**: AST-extracted ``subparsers.add_parser("<name>")``
  calls under ``workbench/workspace/src/chumicro_workspace/cli/``.
  Only calls whose receiver is a function parameter typed
  ``argparse._SubParsersAction`` (by convention named ``subparsers``)
  count. A nested ``verbs.add_parser("list")`` for ``library``'s
  sub-verbs is registered against a different object and is *not* a
  top-level command.
* **Documented**: the leading command-shaped token of every
  backtick span in the ``Commands`` column of the README table.  A
  span like ``new --library <name>`` documents ``new``; a prose
  backtick like ``workspace.yml`` or ``quality:`` is not
  command-shaped and is ignored.

Findings:

* documented but not registered: phantom command.
* registered but not documented: hidden command.

Scope: ``workbench/workspace/`` only.  Absent CLI dir or README (a
downstream workspace, the workspace-template repo), a silent no-op.

Suppression: ``<!-- noqa: CHU014 -->`` on the offending README row
(phantom) or on the table header row (hidden).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule
from chumicro_checks._walker import iter_text_files

_RULE_CODE = "CHU014"

_CLI_DIR = Path("workbench/workspace/src/chumicro_workspace/cli")
_README = Path("workbench/workspace/README.md")

#: argparse type annotation that marks a parameter as the subparsers
#: object top-level commands are registered against.
_SUBPARSERS_ANNOTATION = "_SubParsersAction"

#: A command-shaped leading token inside a backtick span: lowercase,
#: digits and hyphens, bounded by end-of-span / whitespace / an arg
#: placeholder (``[`` / ``<``) / an escaped table pipe / ``)``.  The
#: boundary lookahead rejects ``workspace.yml`` (``.``) and
#: ``quality:`` (``:``) so table prose doesn't read as a command.
_COMMAND_TOKEN = re.compile(r"^([a-z][a-z0-9-]+)(?=$|\s|\[|<|\\\||\))")

#: Backtick span inside a markdown table cell.
_BACKTICK_SPAN = re.compile(r"`([^`]+)`")

#: A markdown table column separator: a ``|`` not escaped as ``\|``.
#: GFM cells legitimately contain ``\|`` (e.g. a command spelled
#: ``list\|add\|update``). A naive ``split("|")`` would shred them.
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def _annotation_is_subparsers(annotation: ast.expr | None) -> bool:
    if isinstance(annotation, ast.Attribute):
        return annotation.attr == _SUBPARSERS_ANNOTATION
    if isinstance(annotation, ast.Name):
        return annotation.id == _SUBPARSERS_ANNOTATION
    return False


def _subparsers_param_names(tree: ast.Module) -> set[str]:
    """Names of function parameters typed ``argparse._SubParsersAction``.

    Falls back to the project convention (a parameter literally named
    ``subparsers``) so an un-annotated adder is still recognised.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for arg in list(node.args.args) + list(node.args.posonlyargs):
            if arg.arg == "subparsers" or _annotation_is_subparsers(
                arg.annotation,
            ):
                names.add(arg.arg)
    return names


def _registered_commands(cli_dir: Path) -> set[str]:
    commands: set[str] = set()
    for filepath in iter_text_files(cli_dir, suffixes=(".py",)):
        try:
            tree = ast.parse(
                filepath.read_text(encoding="utf-8"), filename=str(filepath),
            )
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        receivers = _subparsers_param_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            if not isinstance(callee, ast.Attribute):
                continue
            if callee.attr != "add_parser":
                continue
            if not (
                isinstance(callee.value, ast.Name)
                and callee.value.id in receivers
            ):
                continue
            if not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(
                first.value, str,
            ):
                commands.add(first.value)
    return commands


def _command_token(span: str) -> str | None:
    match = _COMMAND_TOKEN.match(span.strip())
    return match.group(1) if match else None


def _find_command_table(lines: list[str]) -> int | None:
    """Return the 0-based index of the ``| Group | Commands |`` header.

    ``None`` when the README has no such table.
    """
    header = re.compile(r"^\|\s*group\s*\|\s*commands\s*\|", re.IGNORECASE)
    for index, line in enumerate(lines):
        if header.match(line.strip()):
            return index
    return None


def _documented_commands(
    lines: list[str], header_index: int,
) -> dict[str, list[int]]:
    """Map documented command name to 0-based README line numbers.

    Walks body rows after the header + separator until the table
    ends (a non-pipe line).
    """
    documented: dict[str, list[int]] = {}
    # header at header_index, separator at +1, body from +2.
    for index in range(header_index + 2, len(lines)):
        row = lines[index].strip()
        if not row.startswith("|"):
            break
        cells = [
            cell.strip() for cell in _UNESCAPED_PIPE.split(row.strip("|"))
        ]
        if len(cells) < 2:
            continue
        for span in _BACKTICK_SPAN.findall(cells[1]):
            token = _command_token(span)
            if token is not None:
                documented.setdefault(token, []).append(index)
    return documented


def _check_repo(repo_root: Path) -> list[Finding]:
    cli_dir = repo_root / _CLI_DIR
    readme = repo_root / _README
    if not cli_dir.is_dir() or not readme.is_file():
        return []
    try:
        text = readme.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    lines = text.splitlines()
    header_index = _find_command_table(lines)
    if header_index is None:
        return []

    registered = _registered_commands(cli_dir)
    if not registered:
        return []
    documented = _documented_commands(lines, header_index)

    findings: list[Finding] = []

    # Phantom: documented, never registered.
    for name, line_indexes in sorted(documented.items()):
        if name in registered:
            continue
        for line_index in line_indexes:
            if line_suppresses(lines[line_index], _RULE_CODE):
                continue
            findings.append(
                Finding(
                    path=readme,
                    line=line_index + 1,
                    code=_RULE_CODE,
                    message=(
                        f"command {name!r} is documented in the workspace "
                        f"command table but no subparser registers it "
                        f"(phantom command: delete the row or implement it)"
                    ),
                )
            )

    # Hidden: registered, never documented.
    if not line_suppresses(lines[header_index], _RULE_CODE):
        for name in sorted(registered - set(documented)):
            findings.append(
                Finding(
                    path=readme,
                    line=header_index + 1,
                    code=_RULE_CODE,
                    message=(
                        f"subcommand {name!r} is registered but absent from "
                        f"the workspace command table (hidden command: add "
                        f"it to the table)"
                    ),
                )
            )

    return findings


class CHU014_CommandTableParity(Rule):
    code = _RULE_CODE
    description = (
        "workspace CLI command-table parity: no phantom/hidden commands"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        return _check_repo(repo_root)


CHU014 = CHU014_CommandTableParity()
