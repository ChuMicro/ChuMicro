"""Interactive demo for :class:`InteractiveDeployer` hand-holding on real boards.

Run this against plugged-in hardware to see the coached failure
output you get from ``chumicro-deploy`` when things go wrong.
Unlike the pytest-based functional tests, this is an *interactive*
script — it prompts you to physically create failure conditions
(unplug USB, eject the CIRCUITPY drive) and then shows you what
the recovery-layer CLI prints in each case.

Run::

    .venv/bin/python workbench/deploy/examples/demo_recovery_hand_holding.py

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

from chumicro_deploy import (
    CircuitpythonTransportError,
    Deployer,
    DeployFailureKind,
    Device,
    DeviceConfigError,
    DeviceEntry,
    FileMapSource,
    InteractiveDeployer,
    MicropythonTransportError,
    classify_deploy_failure,
    load_device_registry,
)

# ---------------------------------------------------------------------------
# Terminal helpers — ANSI color when isatty, plain text otherwise
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
    # Cyan rather than dim — terminal "dim" (\x1b[2m) renders as nearly
    # unreadable dark gray on most dark themes, and these prompts are
    # the user's cue to take a physical action.  Match the cyan accent
    # the scenario headers and confirmation prompts use.
    input(f"{_CYAN}{message}{_RESET}")


def _board_tag(context: BoardContext) -> str:
    """Human-identifiable descriptor for confirmation prompts.

    Includes description, configured id, runtime, and serial address so
    the user can tell which physical board to unplug / eject / reset.
    """
    entry = context.entry
    description = entry.description or entry.identifier
    return (
        f"{_BOLD}{description}{_RESET} "
        f"[{entry.runtime} · id={entry.identifier} · {entry.address}]"
    )


_CP_BLINK_SCRIPT = (
    "import time\n"
    "try:\n"
    "    import board, digitalio\n"
    "    led = digitalio.DigitalInOut(board.LED)\n"
    "    led.direction = digitalio.Direction.OUTPUT\n"
    "    for _ in range(8):\n"
    "        led.value = not led.value\n"
    "        time.sleep(0.15)\n"
    "    led.deinit()\n"
    "    print('blink-ok')\n"
    "except Exception as exc:\n"
    "    print('no-led:', exc)\n"
)

# Pi Pico W MP: Pin("LED"); Lolin S2 MP: GPIO 15; common fallbacks after.
_MP_BLINK_SCRIPT = (
    "import time\n"
    "from machine import Pin\n"
    "led = None\n"
    "for spec in ('LED', 15, 2, 25):\n"
    "    try:\n"
    "        led = Pin(spec, Pin.OUT)\n"
    "        break\n"
    "    except (ValueError, TypeError):\n"
    "        continue\n"
    "if led is None:\n"
    "    print('no-led')\n"
    "else:\n"
    "    for _ in range(8):\n"
    "        led.value(not led.value())\n"
    "        time.sleep(0.15)\n"
    "    print('blink-ok')\n"
)


def _blink_identify(context: BoardContext) -> None:
    """Best-effort onboard-LED blink so the user can spot the target.

    Deploys a short RAM-mode script.  Silent on any failure — the
    descriptive prompt is the primary identification signal; LED blink
    is a bonus for boards that expose a plain onboard LED.
    """
    device = _deploy_device_for(context)
    if device is None:
        return
    script = (
        _CP_BLINK_SCRIPT if context.runtime == "circuitpython" else _MP_BLINK_SCRIPT
    )
    entrypoint = _entrypoint_for(context.runtime)
    source = FileMapSource({entrypoint: script}, entrypoint=entrypoint)
    try:
        Deployer(device).deploy(source)
    except (CircuitpythonTransportError, MicropythonTransportError) as error:
        _print_note(f"LED blink skipped ({error}).")


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
    # CircuitpythonTransport resolves the CIRCUITPY drive at deploy
    # time by scanning mounted CIRCUITPY* volumes and UID-matching the
    # connected board against each boot_out.txt, so we don't pin it on
    # Device.  On MP, flash maps to mpremote copy-mode and never
    # touches the host filesystem at all.
    return Device(
        transport=entry.runtime,
        address=entry.address,
        baudrate=entry.serial_baudrate,
        deploy_mode="flash",
    )


def _entrypoint_for(runtime: str) -> str:
    return "/code.py" if runtime == "circuitpython" else "/main.py"


def _deploy_device_for(context: BoardContext) -> Device | None:
    """Pick the Device config that's actually usable for a deploy.

    RAM mode now works on both runtimes (CP inlines the files into
    ``sys.modules`` via raw REPL; MP mounts the host dir).  Preferring
    RAM across the board keeps the demo fast and avoids depending on
    a mounted CIRCUITPY drive for scenarios that don't need one.
    Flash-specific scenarios use ``context.device_flash`` directly.
    """
    return context.device_ram


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def scenario_happy_path_ram(context: BoardContext) -> bool:
    """Baseline — confirm the board is wired right before inducing failures."""
    _print_step("Scenario: happy-path deploy (baseline)")
    _print_note(
        "Sanity check.  No hand-holding expected.  Deploys a single "
        "print() entrypoint and verifies the output comes back.  If "
        "this fails the board is in a bad state — fix that before "
        "running the failure-path scenarios below."
    )
    device = _deploy_device_for(context)
    if device is None:
        _print_warn(
            "No usable deploy device — CircuitPython boards need a "
            "mounted CIRCUITPY drive on the host for flash-mode "
            "Deployer.deploy.  Mount the board's USB drive and retry."
        )
        return False
    interactive = InteractiveDeployer(
        Deployer(device),
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
    _print_step("Scenario: entrypoint raises (TRACEBACK_RETURNED)")
    _print_note(
        "Deploys an entrypoint that raises a ZeroDivisionError.  The "
        "InteractiveDeployer should NOT retry — source-level bugs "
        "aren't fixable by replugging.  Instead you should see a "
        "'--- traceback ---' block followed by the recovery plan "
        "(fix source, open REPL, etc.)."
    )
    device = _deploy_device_for(context)
    if device is None:
        _print_warn(
            "No usable deploy device for this board — see "
            "the baseline scenario's message above."
        )
        return False
    interactive = InteractiveDeployer(
        Deployer(device),
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
    # Two semantic paths land here:
    #
    # - MP (both modes) and CP flash mode: the board prints the
    #   traceback to stdout after the soft-reboot / exec returns.
    #   Deployer extracts it and returns a DeployResult(success=False,
    #   traceback=...).  InteractiveDeployer prints the
    #   TRACEBACK_RETURNED plan once and returns the result — the
    #   normal "source bug, not a transport failure" path.
    # - CP RAM mode: the raw REPL separates stdout / stderr with \x04
    #   markers, and a stderr-on-chunk gets raised as
    #   CircuitpythonTransportError containing the traceback inline.
    #   InteractiveDeployer classifies that as TRACEBACK_RETURNED
    #   (non-retryable) via the "Traceback (most recent call last)"
    #   substring rule in classify_deploy_failure, prints the same
    #   coaching block, and re-raises.  Either outcome is "correct"
    #   hand-holding for the user.
    try:
        result = interactive.deploy(source)
    except (CircuitpythonTransportError, MicropythonTransportError) as error:
        kind = classify_deploy_failure(error)
        if kind is not DeployFailureKind.TRACEBACK_RETURNED:
            _print_warn(
                f"Unexpected exception classified as {kind.value}: {error}"
            )
            return False
        if "ZeroDivisionError" not in str(error):
            _print_warn(
                f"Exception did not mention ZeroDivisionError: {error}"
            )
            return False
        _print_ok(
            "Traceback coaching rendered; the raised error was "
            "routed to TRACEBACK_RETURNED (non-retryable) — expected "
            "for CP RAM-mode source bugs."
        )
        return True

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
        "expected behavior for source-level bugs."
    )
    return True


def scenario_port_unavailable(context: BoardContext) -> bool:
    """Walk the user through a physical unplug → retry → replug cycle."""
    _print_step("Scenario: serial port unavailable (PORT_UNAVAILABLE)")
    _print_note(
        "This scenario requires you to PHYSICALLY UNPLUG the USB "
        "cable on the target board before the deploy starts.  The "
        "script will attempt to deploy, hit 'Failed to open serial "
        "port', surface the coaching, and prompt you to retry.  "
        "Plug the board back in, wait for it to re-enumerate, then "
        "press Enter at the retry prompt."
    )
    _print_note(
        "Flashing the onboard LED so you can spot the target board "
        "before you unplug it…"
    )
    _blink_identify(context)
    if not _confirm(
        f"Ready to run the unplug scenario on {_board_tag(context)}?",
    ):
        _print_note("Skipped.")
        return True
    print(
        f"{_RED}UNPLUG{_RESET} {_board_tag(context)} now, then press "
        f"Enter to start the deploy.",
    )
    _pause()
    device = _deploy_device_for(context)
    if device is None:
        _print_warn(
            "No usable deploy device — skipping the unplug scenario.",
        )
        return False
    interactive = InteractiveDeployer(
        Deployer(device),
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
    _print_step("Scenario: CIRCUITPY drive missing (CIRCUITPY_DRIVE_MISSING)")
    if context.runtime != "circuitpython":
        _print_note("Skipped — this scenario is CircuitPython-only.")
        return True
    # _load_boards evaluates _build_flash_device once at startup.  If
    # the configured drive path was briefly unavailable then (e.g.
    # the macOS FSKit wedge had CIRCUITPY unmounted, or the board had
    # just been replugged), context.device_flash latched to None for
    # the whole session.  Re-resolve on demand so a drive that has
    # since come back lets the scenario run without restarting the
    # script.  BoardContext is frozen, so keep the resolved value
    # local and thread it through the rest of the function.
    device_flash = context.device_flash
    if device_flash is None:
        device_flash = _build_flash_device(context.entry)
    if device_flash is None:
        _print_warn(
            "Could not build a flash-mode Device for this board — "
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
    _print_note(
        "Flashing the onboard LED so you can spot the target board "
        "before you eject its drive…"
    )
    _blink_identify(context)
    if not _confirm(
        f"Ready to run the eject-drive scenario on {_board_tag(context)}?",
    ):
        _print_note("Skipped.")
        return True
    print(
        f"{_RED}EJECT{_RESET} the CIRCUITPY drive for "
        f"{_board_tag(context)} now, then press "
        f"Enter to start the deploy.",
    )
    _pause()
    interactive = InteractiveDeployer(
        Deployer(device_flash),
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
        "Scenario: intentional bootloader reset emits no warnings",
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
        f"Proceed on {_board_tag(context)}?  "
        f"(Board will enter the UF2 bootloader)",
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


def scenario_flash_copy_failed(context: BoardContext) -> bool:
    """CP flash only — force an oversized payload to trigger rsync failure."""
    _print_step("Scenario: flash copy fails (FLASH_COPY_FAILED)")
    if context.runtime != "circuitpython":
        _print_note("Skipped — this scenario is CircuitPython-only.")
        return True
    # Same latching-guard as scenario_circuitpy_drive_missing: re-
    # resolve on demand so a drive that came back mid-session works.
    device_flash = context.device_flash
    if device_flash is None:
        device_flash = _build_flash_device(context.entry)
    if device_flash is None:
        _print_warn(
            "Could not build a flash-mode Device for this board — "
            "can't run the flash-mode scenario."
        )
        return False
    _print_note(
        "Stages a payload that is guaranteed to exceed a CIRCUITPY "
        "drive's capacity (~2 MiB of junk on a 512 KiB–1 MiB FAT12 "
        "volume).  The rsync inside flash mode should fail with "
        "'No space left on device', the error should classify as "
        "FLASH_COPY_FAILED, and the InteractiveDeployer should print "
        "the free-space / read-only / unplug-replug coaching.  We "
        "deliberately do NOT retry — the fix (free up space) is a "
        "user action outside the scope of this demo."
    )
    if not _confirm(
        f"Ready to force a disk-full failure on {_board_tag(context)}? "
        f"(No files will be written to the board — the deploy is "
        f"rejected at rsync time.)",
    ):
        _print_note("Skipped.")
        return True
    oversized = b"X" * (2 * 1024 * 1024)
    source = FileMapSource(
        {
            "/code.py": b"print('unreachable-oversized')\n",
            "/chu_fill.bin": oversized,
        },
        entrypoint="/code.py",
    )
    # max_attempts=1 — retrying the same oversized payload would hit
    # the same error.  Real recovery is "free space + smaller
    # payload", which isn't a physical retry action.
    interactive = InteractiveDeployer(
        Deployer(device_flash),
        max_attempts=1,
    )
    try:
        result = interactive.deploy(source)
    except CircuitpythonTransportError as error:
        kind = classify_deploy_failure(error)
        if kind is not DeployFailureKind.FLASH_COPY_FAILED:
            _print_warn(
                f"Unexpected exception classified as {kind.value}: {error}"
            )
            return False
        _print_ok(
            "Oversized payload rejected at rsync time and coaching "
            "routed to FLASH_COPY_FAILED — expected behavior."
        )
        return True
    _print_warn(
        f"Deploy unexpectedly succeeded with the 2 MiB payload.  "
        f"Either the drive has more free space than expected or "
        f"the rsync never ran.  Result: {result!r}"
    )
    return False


_SCENARIOS: list[tuple[str, Callable[[BoardContext], bool]]] = [
    ("happy-path baseline deploy", scenario_happy_path_ram),
    ("entrypoint raises (TRACEBACK_RETURNED)", scenario_traceback_returned),
    ("unplug USB mid-run (PORT_UNAVAILABLE)", scenario_port_unavailable),
    ("eject CIRCUITPY drive (CIRCUITPY_DRIVE_MISSING, CP flash only)",
     scenario_circuitpy_drive_missing),
    ("oversized payload (FLASH_COPY_FAILED, CP flash only)",
     scenario_flash_copy_failed),
    ("intentional bootloader reset is silent (CP only)",
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
                _print_note(
                    "The board may be in an unusual state (ejected "
                    "drive, bootloader, stopped mid-deploy).  The next "
                    "scenario assumes a working baseline — continuing "
                    "blindly will probably fail too."
                )
                results.append((context.label, label, False))
                if not _confirm(
                    "Continue with the next scenario on this board?",
                    default_yes=False,
                ):
                    _print_note(
                        f"Skipping remaining scenarios on {context.label}."
                    )
                    break
                continue
            results.append((context.label, label, ok))

    _print_banner("Summary")
    for board_label, scenario_label, ok in results:
        marker = "OK " if ok else "FAIL"
        color = _GREEN if ok else _RED
        print(f"  {color}{marker}{_RESET}  {board_label}  |  {scenario_label}")
    any_failure = any(not ok for _board, _scenario, ok in results)
    return 1 if any_failure else 0


if __name__ == "__main__":
    sys.exit(main())
