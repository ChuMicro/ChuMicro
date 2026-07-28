"""Shared AST-parse helper for the rules that walk Python syntax trees.

Every AST-based rule (CHU001, CHU007, CHU009 / CHU010, CHU013, CHU015,
CHU016, CHU027, CHU030, CHU033, CHU034) parses each in-scope file with
``ast.parse``.  A file that fails to parse must not silently pass the
rule as clean: :func:`parse_or_syntax_finding` returns a single
"file skipped: syntax error" finding under the calling rule's code in
that case.  So a ``--select CHU0NN`` run over an unparseable file exits
non-zero and names the file, rather than reporting green on a tree it
could not read.
"""

from __future__ import annotations

import ast
from pathlib import Path

from chumicro_checks._finding import Finding


def parse_or_syntax_finding(
    text: str, filepath: Path, code: str,
) -> tuple[ast.Module | None, list[Finding]]:
    """Parse *text*; on ``SyntaxError`` report it under *code*.

    Returns ``(tree, [])`` when *text* parses, or ``(None, [finding])``
    when it does not.  The finding names *filepath* and the line the
    parser reported, so a syntax error surfaces as a rule failure the
    caller can return directly rather than a silent empty result.
    """
    try:
        tree = ast.parse(text, filename=str(filepath))
    except SyntaxError as error:
        line = error.lineno if error.lineno and error.lineno >= 1 else 1
        return None, [
            Finding(
                path=filepath,
                line=line,
                code=code,
                message=(
                    f"file skipped: syntax error ({error.msg}); {code} "
                    f"could not check this file"
                ),
            )
        ]
    return tree, []
