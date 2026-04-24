"""Tests for the interactive recovery layer."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from chumicro_deploy.circuitpython_transport import CircuitpythonTransportError
from chumicro_deploy.micropython_transport import MicropythonTransportError
from chumicro_deploy.recovery import (
    DeployFailureKind,
    InteractiveDeployer,
    RecoveryPlan,
    classify_deploy_failure,
    recovery_plan_for,
)
from chumicro_deploy.result import DeployResult

# ---------------------------------------------------------------------------
# classify_deploy_failure — message → kind mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "expected_kind"),
    [
        # Port unavailable family.
        (
            "Failed to open serial port /dev/cu.usbmodem101: [Errno 2] "
            "could not open port",
            DeployFailureKind.PORT_UNAVAILABLE,
        ),
        (
            "Failed to open serial port /dev/ttyUSB0: [Errno 16] "
            "Resource busy: '/dev/ttyUSB0'",
            DeployFailureKind.PORT_UNAVAILABLE,
        ),
        (
            "Failed to open serial port: [Errno 13] Permission denied",
            DeployFailureKind.PORT_UNAVAILABLE,
        ),
        (
            "Failed to open serial port: device not configured",
            DeployFailureKind.PORT_UNAVAILABLE,
        ),
        # mpremote's message for a missing-or-busy device — wraps
        # both the generic "mpremote command failed" bootstrap-exec
        # substring AND the real cause ("failed to access ...").
        # The real cause must win so unplugged boards don't get
        # "fix your source code" coaching.
        (
            "mpremote command failed (exit 1):\n"
            "  command: /path/to/.venv/bin/mpremote connect "
            "/dev/cu.usbmodem211101 exec print('ok')\n"
            "  stderr: mpremote: failed to access "
            "/dev/cu.usbmodem211101 (it may be in use by another "
            "program)",
            DeployFailureKind.PORT_UNAVAILABLE,
        ),
        # CIRCUITPY drive missing — distinct from port-level failure.
        (
            "CIRCUITPY drive not found.  Either set circuitpy_drive_path "
            "or connect the board's USB drive.",
            DeployFailureKind.CIRCUITPY_DRIVE_MISSING,
        ),
        (
            "CIRCUITPY drive not mounted: /Volumes/CIRCUITPY",
            DeployFailureKind.CIRCUITPY_DRIVE_MISSING,
        ),
        # Stale-mount case — /Volumes/CIRCUITPY exists but writes
        # fail with EACCES (Finder eject leaves the placeholder; the
        # FSKit wedge does too).  The nested "Permission denied" text
        # collides with _PORT_UNAVAILABLE_PATTERNS, but the CIRCUITPY
        # prefix is more specific and must win.
        (
            "CIRCUITPY drive not found or not writable: /Volumes/CIRCUITPY "
            "(PermissionError: [Errno 13] Permission denied: "
            "'/Volumes/CIRCUITPY/.chu-probe')",
            DeployFailureKind.CIRCUITPY_DRIVE_MISSING,
        ),
        # Raw REPL unresponsive.
        (
            "Did not receive raw REPL prompt.  Got: b''",
            DeployFailureKind.RAW_REPL_UNRESPONSIVE,
        ),
        (
            "Raw REPL did not acknowledge code.  Response: b'garbage'",
            DeployFailureKind.RAW_REPL_UNRESPONSIVE,
        ),
        (
            "Malformed raw REPL response (missing \\x04 markers)",
            DeployFailureKind.RAW_REPL_UNRESPONSIVE,
        ),
        # Insufficient memory.
        (
            "CircuitPython board reports too little free RAM for inline "
            "execution (4096 bytes available).",
            DeployFailureKind.INSUFFICIENT_MEMORY,
        ),
        (
            "MemoryError: no more memory",
            DeployFailureKind.INSUFFICIENT_MEMORY,
        ),
        # Flash copy failure.
        (
            "rsync: write error: No space left on device (28)",
            DeployFailureKind.FLASH_COPY_FAILED,
        ),
        (
            "Input/output error: write failed",
            DeployFailureKind.FLASH_COPY_FAILED,
        ),
        (
            "Read-only file system",
            DeployFailureKind.FLASH_COPY_FAILED,
        ),
        # Bootstrap exec failed on the board.
        (
            "CircuitPython inline bootstrap chunk 2/5 failed: "
            "CircuitPython reported an error: ImportError",
            DeployFailureKind.BOOTSTRAP_EXEC_FAILED,
        ),
        (
            "Device exec failed: raw REPL exited",
            DeployFailureKind.BOOTSTRAP_EXEC_FAILED,
        ),
        (
            "Device deploy-execute failed: stderr present",
            DeployFailureKind.BOOTSTRAP_EXEC_FAILED,
        ),
        (
            "mpremote command failed (exit 1): fs cp reported error",
            DeployFailureKind.BOOTSTRAP_EXEC_FAILED,
        ),
        # Configuration error — caller misuse, not a runtime.
        (
            "connect() must be called before execute()",
            DeployFailureKind.CONFIGURATION_ERROR,
        ),
        (
            "entrypoint '/boot.py' missing from files (['/code.py'])",
            DeployFailureKind.CONFIGURATION_ERROR,
        ),
        (
            "CircuitpythonTransport.deploy_files does not support "
            "deploy_mode='ram'",
            DeployFailureKind.CONFIGURATION_ERROR,
        ),
        # Unknown bucket — any message with no hits.
        (
            "An entirely novel failure message",
            DeployFailureKind.UNKNOWN,
        ),
    ],
)
def test_classify_deploy_failure_buckets(
    message: str, expected_kind: DeployFailureKind,
) -> None:
    error = CircuitpythonTransportError(message)
    assert classify_deploy_failure(error) is expected_kind


def test_classify_works_on_both_transport_error_types() -> None:
    cp_error = CircuitpythonTransportError("CIRCUITPY drive not found.")
    mp_error = MicropythonTransportError("CIRCUITPY drive not found.")
    assert (
        classify_deploy_failure(cp_error)
        is classify_deploy_failure(mp_error)
        is DeployFailureKind.CIRCUITPY_DRIVE_MISSING
    )


def test_classify_is_case_insensitive() -> None:
    error = CircuitpythonTransportError(
        "CIRCUITPY DRIVE NOT FOUND.",
    )
    assert (
        classify_deploy_failure(error)
        is DeployFailureKind.CIRCUITPY_DRIVE_MISSING
    )


def test_classify_traceback_in_message_routes_to_traceback_returned() -> None:
    # CP RAM mode raises CircuitpythonTransportError with the board's
    # stderr inline — including a Python traceback.  The classifier
    # routes those to TRACEBACK_RETURNED (non-retryable, source-bug)
    # instead of BOOTSTRAP_EXEC_FAILED so the user gets the same
    # coaching as MP + CP flash paths for the same underlying cause.
    error = CircuitpythonTransportError(
        "CircuitPython inline bootstrap chunk 2/2 failed: "
        "CircuitPython reported an error:\n"
        "Traceback (most recent call last):\n"
        '  File "<stdin>", line 2, in <module>\n'
        "ZeroDivisionError: division by zero"
    )
    assert (
        classify_deploy_failure(error)
        is DeployFailureKind.TRACEBACK_RETURNED
    )


def test_classify_traceback_routing_beats_bootstrap_substring() -> None:
    # Message contains BOTH "inline bootstrap chunk" (→ BOOTSTRAP_EXEC)
    # and a Python traceback.  Traceback wins — the user-visible issue
    # is source code, not a transport hiccup.
    error = CircuitpythonTransportError(
        "CircuitPython inline bootstrap chunk 4/4 failed: "
        "Traceback (most recent call last):\n  ImportError: no mod"
    )
    assert (
        classify_deploy_failure(error)
        is DeployFailureKind.TRACEBACK_RETURNED
    )


def test_classify_configuration_wins_over_drive_missing() -> None:
    # A config-style message that also says "CIRCUITPY drive not found"
    # should still land in CONFIGURATION — configuration errors are
    # checked first because they often contain sub-string matches for
    # other kinds.
    error = CircuitpythonTransportError(
        "connect() must be called before deploy_files().  "
        "Then CIRCUITPY drive not found will be irrelevant."
    )
    assert (
        classify_deploy_failure(error)
        is DeployFailureKind.CONFIGURATION_ERROR
    )


# ---------------------------------------------------------------------------
# recovery_plan_for — every kind has a plan with non-empty fix_steps
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", list(DeployFailureKind))
def test_every_kind_has_a_plan(kind: DeployFailureKind) -> None:
    plan = recovery_plan_for(kind)
    assert isinstance(plan, RecoveryPlan)
    assert plan.headline
    assert plan.fix_steps
    assert all(isinstance(step, str) and step for step in plan.fix_steps)


def test_insufficient_memory_is_not_retryable() -> None:
    # Retrying a too-small-board failure changes nothing.
    plan = recovery_plan_for(DeployFailureKind.INSUFFICIENT_MEMORY)
    assert plan.retryable is False


def test_configuration_error_is_not_retryable() -> None:
    plan = recovery_plan_for(DeployFailureKind.CONFIGURATION_ERROR)
    assert plan.retryable is False


def test_traceback_is_not_retryable() -> None:
    plan = recovery_plan_for(DeployFailureKind.TRACEBACK_RETURNED)
    assert plan.retryable is False


@pytest.mark.parametrize(
    "kind",
    [
        DeployFailureKind.PORT_UNAVAILABLE,
        DeployFailureKind.RAW_REPL_UNRESPONSIVE,
        DeployFailureKind.CIRCUITPY_DRIVE_MISSING,
        DeployFailureKind.MACOS_FSKIT_WEDGED,
        DeployFailureKind.FLASH_COPY_FAILED,
        DeployFailureKind.BOOTSTRAP_EXEC_FAILED,
        DeployFailureKind.UNKNOWN,
    ],
)
def test_physical_failures_are_retryable(kind: DeployFailureKind) -> None:
    plan = recovery_plan_for(kind)
    assert plan.retryable is True


# ---------------------------------------------------------------------------
# InteractiveDeployer — retry loop + prompt behaviour
# ---------------------------------------------------------------------------


class _FakeDeployer:
    """Minimal Deployer stand-in for recovery tests.

    ``outcomes`` is consumed in order: each entry is either an
    :class:`Exception` to raise or a :class:`DeployResult` to
    return.  Attempts beyond the list raise :class:`AssertionError`
    so tests catch unbounded retries.
    """

    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def deploy(
        self,
        source,
        *,
        on_progress: Callable[[float, str], None] | None = None,
        on_file_staged: Callable[[str], None] | None = None,
        on_execute_line: Callable[[str], None] | None = None,
    ) -> DeployResult:
        self.calls += 1
        if not self._outcomes:
            raise AssertionError(
                f"Fake deployer called {self.calls}× but outcomes exhausted",
            )
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, DeployResult):
            return outcome
        raise TypeError(f"Unsupported outcome {outcome!r}")


class _ScriptedPrompt:
    """Answers a list of prompts in order, then asserts no more are asked."""

    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt_text: str) -> str:
        self.prompts.append(prompt_text)
        if not self.answers:
            raise AssertionError(
                f"Prompted after answers exhausted: {prompt_text!r}",
            )
        return self.answers.pop(0)


def _capturing_output() -> tuple[Callable[[str], None], list[str]]:
    lines: list[str] = []

    def _sink(line: str) -> None:
        lines.append(line)

    return _sink, lines


_DUMMY_SOURCE = object()


def test_interactive_deployer_returns_result_when_deploy_succeeds() -> None:
    ok = DeployResult(success=True, execute_output="hi\n")
    fake = _FakeDeployer([ok])
    sink, lines = _capturing_output()
    prompt = _ScriptedPrompt([])  # no prompts expected
    interactive = InteractiveDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
    )

    result = interactive.deploy(_DUMMY_SOURCE)  # type: ignore[arg-type]

    assert result is ok
    assert fake.calls == 1
    assert prompt.prompts == []
    # Success path emits no coaching chatter.
    assert lines == []


def test_retries_on_port_unavailable_then_succeeds() -> None:
    ok = DeployResult(success=True)
    fake = _FakeDeployer(
        [
            CircuitpythonTransportError(
                "Failed to open serial port /dev/cu.usbmodem: Resource busy",
            ),
            ok,
        ],
    )
    sink, lines = _capturing_output()
    prompt = _ScriptedPrompt([""])  # user hits Enter to retry
    interactive = InteractiveDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
    )

    result = interactive.deploy(_DUMMY_SOURCE)  # type: ignore[arg-type]

    assert result is ok
    assert fake.calls == 2
    # Coaching text must name the kind and show the port-unavailable
    # recovery plan.
    joined = "\n".join(lines)
    assert "port_unavailable" in joined
    assert "close any app" in joined.lower()
    assert len(prompt.prompts) == 1


def test_retries_up_to_max_attempts_then_reraises() -> None:
    # Three identical failures — interactive deployer is configured
    # with max_attempts=3, so the third failure re-raises without a
    # fourth prompt.
    fake = _FakeDeployer(
        [
            CircuitpythonTransportError(
                "Failed to open serial port: Resource busy",
            ),
        ]
        * 3,
    )
    sink, _lines = _capturing_output()
    prompt = _ScriptedPrompt(["", ""])  # only two prompts happen
    interactive = InteractiveDeployer(
        fake,  # type: ignore[arg-type]
        max_attempts=3,
        prompt=prompt,
        output=sink,
    )

    with pytest.raises(CircuitpythonTransportError):
        interactive.deploy(_DUMMY_SOURCE)  # type: ignore[arg-type]

    assert fake.calls == 3
    # Two prompts: after attempts 1 and 2.  No prompt after the
    # final attempt — we just re-raise.
    assert len(prompt.prompts) == 2


def test_non_retryable_failure_raises_without_prompting() -> None:
    fake = _FakeDeployer(
        [
            CircuitpythonTransportError(
                "CircuitPython board reports too little free RAM for "
                "inline execution (4096 bytes available).",
            ),
        ],
    )
    sink, lines = _capturing_output()
    prompt = _ScriptedPrompt([])  # zero prompts expected
    interactive = InteractiveDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
    )

    with pytest.raises(CircuitpythonTransportError):
        interactive.deploy(_DUMMY_SOURCE)  # type: ignore[arg-type]

    assert fake.calls == 1
    assert prompt.prompts == []
    # Even for non-retryable failures we still print the coaching
    # header so the user sees why we bailed.
    joined = "\n".join(lines)
    assert "insufficient_memory" in joined


def test_user_quit_stops_retries() -> None:
    fake = _FakeDeployer(
        [
            CircuitpythonTransportError(
                "Did not receive raw REPL prompt.  Got: b''",
            ),
        ],
    )
    sink, _lines = _capturing_output()
    prompt = _ScriptedPrompt(["quit"])
    interactive = InteractiveDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
    )

    with pytest.raises(CircuitpythonTransportError):
        interactive.deploy(_DUMMY_SOURCE)  # type: ignore[arg-type]

    assert fake.calls == 1
    assert len(prompt.prompts) == 1


@pytest.mark.parametrize(
    "quit_response", ["q", "Q", "quit", "QUIT", "abort", "exit"],
)
def test_quit_aliases(quit_response: str) -> None:
    fake = _FakeDeployer(
        [
            CircuitpythonTransportError(
                "CIRCUITPY drive not found.",
            ),
        ],
    )
    sink, _lines = _capturing_output()
    prompt = _ScriptedPrompt([quit_response])
    interactive = InteractiveDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
        # Pin the detector so tests don't shell out on macOS CI.
        fskit_wedge_detector=lambda: False,
    )

    with pytest.raises(CircuitpythonTransportError):
        interactive.deploy(_DUMMY_SOURCE)  # type: ignore[arg-type]

    assert fake.calls == 1


def test_traceback_returns_result_but_prints_coaching() -> None:
    failing = DeployResult(
        success=False,
        execute_output="Traceback (most recent call last):\n  ImportError: ...\n",
        traceback="Traceback (most recent call last):\n  ImportError: ...",
    )
    fake = _FakeDeployer([failing])
    sink, lines = _capturing_output()
    prompt = _ScriptedPrompt([])
    interactive = InteractiveDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
    )

    result = interactive.deploy(_DUMMY_SOURCE)  # type: ignore[arg-type]

    # Source-level bug — InteractiveDeployer still returns the
    # result (no retry) but prints the traceback-coaching block.
    assert result is failing
    assert fake.calls == 1
    joined = "\n".join(lines)
    assert "--- traceback ---" in joined
    assert "ImportError" in joined


def test_mpremote_transport_error_is_handled() -> None:
    # The retry loop catches MicropythonTransportError too, not just
    # the CP variant — both runtimes get the same coaching.
    ok = DeployResult(success=True)
    fake = _FakeDeployer(
        [
            MicropythonTransportError(
                "mpremote command failed (exit 1): could not open port",
            ),
            ok,
        ],
    )
    sink, _lines = _capturing_output()
    prompt = _ScriptedPrompt([""])
    interactive = InteractiveDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
    )

    result = interactive.deploy(_DUMMY_SOURCE)  # type: ignore[arg-type]

    assert result is ok
    assert fake.calls == 2


def test_max_attempts_validation() -> None:
    fake = _FakeDeployer([])
    with pytest.raises(ValueError, match="max_attempts"):
        InteractiveDeployer(fake, max_attempts=0)  # type: ignore[arg-type]


def test_forwards_callbacks_to_deployer() -> None:
    # Verify that on_progress / on_file_staged / on_execute_line
    # are passed through unchanged to the underlying deployer.
    received: dict[str, object] = {}

    class _SpyDeployer:
        calls = 0

        def deploy(self, source, **kwargs):  # type: ignore[no-untyped-def]
            type(self).calls += 1
            received.update(kwargs)
            return DeployResult(success=True)

    spy = _SpyDeployer()
    sink, _lines = _capturing_output()
    prompt = _ScriptedPrompt([])
    interactive = InteractiveDeployer(
        spy,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
    )

    def _progress(_fraction: float, _message: str) -> None:
        pass

    def _staged(_path: str) -> None:
        pass

    def _line(_text: str) -> None:
        pass

    interactive.deploy(
        _DUMMY_SOURCE,  # type: ignore[arg-type]
        on_progress=_progress,
        on_file_staged=_staged,
        on_execute_line=_line,
    )

    assert received["on_progress"] is _progress
    assert received["on_file_staged"] is _staged
    assert received["on_execute_line"] is _line


def test_deployer_property_exposes_wrapped_instance() -> None:
    fake = _FakeDeployer([])
    sink, _lines = _capturing_output()
    prompt = _ScriptedPrompt([])
    interactive = InteractiveDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
    )
    assert interactive.deployer is fake


# ---------------------------------------------------------------------------
# macOS FSKit / DiskArbitration wedge — plan + InteractiveDeployer promotion
# ---------------------------------------------------------------------------


def test_macos_fskit_wedged_plan_contains_recovery_command() -> None:
    # The pasted sudo command is the contract between the coaching
    # output and the user — guard against accidental edits that drop
    # or typo it.
    from chumicro_deploy.macos_fskit import MACOS_FSKIT_RECOVERY_COMMAND
    plan = recovery_plan_for(DeployFailureKind.MACOS_FSKIT_WEDGED)
    assert plan.retryable is True
    joined = "\n".join(plan.fix_steps)
    assert MACOS_FSKIT_RECOVERY_COMMAND in joined
    assert "FSKit" in plan.headline or "fskit" in plan.headline.lower()


def test_stale_mount_eaccess_message_promotes_to_fskit_wedged() -> None:
    # End-to-end regression for the wild-caught bug: the stale-mount
    # error carries an inner "Permission denied" that used to win the
    # classifier race and route to PORT_UNAVAILABLE, which in turn
    # skipped the FSKit wedge detector.  After the reorder + pattern
    # additions, the wedged path should promote correctly.
    from chumicro_deploy.macos_fskit import MACOS_FSKIT_RECOVERY_COMMAND
    fake = _FakeDeployer(
        [
            CircuitpythonTransportError(
                "CIRCUITPY drive not found or not writable: "
                "/Volumes/CIRCUITPY "
                "(PermissionError: [Errno 13] Permission denied: "
                "'/Volumes/CIRCUITPY/.chu-probe')",
            ),
        ],
    )
    sink, lines = _capturing_output()
    prompt = _ScriptedPrompt(["quit"])
    interactive = InteractiveDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
        fskit_wedge_detector=lambda: True,
    )

    with pytest.raises(CircuitpythonTransportError):
        interactive.deploy(_DUMMY_SOURCE)  # type: ignore[arg-type]

    joined = "\n".join(lines)
    assert "macos_fskit_wedged" in joined
    assert MACOS_FSKIT_RECOVERY_COMMAND in joined
    # Must NOT land in port_unavailable — that's the exact regression
    # we're guarding against.
    assert "port_unavailable" not in joined


def test_drive_missing_is_promoted_to_fskit_wedged_when_detector_trips() -> None:
    # Quit on the first prompt so the test stays focused on the
    # classification → plan promotion path.  The assertion is that
    # the coaching output shows the wedged plan, not the generic
    # tap-RESET plan.
    from chumicro_deploy.macos_fskit import MACOS_FSKIT_RECOVERY_COMMAND
    fake = _FakeDeployer(
        [CircuitpythonTransportError("CIRCUITPY drive not found.")],
    )
    sink, lines = _capturing_output()
    prompt = _ScriptedPrompt(["quit"])
    interactive = InteractiveDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
        fskit_wedge_detector=lambda: True,
    )

    with pytest.raises(CircuitpythonTransportError):
        interactive.deploy(_DUMMY_SOURCE)  # type: ignore[arg-type]

    joined = "\n".join(lines)
    assert "macos_fskit_wedged" in joined
    assert MACOS_FSKIT_RECOVERY_COMMAND in joined
    # The generic drive-missing coaching should NOT appear — if both
    # plans leaked into the output the user would see conflicting
    # instructions.
    assert "tap RESET once so CircuitPython re-exposes" not in joined


def test_drive_missing_stays_generic_when_detector_says_healthy() -> None:
    # The detector returning False keeps the existing
    # CIRCUITPY_DRIVE_MISSING coaching — no false-positive promotion
    # to the wedged plan.
    fake = _FakeDeployer(
        [CircuitpythonTransportError("CIRCUITPY drive not found.")],
    )
    sink, lines = _capturing_output()
    prompt = _ScriptedPrompt(["quit"])
    interactive = InteractiveDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
        fskit_wedge_detector=lambda: False,
    )

    with pytest.raises(CircuitpythonTransportError):
        interactive.deploy(_DUMMY_SOURCE)  # type: ignore[arg-type]

    joined = "\n".join(lines)
    assert "circuitpy_drive_missing" in joined
    assert "macos_fskit_wedged" not in joined


def test_detector_not_called_for_unrelated_failure_kinds() -> None:
    # We only run the detector on CIRCUITPY_DRIVE_MISSING — other
    # kinds should skip it so a laggy subprocess call does not
    # creep into the port-unavailable / raw-REPL retry paths.
    detector_calls = 0

    def _spy_detector() -> bool:
        nonlocal detector_calls
        detector_calls += 1
        return True

    fake = _FakeDeployer(
        [
            CircuitpythonTransportError(
                "Failed to open serial port: Resource busy",
            ),
        ],
    )
    sink, _lines = _capturing_output()
    prompt = _ScriptedPrompt(["quit"])
    interactive = InteractiveDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
        fskit_wedge_detector=_spy_detector,
    )

    with pytest.raises(CircuitpythonTransportError):
        interactive.deploy(_DUMMY_SOURCE)  # type: ignore[arg-type]

    assert detector_calls == 0
