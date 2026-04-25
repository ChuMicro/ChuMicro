"""Interactive demo for chumicro-repl robustness on real boards.

Run this against plugged-in hardware to see the coached failure
output ``chumicro-repl`` produces when things go wrong.  Unlike the
pytest-based functional tests, this is an *interactive* script — it
prompts you to physically create failure conditions (unplug USB,
hold the port open in another tool, upload code that ignores
Ctrl-C) and then shows you what the recovery layer prints in each
case.

Run::

    .venv/bin/python workbench/repl/examples/demo_repl_robustness.py

The script reads ``devices.yml``, lets you pick a board, and walks
through a scenario menu.  Every scenario maps to one
:class:`~chumicro_repl.recovery.ReplFailureKind` (or to the
auto-reconnect path on the in-loop side), so running the menu
end-to-end exercises the full hand-holding surface against real
hardware.

Why a script instead of a pytest?  The failures worth showing all
require a human action (unplug the cable, open another mpremote,
flash a tight loop).  Pytest can't do those — it can only assert
on outcomes.  This script is the thing to run when you want to
*see* the hand-holding, not prove it works in CI.

Mirrors :mod:`workbench.deploy.examples.demo_recovery_hand_holding`
in shape and terminal styling so the two demos feel the same.
"""

from __future__ import annotations

import io
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Make scripts/ importable the same way the pytest conftest does.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from chumicro_deploy import Device  # noqa: E402
from chumicro_repl import (  # noqa: E402
    ExitCode,
    InteractiveReplSession,
    ReplFailureKind,
    ReplSession,
    classify_session_failure,
    tail,
)
from chumicro_repl.highlight import strip_ansi_sequences  # noqa: E402
from device_config import (  # type: ignore[import-not-found]  # noqa: E402
    DeviceConfigError,
    DeviceEntry,
    load_device_registry,
)

# ---------------------------------------------------------------------------
# Terminal helpers — ANSI colour when isatty, plain text otherwise
# ---------------------------------------------------------------------------

_IS_TTY = sys.stdout.isatty()
_BOLD = "\033[1m" if _IS_TTY else ""
_DIM = "\033[2m" if _IS_TTY else ""
_CYAN = "\033[36m" if _IS_TTY else ""
_YELLOW = "\033[33m" if _IS_TTY else ""
_GREEN = "\033[32m" if _IS_TTY else ""
_RED = "\033[31m" if _IS_TTY else ""
_RESET = "\033[0m" if _IS_TTY else ""


def _print_banner(text: str) -> None:
    bar = "━" * min(len(text), 72)
    print(f"\n{_BOLD}{_CYAN}{bar}")
    print(text)
    print(f"{bar}{_RESET}")


def _print_step(text: str) -> None:
    print(f"\n{_BOLD}{_YELLOW}▶ {text}{_RESET}")


def _print_note(text: str) -> None:
    print(f"{_DIM}  {text}{_RESET}")


def _print_ok(text: str) -> None:
    print(f"{_GREEN}✓ {text}{_RESET}")


def _print_warn(text: str) -> None:
    print(f"{_RED}⚠ {text}{_RESET}")


def _confirm(prompt_text: str, *, default_yes: bool = True) -> bool:
    suffix = " [Y/n] " if default_yes else " [y/N] "
    response = input(prompt_text + suffix).strip().lower()
    if not response:
        return default_yes
    return response[0] == "y"


def _pause(message: str = "Press Enter when ready…") -> None:
    input(f"{_CYAN}{message}{_RESET}")


# ---------------------------------------------------------------------------
# Board context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BoardContext:
    """Per-board state passed into each scenario."""

    entry: DeviceEntry
    device: Device


def _board_tag(context: BoardContext) -> str:
    entry = context.entry
    description = entry.description or entry.identifier
    return (
        f"{_BOLD}{description}{_RESET} "
        f"[{entry.runtime} · id={entry.identifier} · {entry.address}]"
    )


def _build_device(entry: DeviceEntry) -> Device:
    return Device(
        transport=entry.runtime,
        address=entry.address,
        baudrate=entry.serial_baudrate,
        circuitpy_drive_path=(
            Path(entry.circuitpy_drive_path) if entry.circuitpy_drive_path else None
        ),
    )


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def scenario_happy_path(context: BoardContext) -> None:
    """Open a session, exec one print, close.  Confirms the wiring works."""
    _print_step(f"HAPPY PATH on {_board_tag(context)}")
    _print_note(
        "Confirms the board is reachable before running any failure "
        "scenarios — if this scenario fails, fix the cable / port / "
        "firmware first."
    )
    try:
        with ReplSession(context.device) as session:
            output = session.exec("print('chu-repl-demo-happy')")
        if "chu-repl-demo-happy" in output:
            _print_ok("Session opened, exec round-tripped, close clean.")
        else:
            _print_warn(f"Unexpected output: {output!r}")
    except Exception as error:
        _print_warn(f"Happy path failed: {type(error).__name__}: {error}")
        _print_note(
            "Don't run the failure scenarios until this one passes — "
            "their assertions assume a working baseline."
        )


def scenario_port_not_found(context: BoardContext) -> None:
    """Open a session against a bogus address — expect PORT_NOT_FOUND coaching."""
    _print_step(
        f"PORT_NOT_FOUND coaching: target a bogus address on "
        f"{_board_tag(context)}"
    )
    _print_note(
        "No physical action needed — we point InteractiveReplSession "
        "at /dev/cu.bogus-chumicro-demo and watch the classifier + "
        "plan fire."
    )
    bogus = Device(
        transport=context.entry.runtime,
        address="/dev/cu.bogus-chumicro-demo",
        baudrate=context.entry.serial_baudrate,
    )
    wrapper = InteractiveReplSession(bogus, max_attempts=2)
    try:
        with wrapper:
            _print_warn("Unexpectedly opened a bogus port — re-check the demo.")
    except OSError as error:
        kind = classify_session_failure(error)
        if kind is ReplFailureKind.PORT_NOT_FOUND:
            _print_ok(
                "Classifier picked PORT_NOT_FOUND.  See coached "
                "fix-steps above."
            )
        else:
            _print_warn(
                f"Classifier picked {kind.value!r}; expected "
                f"{ReplFailureKind.PORT_NOT_FOUND.value!r}.  Underlying "
                f"error: {error}"
            )


def scenario_port_busy(context: BoardContext) -> None:
    """User opens the port elsewhere; expect PORT_BUSY coaching."""
    _print_step(f"PORT_BUSY coaching on {_board_tag(context)}")
    _print_note(
        "This one needs a hand: open the port in another process "
        "before we try (e.g. `mpremote connect <addr>` in another "
        "terminal, or `screen <addr> 115200`).  The classifier will "
        "see EBUSY (or 'resource busy') and pick PORT_BUSY."
    )
    if not _confirm(
        f"Have you opened {context.entry.address} in another tool?",
        default_yes=False,
    ):
        _print_note("Skipping PORT_BUSY scenario.")
        return
    wrapper = InteractiveReplSession(context.device, max_attempts=2)
    try:
        with wrapper:
            _print_warn(
                "Port wasn't busy after all — close the other tool "
                "and re-run this scenario to see the coaching."
            )
    except OSError as error:
        kind = classify_session_failure(error)
        if kind is ReplFailureKind.PORT_BUSY:
            _print_ok("Classifier picked PORT_BUSY.  See plan above.")
        else:
            _print_warn(
                f"Classifier picked {kind.value!r} (expected "
                f"PORT_BUSY).  On some platforms pyserial reports "
                f"'permission denied' for a busy port — that's also "
                f"acceptable here.  Underlying error: {error}"
            )


def scenario_raw_repl_unresponsive(context: BoardContext) -> None:
    """Board ignores Ctrl-C — expect RAW_REPL_UNRESPONSIVE coaching.

    To actually trigger this on real hardware: deploy a tight loop
    that holds the GIL (no I/O, no time.sleep) before running the
    scenario.  Most "tight loop" demos still yield enough that
    Ctrl-A breaks out — disabling KeyboardInterrupt during a
    machine.disable_irq()-protected block is the most reliable
    way to make the board genuinely unresponsive.  Skipping this
    scenario when you can't easily produce the condition is fine;
    the classifier itself is unit-tested.
    """
    _print_step(f"RAW_REPL_UNRESPONSIVE coaching on {_board_tag(context)}")
    _print_note(
        "Hardest scenario to trigger on real hardware.  The board "
        "must be in a state where it does not respond to Ctrl-A "
        "(typical causes: running code that disables interrupts, "
        "stuck in a long C-level call, or running firmware that "
        "doesn't speak raw REPL)."
    )
    if not _confirm(
        "Is the board currently stuck (e.g., running an "
        "interrupt-disabled tight loop)?",
        default_yes=False,
    ):
        _print_note(
            "Skipping RAW_REPL_UNRESPONSIVE scenario — classifier is "
            "unit-tested in workbench/repl/tests/test_recovery.py."
        )
        return
    wrapper = InteractiveReplSession(
        context.device, max_attempts=2, connect_timeout=2.0,
    )
    try:
        with wrapper:
            _print_warn(
                "Session opened — board wasn't actually stuck.  Try "
                "deploying a tighter loop and re-run."
            )
    except Exception as error:
        kind = classify_session_failure(error)
        if kind is ReplFailureKind.RAW_REPL_UNRESPONSIVE:
            _print_ok("Classifier picked RAW_REPL_UNRESPONSIVE.")
        else:
            _print_warn(
                f"Classifier picked {kind.value!r} (expected "
                f"RAW_REPL_UNRESPONSIVE).  Underlying: {error}"
            )


def scenario_disconnect_during_tail(context: BoardContext) -> None:
    """Yank the cable while tail() is running, replug, see auto-reconnect."""
    _print_step(f"AUTO-RECONNECT during tail() on {_board_tag(context)}")
    _print_note(
        "tail()'s default reconnect window is 30 seconds.  We'll "
        "start a 60-second tail and ask you to unplug + replug "
        "the USB cable while it runs.  The output should show "
        "'device disconnected', a 'retrying' notice, then "
        "'reconnected' once the device re-enumerates."
    )
    if not _confirm("Ready to unplug + replug the board during the tail?"):
        _print_note("Skipping auto-reconnect scenario.")
        return
    captured = io.StringIO()

    class _Tee:
        def write(self, data: str) -> int:
            sys.stdout.write(data)
            captured.write(data)
            return len(data)

        def flush(self) -> None:
            sys.stdout.flush()

    print()  # spacer before tail output
    result = tail(
        context.device,
        seconds=60.0,
        fail_on_traceback=False,
        output=_Tee(),
        reconnect_seconds=30.0,
        reconnect_interval=0.5,
    )
    plain = strip_ansi_sequences(captured.getvalue())
    if result is ExitCode.OK and "reconnected" in plain:
        _print_ok(
            "Disconnect notice + retry + reconnect all rendered "
            "and the tail kept running."
        )
    elif result is ExitCode.DISCONNECTED and "giving up" in plain:
        _print_warn(
            "Reconnect budget elapsed before you replugged.  "
            "Re-run this scenario and replug faster, or pass a "
            "larger reconnect_seconds."
        )
    elif "disconnected" not in plain:
        _print_note(
            "Tail returned without seeing a disconnect — you may "
            "not have unplugged in time, or the OS hasn't surfaced "
            "the disconnect yet."
        )
    else:
        _print_warn(f"Unexpected outcome: result={result.name}.")


def scenario_user_abort_during_reconnect(context: BoardContext) -> None:
    """Yank the cable, then abort with Ctrl-C — verify clean exit."""
    _print_step(
        f"ABORT during reconnect on {_board_tag(context)} "
        "(programmatic, no terminal Ctrl-C needed)"
    )
    _print_note(
        "Demonstrates the InteractiveReplSession 'q' abort path "
        "after a session-start failure: we point the wrapper at a "
        "bogus address, pre-script 'q' as the response to the "
        "retry prompt, and confirm it re-raises immediately "
        "instead of looping."
    )
    bogus = Device(
        transport=context.entry.runtime,
        address="/dev/cu.bogus-chumicro-demo",
        baudrate=context.entry.serial_baudrate,
    )
    wrapper = InteractiveReplSession(
        bogus,
        max_attempts=5,
        prompt=lambda _text: "q",
        output=lambda line: print(f"  {_DIM}{line}{_RESET}"),
    )
    try:
        with wrapper:
            _print_warn("Wrapper opened a bogus port — re-check the demo.")
    except OSError:
        _print_ok(
            "User-typed 'q' aborted after the first attempt.  Clean "
            "exit, no infinite retry."
        )


# ---------------------------------------------------------------------------
# Menu loop
# ---------------------------------------------------------------------------


_SCENARIOS: tuple[tuple[str, Callable[[BoardContext], None]], ...] = (
    ("Happy path (verify wiring)", scenario_happy_path),
    ("PORT_NOT_FOUND coaching (bogus address)", scenario_port_not_found),
    ("PORT_BUSY coaching (open port elsewhere first)", scenario_port_busy),
    (
        "RAW_REPL_UNRESPONSIVE coaching (board must be stuck)",
        scenario_raw_repl_unresponsive,
    ),
    (
        "Auto-reconnect during tail() (yank + replug cable)",
        scenario_disconnect_during_tail,
    ),
    (
        "Abort during reconnect ('q' at retry prompt)",
        scenario_user_abort_during_reconnect,
    ),
)


def _pick_board(devices: list[DeviceEntry]) -> DeviceEntry:
    print()
    _print_banner("Available boards from devices.yml")
    for index, entry in enumerate(devices, start=1):
        description = entry.description or entry.identifier
        print(
            f"  {_BOLD}{index}{_RESET}. {description} "
            f"[{entry.runtime} · {entry.address}]"
        )
    while True:
        choice = input(f"\nPick a board [1-{len(devices)}]: ").strip()
        try:
            index = int(choice)
        except ValueError:
            _print_warn("Type a number.")
            continue
        if 1 <= index <= len(devices):
            return devices[index - 1]
        _print_warn(f"Out of range; pick 1–{len(devices)}.")


def _run_menu(context: BoardContext) -> None:
    while True:
        _print_banner(f"Scenarios for {_board_tag(context)}")
        for index, (name, _func) in enumerate(_SCENARIOS, start=1):
            print(f"  {_BOLD}{index}{_RESET}. {name}")
        print(f"  {_BOLD}q{_RESET}. back to board selection")
        choice = input("\nPick a scenario: ").strip().lower()
        if choice in ("q", "quit", "exit", ""):
            return
        try:
            index = int(choice) - 1
        except ValueError:
            _print_warn("Type a scenario number, or 'q' to leave.")
            continue
        if not 0 <= index < len(_SCENARIOS):
            _print_warn(f"Out of range; pick 1–{len(_SCENARIOS)}.")
            continue
        _, func = _SCENARIOS[index]
        try:
            func(context)
        except KeyboardInterrupt:
            _print_warn("Aborted by Ctrl-C; back to scenario menu.")
        _pause("Press Enter to return to the scenario menu…")


def main() -> int:
    _print_banner("chumicro-repl robustness demo")
    print(
        "Walks every recovery surface the package exposes: the "
        "session-start classifier (PORT_NOT_FOUND / PORT_BUSY / "
        "PORT_PERMISSION_DENIED / RAW_REPL_UNRESPONSIVE / "
        "UNKNOWN), the InteractiveReplSession coaching loop, and "
        "the auto-reconnect loop in tail()."
    )
    try:
        devices, _defaults = load_device_registry()
    except (DeviceConfigError, FileNotFoundError, OSError) as load_error:
        _print_warn(f"Couldn't load devices.yml: {load_error}")
        _print_note(
            "Run `python scripts/run.py setup` to scaffold one, then "
            "fill in your boards."
        )
        return 1
    if not devices:
        _print_warn("No devices configured in devices.yml — add one and re-run.")
        return 1
    while True:
        entry = _pick_board(devices)
        context = BoardContext(entry=entry, device=_build_device(entry))
        _run_menu(context)
        if not _confirm("Pick another board?", default_yes=False):
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
