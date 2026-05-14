"""Tests for ANSI highlighting + pattern-aware rendering."""

from __future__ import annotations

import pytest
from chumicro_repl import PatternKind, Theme, colorize
from chumicro_repl.highlight import DEFAULT_THEME, strip_ansi_sequences
from chumicro_repl.patterns import PatternMatch

CIRCUITPYTHON_TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "code.py", line 4, in <module>\n'
    "ValueError: oops\n"
)

SOFT_REBOOT_BANNER = "MPY: soft reboot\n"


class TestRendering:
    """:func:`highlight` wraps detected spans in ANSI escapes."""

    def test_no_match_returns_input_unchanged(self):
        assert colorize("plain output\n") == "plain output\n"

    def test_traceback_gets_red_bold_default(self):
        text = CIRCUITPYTHON_TRACEBACK
        rendered = colorize(text)
        assert rendered != text
        # Default traceback style is "1;31"
        assert "\x1b[1;31m" in rendered
        assert rendered.endswith("\x1b[0m")

    def test_strip_round_trip_recovers_plain_text(self):
        rendered = colorize(CIRCUITPYTHON_TRACEBACK)
        assert strip_ansi_sequences(rendered) == CIRCUITPYTHON_TRACEBACK

    def test_soft_reboot_gets_dim_cyan_default(self):
        rendered = colorize(SOFT_REBOOT_BANNER)
        assert "\x1b[2;36m" in rendered

    def test_explicit_matches_override_detection(self):
        # Pretend the whole string is a hard fault, even though
        # it is plain text — the highlighter trusts the caller.
        text = "anything at all"
        match = PatternMatch(
            kind=PatternKind.HARD_FAULT, start=0, end=len(text), text=text,
        )
        rendered = colorize(text, matches=[match])
        assert rendered.startswith("\x1b[1;41m")
        assert rendered.endswith("\x1b[0m")

    def test_multiple_matches_each_wrapped(self):
        text = SOFT_REBOOT_BANNER + "\n" + CIRCUITPYTHON_TRACEBACK
        rendered = colorize(text)
        # Two spans — at minimum two RESETs.
        assert rendered.count("\x1b[0m") >= 2
        # Plain content is preserved.
        assert "ValueError" in rendered

    def test_overlapping_match_is_skipped(self):
        # Construct a deliberately overlapping pair; the second span
        # starts inside the first and must be skipped to keep escapes
        # balanced.
        text = "AAAABBBB"
        first = PatternMatch(PatternKind.TRACEBACK, 0, 6, text[:6])
        second = PatternMatch(PatternKind.SOFT_REBOOT, 4, 8, text[4:8])
        rendered = colorize(text, matches=[first, second])
        # Two RESETs would mean both wrapped; we expect one (only
        # the first span renders).
        assert rendered.count("\x1b[0m") == 1


class TestThemeOverride:
    """Custom themes change the SGR digits emitted around each kind."""

    def test_custom_traceback_color(self):
        theme = Theme(traceback="32")  # green
        rendered = colorize(CIRCUITPYTHON_TRACEBACK, theme=theme)
        assert "\x1b[32m" in rendered
        assert "\x1b[1;31m" not in rendered

    def test_default_theme_is_module_singleton(self):
        # Sanity — DEFAULT_THEME is the singleton :func:`highlight`
        # uses when no theme is supplied.
        rendered_default = colorize(CIRCUITPYTHON_TRACEBACK)
        rendered_explicit = colorize(CIRCUITPYTHON_TRACEBACK, theme=DEFAULT_THEME)
        assert rendered_default == rendered_explicit


class TestStripAnsiSequences:
    """:func:`strip_ansi_sequences` removes SGR escapes for log capture."""

    @pytest.mark.parametrize(
        "raw",
        [
            "\x1b[31mred\x1b[0m",
            "no escapes here",
            "\x1b[1;33myellow\x1b[0m end",
            "\x1b[2J",  # clear screen — non-SGR but still a CSI sequence
        ],
    )
    def test_no_escape_bytes_remain(self, raw):
        assert "\x1b" not in strip_ansi_sequences(raw)


class TestStyleForFallback:
    """Coverage for :meth:`Theme.style_for` branches."""

    def test_each_kind_returns_its_field(self):
        theme = Theme(
            traceback="1", safe_mode="2", hard_fault="3", soft_reboot="4",
        )
        assert theme.style_for(PatternKind.TRACEBACK) == "1"
        assert theme.style_for(PatternKind.SAFE_MODE) == "2"
        assert theme.style_for(PatternKind.HARD_FAULT) == "3"
        assert theme.style_for(PatternKind.SOFT_REBOOT) == "4"
