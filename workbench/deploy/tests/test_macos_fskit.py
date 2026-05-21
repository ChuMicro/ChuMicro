"""Tests for :mod:`chumicro_deploy.macos_fskit`."""

from __future__ import annotations

import subprocess
from collections.abc import Callable

from chumicro_deploy.macos_fskit import (
    MACOS_FSKIT_RECOVERY_COMMAND,
    detect_fskit_wedge,
)


def _scripted_runner(
    outcomes: list[subprocess.CompletedProcess | Exception],
) -> tuple[Callable[..., subprocess.CompletedProcess], list[list[str]]]:
    """Return a fake subprocess.run that replays *outcomes* in order.

    Also captures each call's argv so tests can assert the exact
    commands that were issued.
    """
    calls: list[list[str]] = []
    remaining = list(outcomes)

    def _runner(
        argv: list[str],
        *,
        capture_output: bool = False,
        text: bool = False,
        check: bool = False,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess:
        calls.append(list(argv))
        if not remaining:
            raise AssertionError(
                f"Scripted runner called {len(calls)}× but outcomes exhausted",
            )
        outcome = remaining.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return _runner, calls


def _completed(
    argv: list[str], returncode: int, stdout: str = "",
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=argv, returncode=returncode, stdout=stdout, stderr="",
    )


def test_detect_returns_false_on_non_darwin() -> None:
    # Non-darwin short-circuits before any subprocess call.
    runner, calls = _scripted_runner(
        [
            AssertionError("runner must not be called on non-darwin"),
        ],
    )
    assert detect_fskit_wedge(runner=runner, platform="linux") is False
    assert calls == []


def test_detect_true_when_diskarbitrationd_in_uninterruptible_wait() -> None:
    # pgrep returns PID 351, ps reports state "Us": the smoking-gun
    # uninterruptible-wait state that indicates the FSKit wedge.
    runner, calls = _scripted_runner(
        [
            _completed(["pgrep", "diskarbitrationd"], 0, "351\n"),
            _completed(["ps", "-o", "state=", "-p", "351"], 0, "Us\n"),
        ],
    )
    assert detect_fskit_wedge(runner=runner, platform="darwin") is True
    assert calls == [
        ["pgrep", "diskarbitrationd"],
        ["ps", "-o", "state=", "-p", "351"],
    ]


def test_detect_false_when_diskarbitrationd_healthy() -> None:
    # Healthy daemon sits in "Ss" (interruptible sleep), no U in
    # the state column means no wedge.
    runner, _calls = _scripted_runner(
        [
            _completed(["pgrep", "diskarbitrationd"], 0, "351\n"),
            _completed(["ps", "-o", "state=", "-p", "351"], 0, "Ss\n"),
        ],
    )
    assert detect_fskit_wedge(runner=runner, platform="darwin") is False


def test_detect_false_when_pgrep_finds_no_process() -> None:
    # pgrep returns non-zero when nothing matches, treat as "no
    # wedge to detect" rather than as an error.
    runner, _calls = _scripted_runner(
        [
            _completed(["pgrep", "diskarbitrationd"], 1, ""),
        ],
    )
    assert detect_fskit_wedge(runner=runner, platform="darwin") is False


def test_detect_false_when_pgrep_stdout_is_empty() -> None:
    # Edge case: pgrep exited zero but printed nothing.  Defensively
    # treat as not-wedged rather than falling through to ps with an
    # empty PID argument.
    runner, _calls = _scripted_runner(
        [
            _completed(["pgrep", "diskarbitrationd"], 0, "\n"),
        ],
    )
    assert detect_fskit_wedge(runner=runner, platform="darwin") is False


def test_detect_false_when_pgrep_prints_non_numeric() -> None:
    # Defense against a corrupted shell env where pgrep emits
    # something weird.  Never pass it to ps.
    runner, _calls = _scripted_runner(
        [
            _completed(["pgrep", "diskarbitrationd"], 0, "not-a-pid\n"),
        ],
    )
    assert detect_fskit_wedge(runner=runner, platform="darwin") is False


def test_detect_false_when_ps_fails() -> None:
    # If the daemon dies between pgrep and ps, ps will exit non-zero.
    # That's not a wedge, it's just a race.
    runner, _calls = _scripted_runner(
        [
            _completed(["pgrep", "diskarbitrationd"], 0, "351\n"),
            _completed(["ps", "-o", "state=", "-p", "351"], 1, ""),
        ],
    )
    assert detect_fskit_wedge(runner=runner, platform="darwin") is False


def test_detect_false_when_pgrep_missing() -> None:
    # Truly minimal systems may not have pgrep, so fail open.
    runner, _calls = _scripted_runner([FileNotFoundError("pgrep")])
    assert detect_fskit_wedge(runner=runner, platform="darwin") is False


def test_detect_false_when_pgrep_times_out() -> None:
    # A timeout reaching pgrep itself means the system is in such
    # bad shape that we can't reliably diagnose, so don't block retry.
    runner, _calls = _scripted_runner(
        [subprocess.TimeoutExpired(cmd="pgrep", timeout=2.0)],
    )
    assert detect_fskit_wedge(runner=runner, platform="darwin") is False


def test_detect_false_when_ps_times_out() -> None:
    runner, _calls = _scripted_runner(
        [
            _completed(["pgrep", "diskarbitrationd"], 0, "351\n"),
            subprocess.TimeoutExpired(cmd="ps", timeout=2.0),
        ],
    )
    assert detect_fskit_wedge(runner=runner, platform="darwin") is False


def test_detect_true_with_leading_whitespace_state() -> None:
    # ``ps -o state=`` on macOS often emits a leading space before
    # the state letter; strip/contains checks must still recognize
    # the wedge.
    runner, _calls = _scripted_runner(
        [
            _completed(["pgrep", "diskarbitrationd"], 0, "351\n"),
            _completed(["ps", "-o", "state=", "-p", "351"], 0, "   U   \n"),
        ],
    )
    assert detect_fskit_wedge(runner=runner, platform="darwin") is True


def test_recovery_command_mentions_expected_daemons() -> None:
    # Smoke check.  The pasted command is the contract between this
    # module and the recovery coaching, so catch silent drift.
    assert "sudo killall -9" in MACOS_FSKIT_RECOVERY_COMMAND
    assert "com.apple.fskit.msdos" in MACOS_FSKIT_RECOVERY_COMMAND
    assert "fskit_helper" in MACOS_FSKIT_RECOVERY_COMMAND
    assert "fskitd" in MACOS_FSKIT_RECOVERY_COMMAND
    assert "fskit_agent" in MACOS_FSKIT_RECOVERY_COMMAND
    assert "diskarbitrationd" in MACOS_FSKIT_RECOVERY_COMMAND
    assert "DiskArbitrationAgent" in MACOS_FSKIT_RECOVERY_COMMAND
    assert "launchctl kickstart" not in MACOS_FSKIT_RECOVERY_COMMAND


def test_doc_recovery_block_matches_constant() -> None:
    # docs/troubleshooting/macos-circuitpy.md hardcodes the recovery
    # command in a `bash` code block.  The constant in this module is
    # the single source of truth, so assert the doc literally contains
    # the string so the two cannot drift.
    from pathlib import Path

    doc_path = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "troubleshooting"
        / "macos-circuitpy.md"
    )
    if not doc_path.is_file():
        # Doc tree may be absent in stripped-down install layouts.  The
        # constant assertion above is the load-bearing check.
        return
    assert MACOS_FSKIT_RECOVERY_COMMAND in doc_path.read_text(encoding="utf-8"), (
        "docs/troubleshooting/macos-circuitpy.md does not contain the "
        "current MACOS_FSKIT_RECOVERY_COMMAND verbatim — they have drifted."
    )
