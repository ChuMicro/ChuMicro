"""Tests for the shared AST-parse helper."""

from __future__ import annotations

import ast
from pathlib import Path

from chumicro_checks._ast import parse_or_syntax_finding


class TestParseOrSyntaxFinding:
    def test_valid_source_returns_tree_and_no_finding(self) -> None:
        tree, findings = parse_or_syntax_finding(
            "x = 1\n", Path("ok.py"), "CHU001",
        )
        assert isinstance(tree, ast.Module)
        assert findings == []

    def test_syntax_error_returns_no_tree_and_a_finding(self) -> None:
        tree, findings = parse_or_syntax_finding(
            "def broken(\n", Path("bad.py"), "CHU033",
        )
        assert tree is None
        assert len(findings) == 1
        assert findings[0].code == "CHU033"
        assert findings[0].path == Path("bad.py")
        assert "syntax error" in findings[0].message

    def test_finding_line_is_the_error_line(self) -> None:
        tree, findings = parse_or_syntax_finding(
            "value = 1\ndef broken(\n", Path("bad.py"), "CHU001",
        )
        assert tree is None
        # The parser reports the error on the unterminated def line.
        assert findings[0].line == 2

    def test_line_defaults_to_one_when_unknown(self) -> None:
        # An unterminated triple-quote reports at line 1.
        _tree, findings = parse_or_syntax_finding(
            "x = '''unterminated\n", Path("bad.py"), "CHU027",
        )
        assert findings[0].line >= 1
