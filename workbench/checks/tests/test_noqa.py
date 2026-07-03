"""Tests for the shared noqa-directive parser."""

from __future__ import annotations

from chumicro_checks._noqa import has_noqa, line_suppresses, strip_noqa


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

    def test_hyphenated_prose_is_not_a_directive(self) -> None:
        # ``# noqa-tracking`` is prose, not a directive: it must not
        # suppress every rule on the line.
        assert line_suppresses("some prose ref  # noqa-tracking", "CHU006") is False

    def test_backticked_mention_is_not_a_directive(self) -> None:
        # A Markdown mention of the mechanism, not a directive.
        assert line_suppresses("the `# noqa` mechanism is explained below", "CHU006") is False

    def test_dotted_prose_is_not_a_directive(self) -> None:
        assert line_suppresses("see config.noqa.setting  # noqa.tracking", "CHU006") is False

    def test_directive_before_second_comment_still_suppresses(self) -> None:
        # A bare directive followed by a why-comment still suppresses.
        assert line_suppresses("x  # noqa  # matching upstream api", "CHU006") is True

    def test_trailing_explanation_after_codes_still_suppresses(self) -> None:
        assert line_suppresses("x  # noqa: CHU006 matching upstream api", "CHU006") is True


class TestHasNoqa:
    def test_code_listed_directive_detected(self) -> None:
        assert has_noqa("x  # noqa: CHU006 - reason") is True

    def test_bare_directive_detected(self) -> None:
        assert has_noqa("x  # noqa") is True

    def test_html_directive_detected(self) -> None:
        assert has_noqa("prose <!-- noqa: CHU012 -->") is True

    def test_no_marker_returns_false(self) -> None:
        assert has_noqa("plain prose with no directive") is False

    def test_hyphenated_prose_not_detected(self) -> None:
        assert has_noqa("follow-up  # noqa-tracking item") is False


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

    def test_hyphenated_prose_left_intact(self) -> None:
        # ``# noqa-tracking`` is not a directive, so strip_noqa leaves it
        # in place — a rule scanning the scrubbed line still sees it.
        text = "some prose ref  # noqa-tracking"
        assert strip_noqa(text) == text
