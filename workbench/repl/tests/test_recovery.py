"""Tests for the chumicro-repl session-start recovery layer."""

from __future__ import annotations

import errno

import pytest
from chumicro_repl import (
    InteractiveReplSession,
    RecoveryPlan,
    ReplFailureKind,
    ReplSessionError,
    classify_session_failure,
    coached_session_start,
    recovery_plan_for,
)
from chumicro_repl.session import ReplSessionDisconnected
from chumicro_repl.testing import FakeSerialPort, FakeTime

RAW_REPL_PROMPT = b"raw REPL; CTRL-B to exit\r\n>"


def _handshake_chunks() -> list[bytes | BaseException]:
    return [b"\r\n", RAW_REPL_PROMPT]


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class TestClassifySessionFailure:
    """Each known failure shape maps to its expected kind."""

    def test_enoent_returns_port_not_found(self):
        error = OSError(errno.ENOENT, "No such file or directory", "/dev/cu.x")
        assert classify_session_failure(error) is ReplFailureKind.PORT_NOT_FOUND

    def test_ebusy_returns_port_busy(self):
        error = OSError(errno.EBUSY, "Resource busy", "/dev/cu.x")
        assert classify_session_failure(error) is ReplFailureKind.PORT_BUSY

    def test_eacces_returns_permission_denied(self):
        error = OSError(errno.EACCES, "Permission denied", "/dev/ttyACM0")
        assert (
            classify_session_failure(error)
            is ReplFailureKind.PORT_PERMISSION_DENIED
        )

    def test_message_substring_falls_through_when_errno_missing(self):
        # pyserial sometimes wraps OSError without preserving errno —
        # the classifier falls back to substring matching.
        error = OSError("could not open port: [Errno 2] No such file or directory")
        assert classify_session_failure(error) is ReplFailureKind.PORT_NOT_FOUND

    def test_busy_substring_without_errno(self):
        error = OSError("device or resource busy")
        assert classify_session_failure(error) is ReplFailureKind.PORT_BUSY

    def test_permission_substring_without_errno(self):
        error = OSError("permission denied opening /dev/ttyACM0")
        assert (
            classify_session_failure(error)
            is ReplFailureKind.PORT_PERMISSION_DENIED
        )

    def test_disconnected_during_handshake_treated_as_not_found(self):
        error = ReplSessionDisconnected(OSError("device gone"))
        assert classify_session_failure(error) is ReplFailureKind.PORT_NOT_FOUND

    def test_unresponsive_raw_repl_recognized(self):
        error = ReplSessionError(
            "raw REPL did not announce itself; got b''"
        )
        assert (
            classify_session_failure(error)
            is ReplFailureKind.RAW_REPL_UNRESPONSIVE
        )

    def test_repl_session_error_with_unknown_message(self):
        error = ReplSessionError("something else went wrong")
        assert classify_session_failure(error) is ReplFailureKind.UNKNOWN

    def test_unknown_oserror_falls_through(self):
        # Errno not in the known set, message has no recognizable pattern.
        error = OSError(errno.EIO, "Input/output error")
        assert classify_session_failure(error) is ReplFailureKind.UNKNOWN

    def test_unrelated_exception_returns_unknown(self):
        # Some random other exception — classifier should not crash.
        error = ValueError("not a session-start failure")
        assert classify_session_failure(error) is ReplFailureKind.UNKNOWN


# ---------------------------------------------------------------------------
# Recovery plans
# ---------------------------------------------------------------------------

class TestRecoveryPlans:
    """Every kind has a plan, every plan has the expected shape."""

    @pytest.mark.parametrize("kind", list(ReplFailureKind))
    def test_every_kind_has_a_plan(self, kind):
        plan = recovery_plan_for(kind)
        assert isinstance(plan, RecoveryPlan)
        assert plan.headline
        assert plan.fix_steps
        assert all(isinstance(step, str) for step in plan.fix_steps)
        assert isinstance(plan.retryable, bool)

    def test_all_current_kinds_are_retryable(self):
        # All current kinds are coachable / recoverable; ``retryable``
        # is kept on the dataclass for forward compatibility with
        # any future hard-failure kind we add (matching deploy's shape).
        for kind in ReplFailureKind:
            assert recovery_plan_for(kind).retryable is True

    def test_port_not_found_plan_mentions_cable_check(self):
        plan = recovery_plan_for(ReplFailureKind.PORT_NOT_FOUND)
        joined = " | ".join(plan.fix_steps).lower()
        assert "cable" in joined or "plug" in joined

    def test_port_busy_plan_names_typical_culprits(self):
        plan = recovery_plan_for(ReplFailureKind.PORT_BUSY)
        joined = " | ".join(plan.fix_steps).lower()
        # At least one of the common holders should appear.
        assert any(name in joined for name in ("mu", "thonny", "screen", "mpremote"))

    def test_permission_plan_mentions_dialout(self):
        plan = recovery_plan_for(ReplFailureKind.PORT_PERMISSION_DENIED)
        assert "dialout" in " | ".join(plan.fix_steps).lower()

    def test_unresponsive_plan_mentions_reset(self):
        plan = recovery_plan_for(ReplFailureKind.RAW_REPL_UNRESPONSIVE)
        assert "reset" in " | ".join(plan.fix_steps).lower()


# ---------------------------------------------------------------------------
# InteractiveReplSession
# ---------------------------------------------------------------------------

class TestInteractiveReplSessionConstruction:
    def test_max_attempts_must_be_positive(self):
        with pytest.raises(ValueError, match="max_attempts must be"):
            InteractiveReplSession("/dev/cu.x", max_attempts=0)


class TestInteractiveReplSessionHappyPath:
    """When the underlying session opens cleanly, the wrapper is transparent."""

    def test_happy_path_returns_inner_session(self):
        port = FakeSerialPort(read_chunks=_handshake_chunks())
        outputs: list[str] = []
        wrapper = InteractiveReplSession(
            "/dev/cu.fake",
            max_attempts=3,
            prompt=lambda _text: "",  # never called on happy path
            output=outputs.append,
            time=FakeTime(),
            port_factory=lambda *_args, **_kwargs: port,
        )
        with wrapper as session:
            assert session is not None
            # Verify the wrapper hands back a usable ReplSession by
            # exec'ing through it (the FakeSerialPort needs an exec
            # response queued up to round-trip; we test that path
            # in the existing test_session.py — here we just confirm
            # the context-manager protocol works).
        assert outputs == []  # no failure messages when the session opens
        assert port.closed


class TestInteractiveReplSessionRecovery:
    """Failures are classified, the plan is printed, retries happen."""

    def test_first_attempt_fails_then_succeeds(self):
        # First port construction raises; second succeeds.  The
        # wrapper should print the recovery plan, prompt the user,
        # and retry — landing at a live session on attempt 2.
        good_port = FakeSerialPort(read_chunks=_handshake_chunks())
        attempts = [OSError(errno.ENOENT, "No such file or directory"), good_port]

        def factory(_address, _baudrate, _timeout):
            entry = attempts.pop(0)
            if isinstance(entry, BaseException):
                raise entry
            return entry

        outputs: list[str] = []
        prompt_calls: list[str] = []

        def prompt(text: str) -> str:
            prompt_calls.append(text)
            return ""  # bare Enter → continue

        wrapper = InteractiveReplSession(
            "/dev/cu.fake",
            max_attempts=3,
            prompt=prompt,
            output=outputs.append,
            time=FakeTime(),
            port_factory=factory,
        )
        with wrapper as session:
            assert session is not None
        assert len(prompt_calls) == 1
        rendered = "\n".join(outputs)
        assert "PORT_NOT_FOUND" not in rendered  # use enum-friendly headline
        assert "port path does not exist" in rendered.lower()
        assert "Attempt 1/3 failed" in rendered

    def test_user_aborts_with_q(self):
        # User types 'q' at the retry prompt — the wrapper re-raises
        # the last error without trying again.
        attempts = [OSError(errno.EBUSY, "Resource busy")]

        def factory(_address, _baudrate, _timeout):
            entry = attempts.pop(0)
            raise entry

        wrapper = InteractiveReplSession(
            "/dev/cu.fake",
            max_attempts=5,
            prompt=lambda _text: "q",
            output=lambda _line: None,
            time=FakeTime(),
            port_factory=factory,
        )
        with pytest.raises(OSError, match="Resource busy"):
            with wrapper:
                pytest.fail("entry should not succeed")

    def test_max_attempts_exhausted_raises(self):
        # Every attempt fails; after max_attempts we re-raise the
        # last error.
        def factory(_address, _baudrate, _timeout):
            raise OSError(errno.ENOENT, "No such file or directory")

        outputs: list[str] = []
        wrapper = InteractiveReplSession(
            "/dev/cu.fake",
            max_attempts=2,
            prompt=lambda _text: "",
            output=outputs.append,
            time=FakeTime(),
            port_factory=factory,
        )
        with pytest.raises(OSError, match="No such file or directory"):
            with wrapper:
                pytest.fail("entry should not succeed")
        # Two failure reports, since both attempts failed.
        rendered = "\n".join(outputs)
        assert rendered.count("Attempt 1/2 failed") == 1
        assert rendered.count("Attempt 2/2 failed") == 1

    def test_unresponsive_raw_repl_classified(self):
        # Port opens, but the handshake never gets a prompt → the
        # session raises ReplSessionError, classifier picks
        # RAW_REPL_UNRESPONSIVE.  Then a follow-up port gives a
        # clean handshake.
        bad_port = FakeSerialPort(read_chunks=[b"garbage\r\n>"])
        good_port = FakeSerialPort(read_chunks=_handshake_chunks())
        attempts = [bad_port, good_port]

        def factory(_address, _baudrate, _timeout):
            return attempts.pop(0)

        outputs: list[str] = []
        wrapper = InteractiveReplSession(
            "/dev/cu.fake",
            max_attempts=3,
            prompt=lambda _text: "",
            output=outputs.append,
            time=FakeTime(),
            port_factory=factory,
            connect_timeout=0.05,
        )
        with wrapper as session:
            assert session is not None
        rendered = "\n".join(outputs).lower()
        assert "raw-repl handshake" in rendered
        assert bad_port.closed
        assert good_port.closed

    def test_each_abort_keyword_works(self):
        # Verify each abort word actually aborts.
        for keyword in ("q", "quit", "abort", "exit", "QUIT"):
            calls = [0]

            def factory(_a, _b, _c, _calls=calls):
                _calls[0] += 1
                raise OSError(errno.ENOENT, "missing")

            wrapper = InteractiveReplSession(
                "/dev/cu.fake",
                max_attempts=5,
                prompt=lambda _text, _kw=keyword: _kw,
                output=lambda _line: None,
                time=FakeTime(),
                port_factory=factory,
            )
            with pytest.raises(OSError):
                with wrapper:
                    pytest.fail("should abort")
            assert calls[0] == 1, (
                f"abort keyword {keyword!r} did not stop after first attempt"
            )


class TestInteractiveReplSessionExitClosesInner:
    """``__exit__`` proxies to the wrapped session so the port closes."""

    def test_exit_closes_underlying_port(self):
        port = FakeSerialPort(read_chunks=_handshake_chunks())
        wrapper = InteractiveReplSession(
            "/dev/cu.fake",
            max_attempts=1,
            prompt=lambda _text: "",
            output=lambda _line: None,
            time=FakeTime(),
            port_factory=lambda *_args, **_kwargs: port,
        )
        with wrapper:
            assert not port.closed
        assert port.closed


class TestCoachedSessionStart:
    """The reusable coaching loop wraps any zero-arg callable."""

    def test_first_attempt_success_passes_through(self):
        """Happy path: callable returns on first try, no coaching emitted."""
        outputs: list[str] = []
        result = coached_session_start(
            lambda: 42,
            output=outputs.append,
            prompt=lambda _text: "",
        )
        assert result == 42
        # No retry coaching should have rendered.
        assert outputs == []

    def test_classify_path_invokes_recovery_plan(self):
        # First attempt raises ENOENT, second succeeds.
        attempts = iter([
            (False, OSError(errno.ENOENT, "missing")),
            (True, "session-handle"),
        ])

        def callable_under_test():
            ok, payload = next(attempts)
            if not ok:
                raise payload
            return payload

        outputs: list[str] = []
        result = coached_session_start(
            callable_under_test,
            output=outputs.append,
            prompt=lambda _text: "",
        )
        assert result == "session-handle"
        rendered = "\n".join(outputs).lower()
        assert "port path does not exist" in rendered
        assert "attempt 1" in rendered

    def test_user_aborts(self):
        def callable_under_test():
            raise OSError(errno.EBUSY, "busy")

        with pytest.raises(OSError, match="busy"):
            coached_session_start(
                callable_under_test,
                output=lambda _line: None,
                prompt=lambda _text: "q",
                max_attempts=5,
            )

    def test_max_attempts_zero_rejected(self):
        with pytest.raises(ValueError, match="max_attempts"):
            coached_session_start(
                lambda: None,
                output=lambda _line: None,
                prompt=lambda _text: "",
                max_attempts=0,
            )

    def test_replsessionerror_handled(self):
        # ReplSessionError is one of the catch-classes the loop
        # routes through the classifier — verify it doesn't escape
        # uncoached on attempt 1, and the second attempt completes.
        attempts = iter([
            (False, ReplSessionError("raw REPL did not announce itself")),
            (True, "ok"),
        ])

        def callable_under_test():
            ok, payload = next(attempts)
            if not ok:
                raise payload
            return payload

        outputs: list[str] = []
        result = coached_session_start(
            callable_under_test,
            output=outputs.append,
            prompt=lambda _text: "",
        )
        assert result == "ok"
        assert any("raw-REPL handshake" in line for line in outputs)

    def test_unrelated_exception_bubbles_unchanged(self):
        def callable_under_test():
            raise RuntimeError("not a session-start failure")

        with pytest.raises(RuntimeError, match="not a session-start"):
            coached_session_start(
                callable_under_test,
                output=lambda _line: None,
                prompt=lambda _text: "",
            )
