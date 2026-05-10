"""Tests for the shared noqa-directive parser."""

from __future__ import annotations

from chumicro_checks._noqa import line_suppresses, strip_noqa


class TestLineSuppresses:
    def test_specific_code_suppresses(self) -> None:
        assert line_suppresses("some prose  # noqa: CHU006", "CHU006") is True

    def test_unrelated_code_does_not(self) -> None:
        assert line_suppresses("some prose  # noqa: CHU001", "CHU006") is False

    def test_bare_noqa_suppresses_any(self) -> None:
        assert line_suppresses("some prose  # noqa", "CHU006") is True

    def test_bare_noqa_with_only_whitespace_suppresses_any(self) -> None:
        # ``# noqa:   `` (empty code list) still acts like a bare noqa.
        # Constructed at runtime so ruff doesn't read the test fixture as
        # a malformed directive on this source line.
        marker = "# " + "noqa:   "
        assert line_suppresses(f"some prose  {marker}", "CHU006") is True

    def test_html_comment_suppresses(self) -> None:
        assert line_suppresses("some prose <!-- noqa: CHU006 -->", "CHU006") is True

    def test_html_bare_noqa_suppresses_any(self) -> None:
        assert line_suppresses("some prose <!-- noqa -->", "CHU006") is True

    def test_no_marker_returns_false(self) -> None:
        assert line_suppresses("some prose ref", "CHU006") is False

    def test_comma_separated_codes(self) -> None:
        assert line_suppresses("x  # noqa: CHU001, CHU006", "CHU006") is True
        assert line_suppresses("x  # noqa: CHU001, CHU006", "CHU012") is False


class TestStripNoqa:
    def test_strips_python_marker(self) -> None:
        assert strip_noqa("some prose  # noqa: CHU006") == "some prose  "

    def test_strips_html_marker(self) -> None:
        assert (
            strip_noqa("some prose <!-- noqa: CHU006 -->")
            == "some prose "
        )

    def test_no_marker_unchanged(self) -> None:
        assert strip_noqa("some prose ref") == "some prose ref"
