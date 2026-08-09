"""Tests for the interactive recovery layer."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from chumicro_deploy.circuitpython_transport import CircuitpythonTransportError
from chumicro_deploy.micropython_transport import MicropythonTransportError
from chumicro_deploy.recovery import (
    DeployFailureKind,
    RecoveringDeployer,
    RecoveryPlan,
    classify_deploy_failure,
    recovery_plan_for,
)
from chumicro_deploy.result import DeployResult

# ---------------------------------------------------------------------------
# classify_deploy_failure: message-to-kind mapping
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
        # mpremote's message for a missing-or-busy device wraps
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
        # CIRCUITPY drive missing, distinct from port-level failure.
        (
            "CIRCUITPY drive not found.  Connect the board's USB "
            "drive (or check that the host has it mounted).",
            DeployFailureKind.CIRCUITPY_DRIVE_MISSING,
        ),
        (
            "CIRCUITPY drive not mounted: /Volumes/CIRCUITPY",
            DeployFailureKind.CIRCUITPY_DRIVE_MISSING,
        ),
        # Stale-mount case: /Volumes/CIRCUITPY exists but writes
        # fail with EACCES.  Finder eject leaves the placeholder, and
        # the FSKit wedge does too.  The nested "Permission denied"
        # text collides with _PORT_UNAVAILABLE_PATTERNS, but the
        # CIRCUITPY prefix is more specific and must win.
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
        # mpremote subprocess timeout: a wedged USB-CDC, not a board-side
        # exec error.  Must win over the "mpremote command failed"
        # bootstrap substring and route to the non-retryable replug path.
        (
            "mpremote command timed out after 120 s; the board's USB-CDC "
            "likely wedged mid-command.\n  Fix: replug the board.",
            DeployFailureKind.COMMAND_TIMED_OUT,
        ),
        # Configuration error: caller misuse, not a runtime.
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
        # Unresolved import: the walker refused before touching the board.
        (
            "Deploy refused: unresolved import.\n"
            "  /proj/app.py imports 'chumicro_missing', which resolves to no "
            "deployed file and is not a known device built-in",
            DeployFailureKind.UNRESOLVED_IMPORT,
        ),
        # No Python runtime: board responds but isn't running CP/MP.
        # Distinct from RAW_REPL_UNRESPONSIVE (Python interpreter
        # present but hung) and PORT_UNAVAILABLE (port not reachable).
        # Drives the install-firmware coaching path.
        (
            "no python runtime detected on /dev/cu.usbmodem101 "
            "(received Arduino-style banner)",
            DeployFailureKind.NO_PYTHON_RUNTIME,
        ),
        (
            "no python runtime on /dev/ttyACM0",
            DeployFailureKind.NO_PYTHON_RUNTIME,
        ),
        (
            "board does not respond to python — REPL banner did not "
            "match circuitpython or micropython",
            DeployFailureKind.NO_PYTHON_RUNTIME,
        ),
        (
            "non-Python firmware detected (USB descriptor: "
            "Raspberry Pi RP2040, no CP/MP banner)",
            DeployFailureKind.NO_PYTHON_RUNTIME,
        ),
        (
            "Unknown firmware on /dev/cu.usbmodem211101",
            DeployFailureKind.NO_PYTHON_RUNTIME,
        ),
        # Unknown bucket: any message with no hits.
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


def test_command_timeout_is_not_retryable() -> None:
    """A wedged-CDC timeout must not retry into the same 120 s hang."""
    plan = recovery_plan_for(DeployFailureKind.COMMAND_TIMED_OUT)
    assert plan.retryable is False


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


def test_classify_disk_full_wins_over_circuitpy_drive_wrap() -> None:
    # The CIRCUITPY-wrap message format is wide: every probe-side
    # OSError surfaces as "CIRCUITPY drive not found or not writable",
    # including ENOSPC where the drive was found and only the write
    # failed.  When the wrap text and a flash-state substring ("no
    # space left on device") co-exist in one message, the flash-state
    # signal must win so the user gets free-up-space coaching, not
    # the tap-RESET-to-remount coaching.
    error = CircuitpythonTransportError(
        "CIRCUITPY drive not found or not writable: /Volumes/CIRCUITPY "
        "(OSError: [Errno 28] No space left on device)"
    )
    assert (
        classify_deploy_failure(error)
        is DeployFailureKind.FLASH_COPY_FAILED
    )


def test_classify_read_only_wins_over_circuitpy_drive_wrap() -> None:
    error = CircuitpythonTransportError(
        "CIRCUITPY drive not found or not writable: /Volumes/CIRCUITPY "
        "(OSError: [Errno 30] Read-only file system)"
    )
    assert (
        classify_deploy_failure(error)
        is DeployFailureKind.FLASH_COPY_FAILED
    )


def test_classify_io_error_wins_over_circuitpy_drive_wrap() -> None:
    error = CircuitpythonTransportError(
        "CIRCUITPY drive not found or not writable: /Volumes/CIRCUITPY "
        "(OSError: [Errno 5] Input/output error)"
    )
    assert (
        classify_deploy_failure(error)
        is DeployFailureKind.FLASH_COPY_FAILED
    )


def test_classify_pure_circuitpy_missing_still_routes_to_drive_kind() -> None:
    # A message with no flash-state signal should still classify as
    # CIRCUITPY_DRIVE_MISSING.  Locks in the "drive-state wins, but
    # the wrap path is unaffected" contract.
    error = CircuitpythonTransportError(
        "CIRCUITPY drive not found: /Volumes/CIRCUITPY"
    )
    assert (
        classify_deploy_failure(error)
        is DeployFailureKind.CIRCUITPY_DRIVE_MISSING
    )


def test_classify_eacces_stale_mount_still_routes_to_drive_kind() -> None:
    # EACCES from a Finder-eject stale mount is the original reason
    # CIRCUITPY_DRIVE_MISSING gets checked before PORT_UNAVAILABLE.
    # Make sure that path is still intact.  Disk-state preemption
    # shouldn't catch "Permission denied" (EACCES is not in
    # _FLASH_DRIVE_STATE_PATTERNS).
    error = CircuitpythonTransportError(
        "CIRCUITPY drive not found or not writable: /Volumes/CIRCUITPY "
        "(PermissionError: [Errno 13] Permission denied)"
    )
    assert (
        classify_deploy_failure(error)
        is DeployFailureKind.CIRCUITPY_DRIVE_MISSING
    )


def test_classify_traceback_in_message_routes_to_traceback_returned() -> None:
    # CP RAM mode raises CircuitpythonTransportError with the board's
    # stderr inline, including a Python traceback.  The classifier
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
    # Message contains BOTH "inline bootstrap chunk" (routes to
    # BOOTSTRAP_EXEC) and a Python traceback.  Traceback wins, because
    # the user-visible issue is source code, not a transport hiccup.
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
    # should still land in CONFIGURATION.  Configuration errors are
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


def test_classify_fat_corruption_message() -> None:
    # The message flash_drive.format_fat_corruption_error emits routes
    # to FAT_VOLUME_CORRUPT (reformat coaching), not a generic bucket.
    error = CircuitpythonTransportError(
        "FAT directory entries on /Volumes/CIRCUITPY are torn: the "
        "host can list them, but stat fails with EINVAL and they "
        "cannot be unlinked:\n    lib/chumicro_config/section.py\n"
        "  The volume cannot be repaired in place.  Run "
        "`chumicro-workspace reset-board --device <id> --yes` to "
        "reformat the board's filesystem, then re-run the deploy."
    )
    assert (
        classify_deploy_failure(error)
        is DeployFailureKind.FAT_VOLUME_CORRUPT
    )


def test_classify_fat_corruption_wins_over_rsync_flash_state() -> None:
    # The corruption message embeds rsync stderr, and "rsync" is a
    # _FLASH_DRIVE_STATE_PATTERNS trigger.  Corruption must win: its
    # coaching is "reformat", where FLASH_COPY_FAILED coaches a retry
    # that cannot succeed against torn entries.
    error = CircuitpythonTransportError(
        "FAT directory entries on /Volumes/CIRCUITPY are torn: the "
        "host can list them, but stat fails with EINVAL and they "
        "cannot be unlinked:\n    lib/chumicro_mqtt/_wire.py\n"
        "  rsync reported:\n    rsync: fstatat: Invalid argument\n"
        "  The volume cannot be repaired in place."
    )
    assert (
        classify_deploy_failure(error)
        is DeployFailureKind.FAT_VOLUME_CORRUPT
    )


# ---------------------------------------------------------------------------
# recovery_plan_for: every kind has a plan with non-empty fix_steps
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


def test_unresolved_import_is_not_retryable() -> None:
    # The fix is editing the deploy config or source; the board was never
    # touched, so a retry of the same bytes changes nothing.
    plan = recovery_plan_for(DeployFailureKind.UNRESOLVED_IMPORT)
    assert plan.retryable is False


def test_no_python_runtime_is_not_retryable() -> None:
    """Retrying a board with no Python runtime changes nothing.  The
    user must explicitly run install-firmware first.  Non-retryable
    is the right contract because flashing is destructive (overwrites
    whatever firmware is on the board) and must require explicit
    consent, never an auto-loop retry."""
    plan = recovery_plan_for(DeployFailureKind.NO_PYTHON_RUNTIME)
    assert plan.retryable is False


def test_fat_volume_corrupt_is_not_retryable() -> None:
    # Torn FAT entries survive RESET and retry; only a reformat clears
    # them, so the recovery loop must bail immediately.
    plan = recovery_plan_for(DeployFailureKind.FAT_VOLUME_CORRUPT)
    assert plan.retryable is False


def test_fat_volume_corrupt_plan_names_reset_board() -> None:
    """The coaching must name the one command that actually recovers
    a torn FAT (chumicro-workspace reset-board)."""
    plan = recovery_plan_for(DeployFailureKind.FAT_VOLUME_CORRUPT)
    flat = " ".join(plan.fix_steps).lower()
    assert "reset-board" in flat


def test_no_python_runtime_plan_points_at_install_firmware() -> None:
    """The recovery hint must name install-firmware so the user
    (or an agent reading stderr) can take action."""
    plan = recovery_plan_for(DeployFailureKind.NO_PYTHON_RUNTIME)
    flat = " ".join(plan.fix_steps).lower()
    assert "install-firmware" in flat


def test_classify_no_python_wins_over_raw_repl_unresponsive() -> None:
    """A message that explicitly asserts "no python here" must NOT
    classify as RAW_REPL_UNRESPONSIVE.  They're different recoveries
    (install-firmware vs. tap RESET) and the more specific kind wins.
    Guards against future pattern reordering that might silently
    re-route the no-Python case to the generic REPL bucket."""
    error = CircuitpythonTransportError(
        "no python runtime detected on /dev/cu.usbmodem101 — "
        "did not receive raw REPL prompt either",
    )
    assert (
        classify_deploy_failure(error)
        is DeployFailureKind.NO_PYTHON_RUNTIME
    )


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
# RecoveringDeployer (prompt= set): retry loop + prompt behavior
# ---------------------------------------------------------------------------


class _FakeDeployer:
    """Minimal Deployer stand-in for recovery tests.

    ``outcomes`` is consumed in order.  Each entry is either an
    :class:`Exception` to raise or a :class:`DeployResult` to
    return.  Attempts beyond the list raise :class:`AssertionError`
    so tests catch unbounded retries.
    """

    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def deploy_diff(
        self,
        source,
        *,
        clean: bool = True,
        wipe: bool = False,
        on_progress: Callable[[float, str], None] | None = None,
        on_file_staged: Callable[[str], None] | None = None,
        on_file_deleted: Callable[[str], None] | None = None,
        on_execute_line: Callable[[str], None] | None = None,
        tail_seconds: float | None = None,
        force_deploy_mode: str | None = None,
    ) -> DeployResult:
        self.last_clean = clean
        self.last_wipe = wipe
        self.last_force_deploy_mode = force_deploy_mode
        return self._consume()

    def _consume(self) -> DeployResult:
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
    interactive = RecoveringDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
    )

    result = interactive.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

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
    interactive = RecoveringDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
    )

    result = interactive.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

    assert result is ok
    assert fake.calls == 2
    # Coaching text must name the kind and show the port-unavailable
    # recovery plan.
    joined = "\n".join(lines)
    assert "port_unavailable" in joined
    assert "close any app" in joined.lower()
    assert len(prompt.prompts) == 1


def test_retries_up_to_max_attempts_then_reraises() -> None:
    # Three identical failures.  Interactive deployer is configured
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
    interactive = RecoveringDeployer(
        fake,  # type: ignore[arg-type]
        max_attempts=3,
        prompt=prompt,
        output=sink,
    )

    with pytest.raises(CircuitpythonTransportError):
        interactive.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

    assert fake.calls == 3
    # Two prompts: after attempts 1 and 2.  No prompt after the
    # final attempt, we just re-raise.
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
    interactive = RecoveringDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
    )

    with pytest.raises(CircuitpythonTransportError):
        interactive.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

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
    interactive = RecoveringDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
    )

    with pytest.raises(CircuitpythonTransportError):
        interactive.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

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
    interactive = RecoveringDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
        # Pin the detector so tests don't shell out on macOS CI.
        fskit_wedge_detector=lambda: False,
    )

    with pytest.raises(CircuitpythonTransportError):
        interactive.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

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
    interactive = RecoveringDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
    )

    result = interactive.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

    # Source-level bug.  RecoveringDeployer still returns the
    # result (no retry) but prints the traceback-coaching block.
    assert result is failing
    assert fake.calls == 1
    joined = "\n".join(lines)
    assert "--- traceback ---" in joined
    assert "ImportError" in joined


def test_mpremote_transport_error_is_handled() -> None:
    # The retry loop catches MicropythonTransportError too, not just
    # the CP variant.  Both runtimes get the same coaching.
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
    interactive = RecoveringDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
    )

    result = interactive.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

    assert result is ok
    assert fake.calls == 2


def test_max_attempts_validation() -> None:
    fake = _FakeDeployer([])
    with pytest.raises(ValueError, match="max_attempts"):
        RecoveringDeployer(fake, max_attempts=0)  # type: ignore[arg-type]


def test_forwards_callbacks_to_deployer() -> None:
    # Verify that on_progress / on_file_staged / on_execute_line
    # are passed through unchanged to the underlying deployer.
    received: dict[str, object] = {}

    class _SpyDeployer:
        calls = 0

        def deploy_diff(self, source, **kwargs):  # type: ignore[no-untyped-def]
            type(self).calls += 1
            received.update(kwargs)
            return DeployResult(success=True)

    spy = _SpyDeployer()
    sink, _lines = _capturing_output()
    prompt = _ScriptedPrompt([])
    interactive = RecoveringDeployer(
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

    interactive.deploy_diff(
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
    interactive = RecoveringDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
    )
    assert interactive.deployer is fake


# ---------------------------------------------------------------------------
# RecoveringDeployer.deploy_diff: mirror of .deploy with wipe + on_file_deleted
# ---------------------------------------------------------------------------


def test_deploy_diff_succeeds_on_first_attempt() -> None:
    ok = DeployResult(success=True, execute_output="ok\n")
    fake = _FakeDeployer([ok])
    sink, lines = _capturing_output()
    interactive = RecoveringDeployer(
        fake,  # type: ignore[arg-type]
        prompt=_ScriptedPrompt([]),
        output=sink,
    )

    result = interactive.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

    assert result is ok
    assert fake.calls == 1
    assert fake.last_wipe is False
    assert lines == []


def test_deploy_diff_forwards_wipe_to_underlying_deployer() -> None:
    ok = DeployResult(success=True)
    fake = _FakeDeployer([ok])
    interactive = RecoveringDeployer(
        fake,  # type: ignore[arg-type]
        prompt=_ScriptedPrompt([]),
        output=_capturing_output()[0],
    )

    interactive.deploy_diff(_DUMMY_SOURCE, wipe=True)  # type: ignore[arg-type]

    assert fake.last_wipe is True


def test_deploy_diff_retries_on_port_unavailable_then_succeeds() -> None:
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
    prompt = _ScriptedPrompt([""])
    interactive = RecoveringDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
    )

    result = interactive.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

    assert result is ok
    assert fake.calls == 2
    # Coaching went out before the retry.
    assert any("port_unavailable" in line for line in lines)


def test_deploy_diff_traceback_returns_result_but_prints_coaching() -> None:
    bad = DeployResult(
        success=False,
        execute_output="boom",
        traceback="Traceback (most recent call last):\n  File 'app.py', line 1\nValueError",
    )
    fake = _FakeDeployer([bad])
    sink, lines = _capturing_output()
    interactive = RecoveringDeployer(
        fake,  # type: ignore[arg-type]
        prompt=_ScriptedPrompt([]),
        output=sink,
    )

    result = interactive.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

    assert result is bad
    assert any("traceback" in line.lower() for line in lines)


# ---------------------------------------------------------------------------
# macOS FSKit / DiskArbitration wedge: plan + RecoveringDeployer promotion
# ---------------------------------------------------------------------------


def test_macos_fskit_wedged_plan_contains_recovery_command() -> None:
    # The pasted sudo command is the contract between the coaching
    # output and the user.  Guard against accidental edits that drop
    # or typo it.
    from chumicro_deploy.macos_fskit import MACOS_FSKIT_RECOVERY_COMMAND
    plan = recovery_plan_for(DeployFailureKind.MACOS_FSKIT_WEDGED)
    assert plan.retryable is True
    joined = "\n".join(plan.fix_steps)
    assert MACOS_FSKIT_RECOVERY_COMMAND in joined
    assert "FSKit" in plan.headline or "fskit" in plan.headline.lower()


def test_stale_mount_eaccess_message_promotes_to_fskit_wedged() -> None:
    # Stale Finder-eject leaves /Volumes/CIRCUITPY as a placeholder
    # the host can stat but the kernel refuses writes on.  The probe
    # surfaces this as a CIRCUITPY-wrap message whose inner
    # "Permission denied" text overlaps _PORT_UNAVAILABLE_PATTERNS.
    # When the FSKit wedge detector confirms the wedge, classification
    # must route to the wedged path so the user gets clear-wedge
    # coaching, not replug coaching.
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
    interactive = RecoveringDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
        fskit_wedge_detector=lambda: True,
    )

    with pytest.raises(CircuitpythonTransportError):
        interactive.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

    joined = "\n".join(lines)
    assert "macos_fskit_wedged" in joined
    assert MACOS_FSKIT_RECOVERY_COMMAND in joined
    # Must NOT land in port_unavailable.  That's the exact regression
    # we're guarding against.
    assert "port_unavailable" not in joined


def test_drive_missing_is_promoted_to_fskit_wedged_when_detector_trips() -> None:
    # Quit on the first prompt so the test stays focused on the
    # classification-to-plan promotion path.  The assertion is that
    # the coaching output shows the wedged plan, not the generic
    # tap-RESET plan.
    from chumicro_deploy.macos_fskit import MACOS_FSKIT_RECOVERY_COMMAND
    fake = _FakeDeployer(
        [CircuitpythonTransportError("CIRCUITPY drive not found.")],
    )
    sink, lines = _capturing_output()
    prompt = _ScriptedPrompt(["quit"])
    interactive = RecoveringDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
        fskit_wedge_detector=lambda: True,
    )

    with pytest.raises(CircuitpythonTransportError):
        interactive.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

    joined = "\n".join(lines)
    assert "macos_fskit_wedged" in joined
    assert MACOS_FSKIT_RECOVERY_COMMAND in joined
    # The generic drive-missing coaching should NOT appear.  If both
    # plans leaked into the output the user would see conflicting
    # instructions.
    assert "tap RESET once so CircuitPython re-exposes" not in joined


def test_wipe_filesystem_remount_timeout_promotes_to_fskit_wedged() -> None:
    # The FAT-remount timeout in CircuitpythonTransport.wipe_filesystem
    # is the load-bearing surface for "FSKit wedged a CIRCUITPY drive
    # mid-wipe": serial USB-CDC reconnects fine, but the FAT volume
    # never remounts.  The transport's timeout message is phrased to
    # contain "CIRCUITPY drive not mounted" so it classifies to
    # CIRCUITPY_DRIVE_MISSING, which the recovery layer then promotes
    # to MACOS_FSKIT_WEDGED when the detector reports True.  Without
    # that wiring the user would see a generic "didn't become usable"
    # timeout instead of the actionable killall recovery command.
    from chumicro_deploy.macos_fskit import MACOS_FSKIT_RECOVERY_COMMAND
    fake = _FakeDeployer(
        [
            CircuitpythonTransportError(
                "CIRCUITPY drive not mounted at "
                "/Volumes/CIRCUITPY within 10s of "
                "storage.erase_filesystem(); last error: "
                "PermissionError: [Errno 13] Permission denied",
            ),
        ],
    )
    sink, lines = _capturing_output()
    prompt = _ScriptedPrompt(["quit"])
    interactive = RecoveringDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
        fskit_wedge_detector=lambda: True,
    )

    with pytest.raises(CircuitpythonTransportError):
        interactive.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

    joined = "\n".join(lines)
    assert "macos_fskit_wedged" in joined
    assert MACOS_FSKIT_RECOVERY_COMMAND in joined


def test_drive_missing_stays_generic_when_detector_says_healthy() -> None:
    # The detector returning False keeps the existing
    # CIRCUITPY_DRIVE_MISSING coaching, no false-positive promotion
    # to the wedged plan.
    fake = _FakeDeployer(
        [CircuitpythonTransportError("CIRCUITPY drive not found.")],
    )
    sink, lines = _capturing_output()
    prompt = _ScriptedPrompt(["quit"])
    interactive = RecoveringDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
        fskit_wedge_detector=lambda: False,
    )

    with pytest.raises(CircuitpythonTransportError):
        interactive.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

    joined = "\n".join(lines)
    assert "circuitpy_drive_missing" in joined
    assert "macos_fskit_wedged" not in joined


def test_detector_not_called_for_unrelated_failure_kinds() -> None:
    # We only run the detector on CIRCUITPY_DRIVE_MISSING.  Other
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
    interactive = RecoveringDeployer(
        fake,  # type: ignore[arg-type]
        prompt=prompt,
        output=sink,
        fskit_wedge_detector=_spy_detector,
    )

    with pytest.raises(CircuitpythonTransportError):
        interactive.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

    assert detector_calls == 0


# ---------------------------------------------------------------------------
# MidDeployDisconnected typed subclasses
# ---------------------------------------------------------------------------


class TestMidDeployDisconnected:
    """Typed disconnect subclasses route through the classifier as PORT_UNAVAILABLE."""

    def test_circuitpython_subclass_isinstance_of_base(self):
        from chumicro_deploy import (
            CircuitpythonMidDeployDisconnected,
            CircuitpythonTransportError,
        )

        exception = CircuitpythonMidDeployDisconnected(OSError("cable popped"))
        assert isinstance(exception, CircuitpythonTransportError)

    def test_micropython_subclass_isinstance_of_base(self):
        from chumicro_deploy import (
            MicropythonMidDeployDisconnected,
            MicropythonTransportError,
        )

        exception = MicropythonMidDeployDisconnected(OSError("cable popped"))
        assert isinstance(exception, MicropythonTransportError)

    def test_classifier_routes_circuitpython_disconnect_to_port_unavailable(self):
        from chumicro_deploy import CircuitpythonMidDeployDisconnected

        exception = CircuitpythonMidDeployDisconnected(
            OSError("cable popped"), context="stage",
        )
        kind = classify_deploy_failure(exception)
        assert kind is DeployFailureKind.PORT_UNAVAILABLE

    def test_classifier_routes_micropython_disconnect_to_port_unavailable(self):
        from chumicro_deploy import MicropythonMidDeployDisconnected

        exception = MicropythonMidDeployDisconnected(
            OSError("cable popped"), context="exec",
        )
        kind = classify_deploy_failure(exception)
        assert kind is DeployFailureKind.PORT_UNAVAILABLE

    def test_cause_attribute_holds_underlying_oserror(self):
        from chumicro_deploy import CircuitpythonMidDeployDisconnected

        underlying = OSError(6, "Device not configured")
        exception = CircuitpythonMidDeployDisconnected(underlying)
        assert exception.cause is underlying

    def test_message_includes_context_when_supplied(self):
        from chumicro_deploy import CircuitpythonMidDeployDisconnected

        exception = CircuitpythonMidDeployDisconnected(
            OSError("eof"), context="bootstrap exec",
        )
        assert "during bootstrap exec" in str(exception)

    def test_empty_context_omits_during_clause(self):
        from chumicro_deploy import MicropythonMidDeployDisconnected

        exception = MicropythonMidDeployDisconnected(OSError("eof"))
        assert "device disconnected:" in str(exception)
        assert "during" not in str(exception)


# ---------------------------------------------------------------------------
# FakeSerialPort scripted disconnect support
# ---------------------------------------------------------------------------


class TestFakeSerialPortScriptedDisconnects:
    """Read-side and write-side scripted disconnects via the testing fake."""

    def test_read_chunks_can_raise_oserror(self):
        from chumicro_deploy.testing import FakeSerialPort

        port = FakeSerialPort(read_responses=[b"hello", OSError("gone")])
        assert port.in_waiting == len(b"hello")
        assert port.read(1) == b"hello"
        # Next entry is an exception.  in_waiting reports 1 so polling
        # loops actually call read() instead of skipping past the
        # scripted disconnect.
        assert port.in_waiting == 1
        with pytest.raises(OSError, match="gone"):
            port.read(1)

    def test_write_can_be_scripted_to_raise(self):
        from chumicro_deploy.testing import FakeSerialPort

        port = FakeSerialPort(raise_on_write=OSError("write failed"))
        with pytest.raises(OSError, match="write failed"):
            port.write(b"anything")
        # When raise_on_write is None (default), writes record normally.
        port_quiet = FakeSerialPort()
        port_quiet.write(b"hi")
        assert port_quiet.writes == [b"hi"]

    def test_exhausted_script_returns_empty_bytes(self):
        from chumicro_deploy.testing import FakeSerialPort

        port = FakeSerialPort(read_responses=[b"once"])
        assert port.read(1) == b"once"
        assert port.in_waiting == 0
        assert port.read(1) == b""


# ---------------------------------------------------------------------------
# Port-holder diagnosis
# ---------------------------------------------------------------------------


class TestExtractPortPathFromError:
    """``_extract_port_path_from_error`` pulls the serial port path
    out of transport-error text so the recovery printer can drive
    lsof against it.
    """

    def test_finds_macos_cu_usbmodem_path(self) -> None:
        from chumicro_deploy.recovery import _extract_port_path_from_error  # noqa: PLC0415

        error = Exception(
            "mpremote: failed to access /dev/cu.usbmodem112401 "
            "(it may be in use by another program)",
        )
        assert _extract_port_path_from_error(error) == "/dev/cu.usbmodem112401"

    def test_finds_linux_ttyacm_path(self) -> None:
        from chumicro_deploy.recovery import _extract_port_path_from_error  # noqa: PLC0415

        error = Exception(
            "Failed to open serial port /dev/ttyACM0: Resource busy",
        )
        assert _extract_port_path_from_error(error) == "/dev/ttyACM0"

    def test_finds_linux_ttyusb_path(self) -> None:
        from chumicro_deploy.recovery import _extract_port_path_from_error  # noqa: PLC0415

        error = Exception(
            "could not open port '/dev/ttyUSB0': permission denied",
        )
        assert _extract_port_path_from_error(error) == "/dev/ttyUSB0"

    def test_returns_none_when_no_path(self) -> None:
        from chumicro_deploy.recovery import _extract_port_path_from_error  # noqa: PLC0415

        assert _extract_port_path_from_error(
            Exception("mpremote command failed (exit 1)"),
        ) is None
        assert _extract_port_path_from_error(Exception("")) is None


class TestDiagnosePortHolders:
    """``diagnose_port_holders`` calls ``lsof`` and parses ``-F pcn``
    output into :class:`PortHolder` records.
    """

    def test_returns_empty_on_unsupported_platform(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from chumicro_deploy import recovery  # noqa: PLC0415

        monkeypatch.setattr(recovery.sys, "platform", "win32")
        assert recovery.diagnose_port_holders("/dev/cu.fake") == []

    def test_returns_empty_when_lsof_missing(self) -> None:
        from chumicro_deploy import recovery  # noqa: PLC0415

        def fake_run(*_args, **_kwargs):
            raise FileNotFoundError("lsof: command not found")

        assert recovery.diagnose_port_holders(
            "/dev/cu.fake", runner=fake_run,
        ) == []

    def test_returns_empty_when_lsof_returns_nothing(self) -> None:
        """Free port: lsof exits non-zero with empty stdout."""
        from chumicro_deploy import recovery  # noqa: PLC0415

        def fake_run(args, **_kwargs):
            class _Result:
                returncode = 1
                stdout = ""
                stderr = ""
            return _Result()

        assert recovery.diagnose_port_holders(
            "/dev/cu.fake", runner=fake_run,
        ) == []

    def test_parses_single_holder(self) -> None:
        """Realistic single-holder output gets parsed into a PortHolder."""
        from chumicro_deploy import recovery  # noqa: PLC0415

        def fake_run(args, **_kwargs):
            if args[0] == "lsof":
                stdout = "p11421\ncPython\nf3\nn/dev/cu.usbmodem112401\n"
            else:  # ps -p <pid> -o command=
                stdout = "/usr/bin/python /path/run.py deploy hello_world"  # noqa: CHU006 — workspace shim command name is data here, exercising the chumicro-detection heuristic

            class _Result:
                returncode = 0

            result = _Result()
            result.stdout = stdout  # type: ignore[attr-defined]
            return result

        holders = recovery.diagnose_port_holders(
            "/dev/cu.usbmodem112401", runner=fake_run,
        )
        assert len(holders) == 1
        assert holders[0].pid == 11421
        # ps fallout: full command line preferred over lsof's short ``c``.
        assert "run.py deploy" in holders[0].command  # noqa: CHU006 — assertion against the workspace shim command name as data

    def test_parses_multiple_holders(self) -> None:
        """Multiple processes on the same port (rare but possible)."""
        from chumicro_deploy import recovery  # noqa: PLC0415

        # ps lookups return per-PID command strings.
        ps_responses = {
            "111": "Mu --port /dev/cu.x",
            "222": "/usr/bin/python /path/mpremote connect /dev/cu.x",
        }

        def fake_run(args, **_kwargs):
            class _Result:
                returncode = 0
                stdout = ""

            if args[0] == "lsof":
                _Result.stdout = (
                    "p111\ncMu\nn/dev/cu.x\n"
                    "p222\ncPython\nn/dev/cu.x\n"
                )
            else:
                pid = args[args.index("-p") + 1]
                _Result.stdout = ps_responses.get(pid, "") + "\n"
            return _Result()

        holders = recovery.diagnose_port_holders("/dev/cu.x", runner=fake_run)
        assert {holder.pid for holder in holders} == {111, 222}
        assert any("Mu" in holder.command for holder in holders)
        assert any("mpremote" in holder.command for holder in holders)

    def test_falls_back_to_lsof_command_when_ps_fails(self) -> None:
        """When ``ps`` returns non-zero, use lsof's short ``c`` field."""
        from chumicro_deploy import recovery  # noqa: PLC0415

        def fake_run(args, **_kwargs):
            class _Result:
                returncode = 0
                stdout = ""

            if args[0] == "lsof":
                _Result.stdout = "p999\ncPython\nn/dev/cu.x\n"
            else:  # ps fails (process exited between lsof and ps)
                _Result.returncode = 1
                _Result.stdout = ""
            return _Result()

        holders = recovery.diagnose_port_holders("/dev/cu.x", runner=fake_run)
        assert len(holders) == 1
        assert holders[0].pid == 999
        assert holders[0].command == "Python"  # lsof short field


class TestLooksLikeChumicro:
    """The chumicro-process heuristic distinguishes stale orphans
    (which the user can safely kill) from external apps the user
    explicitly opened (which need different handling).
    """

    def _holder(self, command: str):
        from chumicro_deploy.recovery import PortHolder  # noqa: PLC0415

        return PortHolder(pid=12345, command=command)

    def test_chumicro_deploy_subprocess_is_recognized(self) -> None:
        from chumicro_deploy.recovery import _looks_like_chumicro  # noqa: PLC0415

        assert _looks_like_chumicro(self._holder(
            "/usr/bin/python /path/.venv/bin/chumicro-deploy ...",
        ))

    def test_run_py_deploy_is_recognized(self) -> None:
        from chumicro_deploy.recovery import _looks_like_chumicro  # noqa: PLC0415

        assert _looks_like_chumicro(self._holder(
            "/usr/bin/python /workspace/run.py deploy hello_world",  # noqa: CHU006 — workspace shim command name is data here
        ))

    def test_mpremote_subprocess_is_recognized(self) -> None:
        from chumicro_deploy.recovery import _looks_like_chumicro  # noqa: PLC0415

        assert _looks_like_chumicro(self._holder(
            "/usr/bin/python /path/mpremote connect /dev/cu.x exec ...",
        ))

    def test_external_apps_are_not_recognized(self) -> None:
        from chumicro_deploy.recovery import _looks_like_chumicro  # noqa: PLC0415

        for command in (
            "/Applications/Mu.app/Contents/MacOS/Mu",
            "thonny --port /dev/cu.x",
            "screen /dev/cu.x 115200",
            "/Applications/Visual Studio Code.app/Contents/MacOS/Electron",
        ):
            assert not _looks_like_chumicro(self._holder(command)), (
                f"unexpectedly classified {command!r} as chumicro"
            )


class TestReportFailureWithPortHolders:
    """End-to-end coaching output for ``PORT_UNAVAILABLE`` includes
    the lsof diagnosis when something is holding the port.
    """

    def test_port_unavailable_with_holder_includes_pid(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from chumicro_deploy import recovery  # noqa: PLC0415

        # Stub the diagnose call so we don't actually shell out.
        monkeypatch.setattr(
            recovery, "diagnose_port_holders",
            lambda _p: [
                recovery.PortHolder(
                    pid=11421,
                    command=(
                        "/usr/bin/python "
                        "/workspace/run.py deploy wifi_only"  # noqa: CHU006 — workspace shim command name is data here
                    ),
                ),
            ],
        )

        fake = _FakeDeployer(
            [
                MicropythonTransportError(
                    "mpremote: failed to access /dev/cu.usbmodem112401 "
                    "(it may be in use by another program)",
                ),
            ] * 3,
        )
        sink, lines = _capturing_output()
        prompt = _ScriptedPrompt(["", ""])
        interactive = recovery.RecoveringDeployer(
            fake,  # type: ignore[arg-type]
            prompt=prompt,
            output=sink,
        )
        with pytest.raises(MicropythonTransportError):
            interactive.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

        joined = "\n".join(lines)
        # The PID + command must appear so the user can kill it.
        assert "11421" in joined
        assert "run.py deploy" in joined  # noqa: CHU006 — assertion against the workspace shim command name as data
        # The chumicro-stale heuristic must fire and surface the
        # actionable kill suggestion.
        assert "stale chumicro-deploy or mpremote" in joined
        assert "kill 11421" in joined

    def test_port_unavailable_with_external_holder_no_kill_hint(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """External app holding the port: list it but don't suggest
        ``kill`` (user might be deliberately running Mu / Thonny).
        """
        from chumicro_deploy import recovery  # noqa: PLC0415

        monkeypatch.setattr(
            recovery, "diagnose_port_holders",
            lambda _p: [
                recovery.PortHolder(
                    pid=4242,
                    command="/Applications/Mu.app/Contents/MacOS/Mu",
                ),
            ],
        )

        fake = _FakeDeployer(
            [
                MicropythonTransportError(
                    "mpremote: failed to access /dev/cu.x "
                    "(it may be in use by another program)",
                ),
            ] * 3,
        )
        sink, lines = _capturing_output()
        prompt = _ScriptedPrompt(["", ""])
        interactive = recovery.RecoveringDeployer(
            fake,  # type: ignore[arg-type]
            prompt=prompt,
            output=sink,
        )
        with pytest.raises(MicropythonTransportError):
            interactive.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

        joined = "\n".join(lines)
        # PID still surfaces so the user knows what's there.
        assert "4242" in joined
        assert "Mu" in joined
        # No kill suggestion for external apps.
        assert "kill 4242" not in joined
        assert "stale chumicro" not in joined

    def test_port_unavailable_with_no_holders_falls_through(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No holders detected (e.g., USB unplug): no diagnosis
        section, just the default recovery steps.
        """
        from chumicro_deploy import recovery  # noqa: PLC0415

        monkeypatch.setattr(
            recovery, "diagnose_port_holders", lambda _p: [],
        )

        fake = _FakeDeployer(
            [
                MicropythonTransportError(
                    "mpremote: failed to access /dev/cu.x",
                ),
            ] * 3,
        )
        sink, lines = _capturing_output()
        prompt = _ScriptedPrompt(["", ""])
        interactive = recovery.RecoveringDeployer(
            fake,  # type: ignore[arg-type]
            prompt=prompt,
            output=sink,
        )
        with pytest.raises(MicropythonTransportError):
            interactive.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

        joined = "\n".join(lines)
        # No diagnosis section, default recovery hints still present.
        assert "is currently held by" not in joined
        assert "Close any app" in joined

    def test_diagnosis_silent_on_subprocess_failure(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Best-effort.  If diagnose_port_holders raises, swallow it
        and fall through to the default recovery steps.
        """
        from chumicro_deploy import recovery  # noqa: PLC0415

        def boom(_port):
            raise RuntimeError("lsof exploded")

        monkeypatch.setattr(recovery, "diagnose_port_holders", boom)

        fake = _FakeDeployer(
            [
                MicropythonTransportError(
                    "mpremote: failed to access /dev/cu.x",
                ),
            ] * 3,
        )
        sink, lines = _capturing_output()
        prompt = _ScriptedPrompt(["", ""])
        interactive = recovery.RecoveringDeployer(
            fake,  # type: ignore[arg-type]
            prompt=prompt,
            output=sink,
        )
        with pytest.raises(MicropythonTransportError):
            interactive.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

        joined = "\n".join(lines)
        # No diagnosis section emitted, default hints still present.
        assert "is currently held by" not in joined
        assert "Close any app" in joined


# ---------------------------------------------------------------------------
# RecoveringDeployer (prompt=None): single attempt, no retry loop.
# CI / scripted flows.
# ---------------------------------------------------------------------------


class TestRecoveringDeployer:
    """``RecoveringDeployer`` with ``prompt=None`` reports the failure
    once and re-raises.

    Same coached output as the prompt-driven mode (classify + lsof
    diagnosis when applicable + fix steps), but no retry loop and
    no stdin probe, for CI / scripted flows where stdin has nowhere
    to go.
    """

    def test_returns_result_when_deploy_succeeds(self) -> None:
        from chumicro_deploy.recovery import RecoveringDeployer  # noqa: PLC0415

        ok = DeployResult(success=True, execute_output="hi\n")
        fake = _FakeDeployer([ok])
        sink, lines = _capturing_output()
        runner = RecoveringDeployer(
            fake,  # type: ignore[arg-type]
            output=sink,
        )

        result = runner.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

        assert result is ok
        assert fake.calls == 1
        # Success path emits no coaching chatter.
        assert lines == []

    def test_reports_and_reraises_on_transport_failure(self) -> None:
        """Single transport failure: one coached report, then re-raise."""
        from chumicro_deploy.recovery import RecoveringDeployer  # noqa: PLC0415

        fake = _FakeDeployer(
            [
                MicropythonTransportError(
                    "mpremote: failed to access /dev/cu.x "
                    "(it may be in use by another program)",
                ),
            ],
        )
        sink, lines = _capturing_output()
        runner = RecoveringDeployer(
            fake,  # type: ignore[arg-type]
            output=sink,
        )

        with pytest.raises(MicropythonTransportError):
            runner.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

        # Underlying deployer was called exactly once, no retry.
        assert fake.calls == 1
        joined = "\n".join(lines)
        # The "1/1" header makes the no-retry contract explicit in
        # the output a CI log captures.
        assert "1/1" in joined
        assert "port_unavailable" in joined
        # Canonical fix hints still present.
        assert "Close any app" in joined.lower() or "close any app" in joined.lower()

    def test_diff_signature_mirrors_deployer(self) -> None:
        """``deploy_diff`` accepts clean + wipe + on_file_deleted just
        like the underlying :class:`Deployer`, and forwards them.
        """
        from chumicro_deploy.recovery import RecoveringDeployer  # noqa: PLC0415

        ok = DeployResult(success=True)
        fake = _FakeDeployer([ok])
        sink, _lines = _capturing_output()
        runner = RecoveringDeployer(
            fake,  # type: ignore[arg-type]
            output=sink,
        )
        result = runner.deploy_diff(
            _DUMMY_SOURCE,  # type: ignore[arg-type]
            clean=False,
            wipe=True,
            on_file_deleted=lambda _path: None,
        )
        assert result is ok
        assert fake.last_wipe is True
        assert fake.last_clean is False  # forwarded through the wrapper

    def test_diff_clean_defaults_true(self) -> None:
        """clean-slate is the default.  The wrapper forwards clean=True."""
        from chumicro_deploy.recovery import RecoveringDeployer  # noqa: PLC0415

        fake = _FakeDeployer([DeployResult(success=True)])
        sink, _lines = _capturing_output()
        runner = RecoveringDeployer(fake, output=sink)  # type: ignore[arg-type]
        runner.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]
        assert fake.last_clean is True

    def test_includes_port_holder_diagnosis(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """F6 diagnosis fires for ``PORT_UNAVAILABLE`` failures
        in the non-interactive path too.
        """
        from chumicro_deploy import recovery  # noqa: PLC0415

        monkeypatch.setattr(
            recovery, "diagnose_port_holders",
            lambda _port: [
                recovery.PortHolder(
                    pid=4242,
                    command="/usr/bin/python /path/run.py deploy hello_world",  # noqa: CHU006 — workspace shim command name is data here
                ),
            ],
        )

        fake = _FakeDeployer(
            [
                MicropythonTransportError(
                    "mpremote: failed to access /dev/cu.usbmodem112401 "
                    "(it may be in use by another program)",
                ),
            ],
        )
        sink, lines = _capturing_output()
        runner = recovery.RecoveringDeployer(
            fake,  # type: ignore[arg-type]
            output=sink,
        )
        with pytest.raises(MicropythonTransportError):
            runner.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

        joined = "\n".join(lines)
        assert "4242" in joined
        assert "run.py deploy" in joined  # noqa: CHU006 — assertion against the workspace shim command name as data
        assert "kill 4242" in joined  # chumicro-stale heuristic fires

    def test_traceback_result_is_reported(self) -> None:
        """A ``DeployResult`` with ``success=False`` + ``traceback``
        gets reported (not raised), same contract as RecoveringDeployer.
        """
        from chumicro_deploy.recovery import RecoveringDeployer  # noqa: PLC0415

        bad = DeployResult(
            success=False,
            traceback="Traceback (most recent call last):\n  ZeroDivisionError",
            execute_output="",
        )
        fake = _FakeDeployer([bad])
        sink, lines = _capturing_output()
        runner = RecoveringDeployer(
            fake,  # type: ignore[arg-type]
            output=sink,
        )

        result = runner.deploy_diff(_DUMMY_SOURCE)  # type: ignore[arg-type]

        assert result is bad
        joined = "\n".join(lines)
        assert "traceback" in joined.lower()
        assert "ZeroDivisionError" in joined
