"""Tests for pattern detectors and the streaming detector."""

from __future__ import annotations

from chumicro_repl import PatternKind, detect_patterns
from chumicro_repl.patterns import StreamingPatternDetector

CIRCUITPYTHON_TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "code.py", line 4, in <module>\n'
    "  File \"projects/sensor.py\", line 12, in run\n"
    "ValueError: bad sensor reading\n"
)

MICROPYTHON_TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "main.py", line 7, in <module>\n'
    "  File \"app.py\", line 22, in start\n"
    "OSError: [Errno 2] ENOENT\n"
)

SAFE_MODE_BLOCK = (
    "You are in safe mode because: You pressed the reset button "
    "during boot.\n"
    "Press reset to exit safe mode.\n"
)

HARD_FAULT_BLOCK = (
    "Hard fault: memory access or instruction error.\n"
    "Boot stack: 0x12345678\n"
    "\n"
)

SOFT_REBOOT_BANNER = "MPY: soft reboot\n"


class TestSingleScan:
    """:func:`detect_patterns` recognizes each kind in isolation."""

    def test_circuitpython_traceback(self):
        matches = detect_patterns(CIRCUITPYTHON_TRACEBACK)
        assert len(matches) == 1
        assert matches[0].kind is PatternKind.TRACEBACK
        assert matches[0].text.startswith("Traceback (most recent call last):")
        assert "ValueError" in matches[0].text

    def test_micropython_traceback(self):
        matches = detect_patterns(MICROPYTHON_TRACEBACK)
        assert len(matches) == 1
        assert matches[0].kind is PatternKind.TRACEBACK
        assert "OSError" in matches[0].text

    def test_safe_mode(self):
        matches = detect_patterns(SAFE_MODE_BLOCK)
        assert len(matches) == 1
        assert matches[0].kind is PatternKind.SAFE_MODE
        assert "Press reset" in matches[0].text

    def test_hard_fault(self):
        matches = detect_patterns(HARD_FAULT_BLOCK)
        assert len(matches) == 1
        assert matches[0].kind is PatternKind.HARD_FAULT
        assert "Hard fault" in matches[0].text

    def test_soft_reboot(self):
        matches = detect_patterns(SOFT_REBOOT_BANNER)
        assert len(matches) == 1
        assert matches[0].kind is PatternKind.SOFT_REBOOT

    def test_no_match_returns_empty_list(self):
        assert detect_patterns("normal output line\n") == []


class TestMixedScan:
    """Real REPL streams interleave normal output with patterns."""

    def test_pattern_after_plain_text(self):
        text = (
            "boot complete\n"
            "running app\n"
            f"{CIRCUITPYTHON_TRACEBACK}"
            "main loop done\n"
        )
        matches = detect_patterns(text)
        assert len(matches) == 1
        assert matches[0].kind is PatternKind.TRACEBACK
        # text slice captured in the match should include only the
        # traceback span, not the surrounding plain lines.
        assert "boot complete" not in matches[0].text
        assert "main loop done" not in matches[0].text

    def test_soft_reboot_then_traceback(self):
        text = SOFT_REBOOT_BANNER + "doing projects\n" + MICROPYTHON_TRACEBACK
        matches = detect_patterns(text)
        kinds = [match.kind for match in matches]
        assert kinds == [PatternKind.SOFT_REBOOT, PatternKind.TRACEBACK]
        assert matches[0].start < matches[1].start

    def test_two_tracebacks_in_one_scan(self):
        text = MICROPYTHON_TRACEBACK + "\n" + CIRCUITPYTHON_TRACEBACK
        matches = detect_patterns(text)
        assert len(matches) == 2
        assert all(match.kind is PatternKind.TRACEBACK for match in matches)


class TestStreamingDetector:
    """Streaming detector emits each pattern exactly once."""

    def test_pattern_split_across_two_feeds_still_detected(self):
        detector = StreamingPatternDetector()
        first_part = CIRCUITPYTHON_TRACEBACK[:30]
        second_part = CIRCUITPYTHON_TRACEBACK[30:]
        first_matches = detector.feed(first_part)
        assert first_matches == []
        second_matches = detector.feed(second_part)
        assert len(second_matches) == 1
        assert second_matches[0].kind is PatternKind.TRACEBACK

    def test_pattern_emitted_only_once(self):
        detector = StreamingPatternDetector()
        first_matches = detector.feed(MICROPYTHON_TRACEBACK)
        assert len(first_matches) == 1
        # Append more text — the original traceback must not re-emit.
        next_matches = detector.feed("more output\n")
        assert next_matches == []

    def test_total_fed_tracks_chars(self):
        detector = StreamingPatternDetector()
        detector.feed("abc")
        detector.feed("defg")
        assert detector.total_fed == 7

    def test_match_offsets_are_absolute(self):
        detector = StreamingPatternDetector()
        prefix = "noise before the traceback\n"
        matches = detector.feed(prefix + CIRCUITPYTHON_TRACEBACK)
        assert len(matches) == 1
        assert matches[0].start == len(prefix)
        # text slice equals the absolute slice of the original input.
        captured = (prefix + CIRCUITPYTHON_TRACEBACK)[
            matches[0].start - 0 : matches[0].end - 0
        ]
        assert captured == matches[0].text

    def test_buffer_trim_drops_unmatched_history(self):
        detector = StreamingPatternDetector(buffer_limit=64)
        # Feed more bytes than buffer_limit without any pattern.
        large_payload = "x" * 200
        detector.feed(large_payload)
        # Internal buffer must not retain everything.
        # We do not assert exact size — just bound it.
        assert detector._buffer.__len__() <= 64

    def test_empty_feed_returns_empty(self):
        detector = StreamingPatternDetector()
        assert detector.feed("") == []
        assert detector.total_fed == 0
