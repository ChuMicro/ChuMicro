"""Canned :class:`RecoveryPlan` text for every :class:`DeployFailureKind`.

The user-facing coaching strings live here, apart from the
classifier and recovery-loop machinery.  Edits are text-only;
the one code-shape constraint is the ``retryable`` flag that drives
whether the recovery loop continues or bails.
"""

from __future__ import annotations

from .macos_fskit import MACOS_FSKIT_RECOVERY_COMMAND
from .recovery_kind import DeployFailureKind, RecoveryPlan

PLANS: dict[DeployFailureKind, RecoveryPlan] = {
    DeployFailureKind.PORT_UNAVAILABLE: RecoveryPlan(
        headline="The serial port is unavailable.",
        fix_steps=(
            "Check that the board is plugged into USB.",
            "Close any app that may be holding the port: Mu, Thonny, "
            "screen/minicom, another mpremote, PyCharm or VS Code "
            "serial console.",
            "If the port still does not appear, tap the board's "
            "RESET button and wait 2 to 3 seconds for re-enumeration.",
        ),
        retryable=True,
    ),
    DeployFailureKind.RAW_REPL_UNRESPONSIVE: RecoveryPlan(
        headline="The board's REPL did not respond.",
        fix_steps=(
            "Tap the board's RESET button and wait a second.",
            "If CircuitPython dropped into safe mode, press any key "
            "over a serial terminal to exit safe mode, then retry.",
            "If the board is stuck running user code that ignores "
            "Ctrl-C, hold RESET for 2 seconds or unplug + replug "
            "the USB cable.",
        ),
        retryable=True,
    ),
    DeployFailureKind.COMMAND_TIMED_OUT: RecoveryPlan(
        headline=(
            "The board stopped responding mid-command.  Its USB-CDC "
            "serial link likely wedged."
        ),
        fix_steps=(
            "Physically replug the board: unplug the USB cable and plug "
            "it back in.  A wedged USB-CDC does not clear on its own, so "
            "retrying without this just hangs for the same timeout.",
            "If it stays unresponsive after replugging, run "
            "`chumicro-workspace reset-board --yes --device <id>` to wipe "
            "and re-prep it, or reflash with `install-firmware`.",
        ),
        retryable=False,
    ),
    DeployFailureKind.NO_PYTHON_RUNTIME: RecoveryPlan(
        headline=(
            "The board responds, but it's not running CircuitPython "
            "or MicroPython.  It looks like Arduino, a raw bootloader, "
            "or unknown firmware."
        ),
        fix_steps=(
            "Install firmware before deploying, because chumicro "
            "libraries need a Python runtime on the board.  Pick the runtime "
            "that suits your project: CircuitPython for the broadest "
            "Adafruit-board support, MicroPython for stronger "
            "hardware-acceleration on ESP32 / Pi Pico W.",
            "Register the board first if you haven't "
            "(`chumicro-workspace add-device`), then run:  "
            "chumicro-workspace install-firmware --device <id> "
            "--method <uf2|esptool>  (uf2 for RP2040 / RP2350, esptool "
            "for the ESP32 family).",
            "The firmware URL is derived from the device entry; pass "
            "--url <firmware-url> to flash a specific build instead.  "
            "Heads-up: flashing is destructive, and it overwrites whatever "
            "the board is currently running (your Arduino sketch, "
            "custom firmware, etc.).  Back up first if it matters.",
            "After flashing, the board re-enumerates with the new "
            "runtime; re-run the original command.",
        ),
        retryable=False,
    ),
    DeployFailureKind.CIRCUITPY_DRIVE_MISSING: RecoveryPlan(
        headline="The CIRCUITPY drive is not mounted.",
        fix_steps=(
            "Tap RESET on the board.  This re-exposes the drive "
            "whether it was hidden by flash deploy mode or ejected "
            "manually from Finder.",
            "If the board has no RESET button, unplug + replug it.",
            "If the board isn't running CircuitPython, reflash it "
            "first with `chumicro-deploy flash-firmware --method uf2`.",
        ),
        retryable=True,
    ),
    DeployFailureKind.MACOS_FSKIT_WEDGED: RecoveryPlan(
        headline=(
            "macOS FSKit / DiskArbitration is wedged.  CIRCUITPY drives "
            "cannot mount until the stuck daemons are killed."
        ),
        fix_steps=(
            "Paste this into another terminal (it needs sudo):",
            f"    {MACOS_FSKIT_RECOVERY_COMMAND}",
            "Run it ONLY ONCE per wedge.  A second run on the now-"
            "healthy system kills the daemons mid-operation on the "
            "just-remounted volumes and leaves them in an I/O-error "
            "state that needs physical unplug + replug of the board "
            "to recover (soft-reboot does not, because USB-MSC stays "
            "attached across it).",
            "Each killed daemon respawns under launchd in a clean "
            "state; pending CIRCUITPY drives mount and become "
            "readable.  Press Enter here to retry the deploy.",
            "Heads-up: after the paste your drives will be fully "
            "functional (mounted at /Volumes, readable, writable, "
            "and chumicro-deploy works against them), but on "
            "recent macOS they may NOT appear in Finder's "
            "Locations sidebar.  That's an Apple FSKit-Finder "
            "regression unrelated to this recovery.  Reach them "
            "via Shift+Cmd+C (Computer view) or drag one into "
            "the Favorites sidebar section.",
            "If the wedge persists after the command, reboot.  "
            "That always clears it and also resets the Finder "
            "sidebar classifier.",
            "Full write-up (why each daemon is killed, what the "
            "Finder sidebar regression is, and when to reboot) "
            "lives at "
            "https://github.com/ChuMicro/ChuMicro/blob/main/"
            "docs/troubleshooting/macos-circuitpy.md.",
        ),
        retryable=True,
    ),
    DeployFailureKind.FLASH_COPY_FAILED: RecoveryPlan(
        headline="Copying files to the CIRCUITPY drive failed.",
        fix_steps=(
            "Reformat the CIRCUITPY drive.  The read-only state is "
            "typically a corrupted FAT that persists across RESETs.  "
            "Run `chumicro-workspace reset-board --yes --device "
            "<id>` (or `import storage; storage.erase_filesystem()` "
            "directly via the REPL).  Destructive: every user file "
            "on the board is wiped, including settings.toml.",
            "Check free space on the drive if the payload is larger "
            "than a few KiB.",
            "Optional pre-step before reformatting: tap RESET and "
            "retry once.  Treat this as a longshot, because RESET only "
            "clears transient cases, not the typical FAT corruption "
            "that needs the reformat above.",
        ),
        retryable=True,
    ),
    DeployFailureKind.BOOTSTRAP_EXEC_FAILED: RecoveryPlan(
        headline="The code raised on the board during startup.",
        fix_steps=(
            "Read the traceback or stderr above to spot the error.",
            "If it's a bug in your source, fix it and retry.",
            "If it looks transient (bad frame, serial glitch, "
            "partial mount), tap RESET and retry.",
        ),
        retryable=True,
    ),
    DeployFailureKind.INSUFFICIENT_MEMORY: RecoveryPlan(
        headline=(
            "The board does not have enough free RAM for inline "
            "(RAM-mode) deploy."
        ),
        fix_steps=(
            "Re-run with `--deploy-mode flash` to land the files on "
            "the CIRCUITPY drive instead.  Flash mode is the "
            "built-in escape hatch for payloads that do not fit.",
            "Reduce payload size by trimming unused imports, or "
            "split the deploy across multiple runs.",
        ),
        retryable=False,
    ),
    DeployFailureKind.CONFIGURATION_ERROR: RecoveryPlan(
        headline="The deploy call was misconfigured.",
        fix_steps=(
            "Code-level misuse, not a runtime failure.  Check the "
            "error message above for the exact parameter that's "
            "missing or wrong.  A retry will not change the outcome "
            "until the call-site is fixed.",
        ),
        retryable=False,
    ),
    DeployFailureKind.UNRESOLVED_IMPORT: RecoveryPlan(
        headline=(
            "The deploy was refused: an import in the bundle resolves to "
            "no deployed file and is not a known device built-in."
        ),
        fix_steps=(
            "Read the error above.  It names each importing file and the "
            "module it imports that the walker could not find.",
            "If the module is one of your libraries, register it so the "
            "walker can find it: add its directory to the deploy's search "
            "paths (its package needs to live under one of them).",
            "If it's a typo, fix the import statement.",
            "If the module is a genuine MicroPython / CircuitPython runtime "
            "built-in the walker doesn't yet know about, list it in the "
            "CHUMICRO_DEPLOY_EXTRA_BUILTINS environment variable "
            "(comma-separated top-level names); the durable fix is adding "
            "it to the allowlist upstream.",
            "If the import is a deliberate optional fallback, wrap it in "
            "`try: import foo` / `except ImportError:`.  The walker treats "
            "ImportError-guarded imports as optional and does not refuse "
            "the deploy over them.",
        ),
        retryable=False,
    ),
    DeployFailureKind.TRACEBACK_RETURNED: RecoveryPlan(
        headline="The entrypoint ran but raised a traceback.",
        fix_steps=(
            "Read the traceback above, fix the source, and redeploy.",
            "To poke at the board's state live, open a REPL with "
            "`screen <port> 115200`, `minicom`, `mpremote`, or your "
            "IDE's serial console.",
        ),
        retryable=False,
    ),
    DeployFailureKind.UNKNOWN: RecoveryPlan(
        headline="An unclassified deploy failure occurred.",
        fix_steps=(
            "The full error is above.  As a first cut at recovery, "
            "tap RESET and retry.",
            "If you can reproduce this, please file a report with "
            "the message text and the board involved.",
        ),
        retryable=True,
    ),
}
