"""Tests for strip_comments.py — the clean-room comment/docstring stripper."""

from __future__ import annotations

import ast

import pytest
import strip_comments
from strip_comments import _strip_comments, strip_file


def _string_value(source: str):
    """Return the value of the single module-level string assignment."""
    return ast.literal_eval(ast.parse(source).body[0].value)


class TestStripComments:
    """Tests for the tokenize-based comment scanner."""

    def test_drops_full_line_comment(self):
        assert _strip_comments("# hi\nx = 1\n") == "x = 1\n"

    def test_strips_inline_comment_keeps_code(self):
        assert _strip_comments("x = 1  # set x\n") == "x = 1\n"

    def test_preserves_lint_exception_comment(self):
        source = "x = 1  # noqa: E501\n"
        assert _strip_comments(source) == source

    def test_preserves_full_line_lint_exception(self):
        source = "# pragma: no cover\nx = 1\n"
        assert _strip_comments(source) == source

    def test_hash_inside_single_line_string_is_kept(self):
        source = 'url = \"http://x#frag\"\n'
        assert _strip_comments(source) == source


class TestMultilineStringNotCorrupted:
    """The probe's corrupting inputs: a ``#`` inside a multi-line string.

    A per-line scanner that reset its string state each line misread these
    as comments and silently altered the string's value.  tokenize sees the
    whole literal as one STRING token, so no COMMENT is found inside it.
    """

    def test_leading_hash_line_inside_multiline_string(self):
        source = 'BANNER = """\nUsage:\n  # not a comment, part of banner\n  run foo\n"""\n'
        out = strip_file(source)
        assert _string_value(source) == _string_value(out)
        assert "# not a comment" in out

    def test_trailing_hash_inside_multiline_string(self):
        source = 'TEMPLATE = """\nfoo = bar   # looks like a comment\nbaz\n"""\n'
        out = strip_file(source)
        assert _string_value(source) == _string_value(out)
        assert "# looks like a comment" in out


class TestStripFileEquivalenceGuard:
    """strip_file returns the input verbatim when a strip alters code."""

    def test_happy_path_strips_docstrings_and_comments(self):
        source = '"""mod doc."""\nimport os  # noqa: E501\nx = 1  # inline\n'
        out = strip_file(source)
        assert "mod doc" not in out
        assert "# inline" not in out
        assert "# noqa: E501" in out
        assert "import os" in out

    def test_guard_returns_verbatim_when_comment_strip_alters_code(
        self, monkeypatch: pytest.MonkeyPatch,
    ):
        """A comment stripper that mutates code trips the equivalence guard."""
        source = "x = 1\ny = 2\n"

        def corrupting(_source: str) -> str:
            return "x = 999\ny = 2\n"  # alters a literal — parses, but wrong

        monkeypatch.setattr(strip_comments, "_strip_comments", corrupting)
        # Guard detects the code-level mismatch and returns the input as-is.
        assert strip_file(source) == source

    def test_raises_on_unparseable_input(self):
        with pytest.raises(SyntaxError):
            strip_file("def (:\n")
