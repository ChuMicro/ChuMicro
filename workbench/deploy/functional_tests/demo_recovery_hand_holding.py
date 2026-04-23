"""Interactive demo for :class:`InteractiveDeployer` hand-holding on real boards.

Run this against plugged-in hardware to see the coached failure
output you get from ``chumicro-deploy`` when things go wrong.
Unlike the pytest-based functional tests, this is an *interactive*
script — it prompts you to physically create failure conditions
(unplug USB, eject the CIRCUITPY drive) and then shows you what
the recovery-layer CLI prints in each case.

Run::

    .venv/bin/python workbench/deploy/functional_tests/demo_recovery_hand_holding.py

The script reads ``devices.yml``, lists every configured board, and
walks you through a scenario menu per board.  Every scenario maps
to one :class:`~chumicro_deploy.recovery.DeployFailureKind`, so
running the menu end-to-end exercises the full coaching surface
against real hardware.

Why a script instead of a pytest?  The failures worth showing all
require a human action (unplug the cable, tap RESET, eject the
drive).  Pytest can't do those — it can only assert on outcomes.
This script is the thing to run when you want to *see* the
hand-holding, not prove it works in CI.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Make scripts/ importable the same way the pytest conftest does.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from chumicro_deploy import (  # noqa: E402
    CircuitpythonTransportError,
    Deployer,
    Device,
    FileMapSource,
    InteractiveDeployer,
    MicropythonTransportError,
    classify_deploy_failure,
)
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
    input(f"{_DIM}{message}{_RESET}")


# ---------------------------------------------------------------------------
# Board descriptor + scenario plumbing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BoardContext:
    """Per-board state the scenarios read from."""

    entry: DeviceEntry
    device_ram: Device
    device_flash: Device | None

    @property
    def runtime(self) -> str:
        return self.entry.runtime

    @property
    def label(self) -> str:
        return f"{self.entry.description} ({self.entry.identifier})"


def _build_ram_device(entry: DeviceEntry) -> Device:
    return Device(
        transport=entry.runtime,
        address=entry.address,
        baudrate=entry.serial_baudrate,
        deploy_mode="ram",
    )


def _build_flash_device(entry: DeviceEntry) -> Device | None:
    # Flash mode only makes sense on CP with a mounted drive.  On MP
    # this maps to mpremote copy-mode and does not need a drive, so
    # build a flash device for MP too.
    if entry.runtime == "circuitpython":
        drive_path = entry.circuitpy_drive_path
        if not drive_path or not Path(drive_path).is_dir():
            return None
        return Device(
            transport=entry.runtime,
            address=entry.address,
            baudrate=entry.serial_baudrate,
            deploy_mode="flash",
            circuitpy_drive_path=Path(drive_path),
        )
    return Device(
        transport=entry.runtime,
        address=entry.address,
        baudrate=entry.serial_baudrate,
        deploy_mode="flash",
    )


def _entrypoint_for(runtime: str) -> str:
    return "/code.py" if runtime == "circuitpython" else "/main.py"


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def scenario_happy_path_ram(context: BoardContext) -> bool:
    """Baseline — confirm the board is wired right before inducing failures."""
    _print_step("Scenario 0: happy-path RAM-mode deploy (baseline)")
    _print_note(
        "Sanity check.  No hand-holding expected.  Deploys a single "
        "print() entrypoint and verifies the output comes back.  If "
        "this fails the board is in a bad state — fix that before "
        "running the failure-path scenarios below."
    )
    interactive = InteractiveDeployer(
        Deployer(context.device_ram),
        max_attempts=1,  # no retry loop on the baseline run
    )
    entrypoint = _entrypoint_for(context.runtime)
    source = FileMapSource(
        {entrypoint: "print('chu-demo-ok')\n"}, entrypoint=entrypoint,
    )
    try:
        result = interactive.deploy(source)
    except (CircuitpythonTransportError, MicropythonTransportError) as error:
        _print_warn(f"Baseline deploy failed: {error}")
        return False
    if result.success and "chu-demo-ok" in result.execute_output:
        _print_ok("Baseline deploy succeeded.")
        return True
    _print_warn(f"Baseline deploy produced unexpected output: {result.execute_output!r}")
    return False


def scenario_traceback_returned(context: BoardContext) -> bool:
    """Deploy code that raises — expect the traceback coaching block."""
    _print_step("Scenario 1: entrypoint raises (TRACEBACK_RETURNED)")
    _print_note(
        "Deploys an entrypoint that raises a ZeroDivisionError.  The "
        "InteractiveDeployer should NOT retry — source-level bugs "
        "aren't fixable by replugging.  Instead you should see a "
        "'--- traceback ---' block followed by the recovery plan "
        "(fix source, open REPL, etc.)."
    )
    interactive = InteractiveDeployer(
        Deployer(context.device_ram),
        max_attempts=1,
    )
    entrypoint = _entrypoint_for(context.runtime)
    source = FileMapSource(
        {
            entrypoint: (
                "print('about-to-raise')\n"
                "1 / 0\n"
                "print('unreachable')\n"
            ),
        },
        entrypoint=entrypoint,
    )
    result = interactive.deploy(source)
    if result.traceback is None:
        _print_warn("Expected a traceback but none was returned.")
        return False
    if "ZeroDivisionError" not in (result.traceback or ""):
        _print_warn(
            f"Traceback did not mention ZeroDivisionError: "
            f"{result.traceback!r}"
        )
        return False
    _print_ok(
        "Traceback coaching rendered and returned without retrying — "
        "expected behaviour for source-level bugs."
    )
    return True


def scenario_port_unavailable(context: BoardContext) -> bool:
    """Walk the user through a physical unplug → retry → replug cycle."""
    _print_step("Scenario 2: serial port unavailable (PORT_UNAVAILABLE)")
    _print_note(
        "This scenario requires you to PHYSICALLY UNPLUG the USB "
        "cable on the target board before the deploy starts.  The "
        "script will attempt to deploy, hit 'Failed to open serial "
        "port', surface the coaching, and prompt you to retry.  "
        "Plug the board back in, wait for it to re-enumerate, then "
        "press Enter at the retry prompt."
    )
    if not _confirm(
        f"Ready to run the unplug scenario on "
        f"{context.entry.address!r}?",
    ):
        _print_note("Skipped.")
        return True
    print(
        f"{_RED}UNPLUG{_RESET} the board now, then press Enter to "
        f"start the deploy.",
    )
    _pause()
    interactive = InteractiveDeployer(
        Deployer(context.device_ram),
        max_attempts=3,
    )
    entrypoint = _entrypoint_for(context.runtime)
    source = FileMapSource(
        {entrypoint: "print('chu-demo-unplug-recovery')\n"},
        entrypoint=entrypoint,
    )
    try:
        result = interactive.deploy(source)
    except (CircuitpythonTransportError, MicropythonTransportError) as error:
        kind = classify_deploy_failure(error)
        _print_warn(
            f"Could not recover after {interactive._max_attempts} "  # noqa: SLF001 — demo introspection
            f"attempts.  Final kind: {kind.value}.  Underlying: {error}"
        )
        return False
    if result.success:
        _print_ok(
            "Recovered from PORT_UNAVAILABLE and deploy succeeded."
        )
        return True
    _print_warn(
        f"Deploy returned without the expected output: "
        f"{result.execute_output!r}"
    )
    return False


def scenario_circuitpy_drive_missing(context: BoardContext) -> bool:
    """CP flash only — walk the user through an eject → retry cycle."""
    _print_step("Scenario 3: CIRCUITPY drive missing (CIRCUITPY_DRIVE_MISSING)")
    if context.runtime != "circuitpython":
        _print_note("Skipped — this scenario is CircuitPython-only.")
        return True
    if context.device_flash is None:
        _print_warn(
            "No circuitpy_drive_path configured for this board in "
            "devices.yml and the drive is not currently mounted — "
            "can't run the flash-mode scenario."
        )
        return False
    _print_note(
        "This scenario requires you to EJECT the CIRCUITPY drive "
        "before the deploy starts (Finder/Files: Eject).  The "
        "script will attempt a flash-mode deploy, hit the "
        "'CIRCUITPY drive not found' path, surface the coaching, "
        "and prompt you to retry.  Tap RESET on the board (or "
        "unplug/replug) to remount, then press Enter at the retry "
        "prompt."
    )
    if not _confirm("Ready to run the eject-drive scenario?"):
        _print_note("Skipped.")
        return True
    print(
        f"{_RED}EJECT{_RESET} the CIRCUITPY drive now "
        f"({context.entry.circuitpy_drive_path!r}), then press "
        f"Enter to start the deploy.",
    )
    _pause()
    interactive = InteractiveDeployer(
        Deployer(context.device_flash),
        max_attempts=3,
    )
    source = FileMapSource(
        {"/code.py": "print('chu-demo-drive-recovery')\n"},
        entrypoint="/code.py",
    )
    try:
        result = interactive.deploy(source)
    except CircuitpythonTransportError as error:
        _print_warn(
            f"Could not recover after retries.  Underlying: {error}"
        )
        return False
    if result.success and "chu-demo-drive-recovery" in result.execute_output:
        _print_ok("Recovered from CIRCUITPY_DRIVE_MISSING.")
        return True
    _print_warn(
        f"Deploy returned without the expected output: "
        f"{result.execute_output!r}"
    )
    return False


def scenario_bootloader_reset_silent(context: BoardContext) -> bool:
    """CP only — verify the disconnect fix: no spurious warnings on intentional reset."""
    _print_step(
        "Scenario 4: intentional bootloader reset emits no warnings",
    )
    if context.runtime != "circuitpython":
        _print_note(
            "Skipped — this scenario exercises the CP transport's "
            "reset_into_bootloader + disconnect dance."
        )
        return True
    _print_note(
        "Connects, triggers reset_into_bootloader, disconnects.  "
        "Before the fix you would see two 'WARNING: Failed to ...' "
        "lines because disconnect() tried to talk to a board that "
        "was already rebooting.  After the fix the sequence is "
        "silent — _reset_pending skips the restore dance.\n"
        "  Note: your CP board WILL enter the UF2 bootloader.  "
        "Afterwards you'll need to tap RESET (or unplug/replug) "
        "to get it out of the bootloader and back to CIRCUITPY."
    )
    if not _confirm(
        "Proceed?  (Board will enter the UF2 bootloader)",
        default_yes=False,
    ):
        _print_note("Skipped.")
        return True
    transport = context.device_ram.create_transport()
    try:
        transport.connect()
    except CircuitpythonTransportError as error:
        _print_warn(f"Could not connect to board: {error}")
        return False
    try:
        dispatched = transport.reset_into_bootloader()
    finally:
        transport.disconnect()
    if not dispatched:
        _print_warn("reset_into_bootloader returned False — unexpected on CP.")
        return False
    _print_ok(
        "reset_into_bootloader dispatched and disconnect returned "
        "without printing warnings.  If you saw zero 'WARNING:' "
        "lines scroll past, the fix is working."
    )
    _print_note(
        "Tap RESET on the board now (or unplug/replug) to exit the "
        "UF2 bootloader before running another scenario."
    )
    _pause("Press Enter when the board is back on CIRCUITPY.")
    return True


_SCENARIOS: list[tuple[str, Callable[[BoardContext], bool]]] = [
    ("0. happy-path baseline RAM deploy", scenario_happy_path_ram),
    ("1. entrypoint raises (TRACEBACK_RETURNED)", scenario_traceback_returned),
    ("2. unplug USB mid-run (PORT_UNAVAILABLE)", scenario_port_unavailable),
    ("3. eject CIRCUITPY drive (CIRCUITPY_DRIVE_MISSING, CP flash only)",
     scenario_circuitpy_drive_missing),
    ("4. intentional bootloader reset is silent (CP only)",
     scenario_bootloader_reset_silent),
]


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def _load_boards() -> list[BoardContext]:
    try:
        devices, _defaults = load_device_registry()
    except (DeviceConfigError, FileNotFoundError, OSError) as error:
        _print_warn(f"Failed to load devices.yml: {error}")
        return []
    contexts: list[BoardContext] = []
    for device_entry in devices:
        try:
            ram = _build_ram_device(device_entry)
        except ValueError as build_error:
            _print_warn(
                f"Skipping {device_entry.identifier!r}: {build_error}"
            )
            continue
        flash = _build_flash_device(device_entry)
        contexts.append(
            BoardContext(
                entry=device_entry, device_ram=ram, device_flash=flash,
            )
        )
    return contexts


def _pick_boards(boards: list[BoardContext]) -> list[BoardContext]:
    _print_banner("Configured boards")
    for index, context in enumerate(boards, start=1):
        flash_note = (
            " / flash ok" if context.device_flash is not None else ""
        )
        print(f"  {index}. {context.label} [{context.runtime}]{flash_note}")
    print(
        "\nEnter a comma-separated list of numbers (e.g. '1,3') to "
        "run the demo against specific boards, or 'all' for every "
        "listed board.",
    )
    choice = input("Boards: ").strip().lower()
    if choice in ("", "all"):
        return list(boards)
    picked: list[BoardContext] = []
    for raw in choice.split(","):
        token = raw.strip()
        if not token.isdigit():
            _print_warn(f"Ignoring invalid token: {token!r}")
            continue
        index = int(token)
        if 1 <= index <= len(boards):
            picked.append(boards[index - 1])
        else:
            _print_warn(f"Ignoring out-of-range index: {index}")
    return picked


def _pick_scenarios() -> list[tuple[str, Callable[[BoardContext], bool]]]:
    _print_banner("Scenarios")
    for index, (label, _handler) in enumerate(_SCENARIOS, start=1):
        print(f"  {index}. {label}")
    choice = input(
        "\nEnter a comma-separated list (e.g. '1,2'), or 'all': ",
    ).strip().lower()
    if choice in ("", "all"):
        return list(_SCENARIOS)
    picked: list[tuple[str, Callable[[BoardContext], bool]]] = []
    for raw in choice.split(","):
        token = raw.strip()
        if not token.isdigit():
            _print_warn(f"Ignoring invalid token: {token!r}")
            continue
        index = int(token)
        if 1 <= index <= len(_SCENARIOS):
            picked.append(_SCENARIOS[index - 1])
        else:
            _print_warn(f"Ignoring out-of-range index: {index}")
    return picked


def main() -> int:
    _print_banner("chumicro-deploy — recovery hand-holding demo")
    boards = _load_boards()
    if not boards:
        _print_warn(
            "No boards available.  Check devices.yml and ensure at "
            "least one board is reachable."
        )
        return 1
    selected_boards = _pick_boards(boards)
    if not selected_boards:
        _print_warn("No boards selected; aborting.")
        return 1
    selected_scenarios = _pick_scenarios()
    if not selected_scenarios:
        _print_warn("No scenarios selected; aborting.")
        return 1

    # Teardown reminder — some scenarios leave the board in a non-
    # happy state (UF2 bootloader) on purpose.  Remind the user
    # before we start so nothing is a surprise.
    _print_banner("Pre-flight")
    print(
        "Some scenarios deliberately leave the board in a recoverable "
        "but not-quite-happy state (UF2 bootloader, running code, "
        "traceback).  You'll be walked through each one and prompted "
        "to get the board back to normal before the next scenario "
        "starts.",
    )
    if not _confirm("Continue?"):
        return 1

    results: list[tuple[str, str, bool]] = []
    for context in selected_boards:
        _print_banner(f"Board: {context.label}")
        for label, handler in selected_scenarios:
            try:
                ok = handler(context)
            except KeyboardInterrupt:
                print()  # newline after ^C
                _print_warn(f"Interrupted during: {label}")
                results.append((context.label, label, False))
                break
            except Exception as error:  # noqa: BLE001 — demo surface
                _print_warn(
                    f"Scenario '{label}' raised unexpectedly: "
                    f"{type(error).__name__}: {error}"
                )
                results.append((context.label, label, False))
                continue
            results.append((context.label, label, ok))

    _print_banner("Summary")
    for board_label, scenario_label, ok in results:
        marker = "OK " if ok else "FAIL"
        colour = _GREEN if ok else _RED
        print(f"  {colour}{marker}{_RESET}  {board_label}  |  {scenario_label}")
    any_failure = any(not ok for _board, _scenario, ok in results)
    return 1 if any_failure else 0


if __name__ == "__main__":
    sys.exit(main())
