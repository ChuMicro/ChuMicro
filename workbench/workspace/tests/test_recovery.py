"""Tests for app-level deploy-failure recovery hints."""

from __future__ import annotations

import pytest
from chumicro_workspace.recovery import (
    AppErrorHint,
    detect_hints,
    format_hints,
)


class TestDetectHints:
    def test_empty_input_returns_empty_list(self) -> None:
        assert detect_hints("") == []
        # ``None``-shaped input is the caller's bug, but the function
        # still survives it without raising — falsy → no hints.
        assert detect_hints(None) == []  # type: ignore[arg-type]

    def test_no_match_returns_empty_list(self) -> None:
        traceback = (
            "Traceback (most recent call last):\n"
            '  File "/code.py", line 1, in <module>\n'
            "    1 / 0\n"
            "ZeroDivisionError: division by zero\n"
        )
        assert detect_hints(traceback) == []

    def test_name_error_pattern(self) -> None:
        traceback = (
            "Traceback (most recent call last):\n"
            "  ...\n"
            "NameError: name 'WifiConfig' is not defined\n"
        )
        hints = detect_hints(traceback)
        assert len(hints) == 1
        assert hints[0].pattern_label == "name-error"
        assert "'WifiConfig'" in hints[0].hint
        assert "import" in hints[0].hint.lower()

    def test_ram_mode_runtime_config_pattern(self) -> None:
        traceback = (
            "Traceback (most recent call last):\n"
            "  ...\n"
            "OSError: [Errno 2] ENOENT: '/runtime_config.msgpack'\n"
        )
        hints = detect_hints(traceback)
        labels = [hint.pattern_label for hint in hints]
        assert "ram-mode-config" in labels

    def test_missing_chumicro_lib_pattern(self) -> None:
        traceback = (
            "Traceback (most recent call last):\n"
            "  ...\n"
            "ImportError: no module named 'chumicro_wifi'\n"
        )
        hints = detect_hints(traceback)
        labels = [hint.pattern_label for hint in hints]
        assert "missing-chumicro-lib" in labels
        lib_hint = next(
            hint for hint in hints if hint.pattern_label == "missing-chumicro-lib"
        )
        assert "chumicro_wifi" in lib_hint.hint

    def test_missing_chumicro_lib_modulenotfound_variant(self) -> None:
        """``ModuleNotFoundError`` (Python 3.6+ shape) also matches."""
        traceback = (
            "Traceback (most recent call last):\n"
            "  ...\n"
            "ModuleNotFoundError: No module named 'chumicro_mqtt'\n"
        )
        hints = detect_hints(traceback)
        labels = [hint.pattern_label for hint in hints]
        assert "missing-chumicro-lib" in labels

    def test_missing_config_key_pattern(self) -> None:
        traceback = (
            "Traceback (most recent call last):\n"
            "  ...\n"
            "KeyError: 'wifi'\n"
        )
        hints = detect_hints(traceback)
        labels = [hint.pattern_label for hint in hints]
        assert "missing-config-key" in labels
        key_hint = next(
            hint for hint in hints if hint.pattern_label == "missing-config-key"
        )
        assert "wifi" in key_hint.hint

    def test_each_label_emits_at_most_once(self) -> None:
        """Two `NameError` lines in one traceback yield one hint, not two."""
        traceback = (
            "NameError: name 'foo' is not defined\n"
            "NameError: name 'bar' is not defined\n"
        )
        hints = detect_hints(traceback)
        labels = [hint.pattern_label for hint in hints]
        assert labels.count("name-error") == 1

    def test_multiple_distinct_patterns_all_emit(self) -> None:
        traceback = (
            "ImportError: No module named 'chumicro_wifi'\n"
            "KeyError: 'mqtt'\n"
        )
        hints = detect_hints(traceback)
        labels = sorted(hint.pattern_label for hint in hints)
        assert labels == ["missing-chumicro-lib", "missing-config-key"]


class TestFormatHints:
    def test_empty_returns_empty_string(self) -> None:
        assert format_hints([]) == ""

    def test_renders_header_and_indented_bullets(self) -> None:
        hints = [
            AppErrorHint("name-error", "did you forget to import foo?"),
            AppErrorHint("missing-config-key", "missing config key bar"),
        ]
        text = format_hints(hints)
        lines = text.splitlines()
        assert lines[0] == "--- hints ---"
        assert lines[1] == "  did you forget to import foo?"
        assert lines[2] == "  missing config key bar"


class TestHintTableShape:
    """Sanity-check the table is well-formed (every label unique)."""

    def test_labels_are_unique(self) -> None:
        from chumicro_workspace.recovery import _HINT_TABLE
        labels = [label for _, label, _ in _HINT_TABLE]
        assert len(labels) == len(set(labels)), (
            f"duplicate labels in _HINT_TABLE: {labels}"
        )


class TestUnrelatedOserrorDoesNotMatchRamModeRule:
    """An OSError at a different path shouldn't fire the RAM-mode pattern.

    Regression guard: the RAM-mode hint is anchored on
    `runtime_config.msgpack` specifically — checking a similar
    "missing file" trace at a different path doesn't fire it.
    """

    @pytest.mark.parametrize(
        "trace_line",
        [
            "OSError: [Errno 2] ENOENT: '/lib/projects/foo/some_other.yml'",
            "OSError: [Errno 2] ENOENT: '/lib/projects/foo/app.py'",
        ],
    )
    def test_unrelated_oserror_does_not_match(self, trace_line: str) -> None:
        hints = detect_hints(f"Traceback ...\n{trace_line}\n")
        labels = [hint.pattern_label for hint in hints]
        assert "ram-mode-config" not in labels
