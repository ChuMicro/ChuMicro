"""Firmware URL resolution + flashing.

Two surfaces:

- :func:`resolve_firmware_url` — download URL from a board id +
  runtime + version (pure, no network).
- :func:`flash_firmware` — download and apply firmware to a
  connected board.  Destructive: overwrites whatever's currently
  installed.  UF2 path writes to a bootloader drive after entering
  bootloader mode; esptool path shells out to the ``esptool`` CLI
  over serial.

The UF2 path tries programmatic bootloader entry through the
connected transport first, then falls back to an interactive prompt
so users on ESP32 ROM bootloaders (no Python-side bootloader entry
available) can still drive the flow.  Both paths document their
recovery strategies in the exception messages, and every failure mode
leaves the board in a known state or points the user at the fix.
"""

from __future__ import annotations

import dataclasses
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar
from urllib.error import URLError

from .device import Device
from .firmware_url import (
    CIRCUITPYTHON_FIRMWARE_URL_TEMPLATE,
    UnresolvedFirmwareError,
)
from .protocol import ReflashMethod, Runtime

_DEFAULT_LANGUAGE = "en_US"


def resolve_firmware_url(
    board_id: str,
    runtime: str,
    version: str,
    *,
    language: str = _DEFAULT_LANGUAGE,
) -> str:
    """Format the firmware download URL for a known board + version.

    Pure URL formatter.  No network access.  Use this when you have
    an explicit version (e.g. from CI, a release script, or
    user-supplied).  For "give me the latest version available" use
    :func:`firmware_url.derive_firmware_url` or
    :func:`firmware_url.latest_circuitpython_url` instead.

    Args:
        board_id: Board identifier.  CircuitPython boards use the
            Adafruit ID (e.g. ``"raspberry_pi_pico_w"``,
            ``"adafruit_feather_esp32s3_4mbflash_2mbpsram"``).
        runtime: ``"circuitpython"`` or ``"micropython"``.
        version: Firmware version.  For CircuitPython, the Adafruit
            release label (``"10.1.4"`` for stable; ``"10.2.0-rc.0"``
            for pre-release).
        language: Adafruit language code (CircuitPython only).
            Defaults to ``"en_US"``.

    Returns:
        Fully-formed download URL.

    Raises:
        UnresolvedFirmwareError: If *runtime* is not supported, or
            if any required field is empty.  ``cause`` carries the
            specific failure (``"no_board_id"``, ``"no_version"``,
            ``"micropython_needs_listing"``, ``"unsupported_runtime"``).
    """
    if not board_id:
        raise UnresolvedFirmwareError(
            "board_id is required", cause="no_board_id",
        )
    if not version:
        raise UnresolvedFirmwareError(
            "version is required", cause="no_version",
        )
    if runtime == Runtime.CIRCUITPYTHON:
        return CIRCUITPYTHON_FIRMWARE_URL_TEMPLATE.format(
            board_id=board_id, version=version, language=language,
        )
    if runtime == Runtime.MICROPYTHON:
        raise UnresolvedFirmwareError(
            "MicroPython firmware URLs embed a per-build date that "
            "cannot be inferred from the version alone.  Use "
            "chumicro_deploy.firmware_url.derive_firmware_url for the "
            "listing-page lookup, or supply the URL directly.",
            cause="micropython_needs_listing",
        )
    allowed = ", ".join(f"{member.value!r}" for member in Runtime)
    raise UnresolvedFirmwareError(
        f"Unsupported runtime: {runtime!r} (expected {allowed})",
        cause="unsupported_runtime",
    )


# ---------------------------------------------------------------------------
# flash_firmware — download + apply new firmware to a connected board
# ---------------------------------------------------------------------------


#: Where a UF2 bootloader drive typically mounts per platform.
#: Polling every candidate directory for an INFO_UF2.TXT file keeps
#: the check board-agnostic, since we don't need to hard-code
#: per-board drive labels (RPI-RP2, SAMD51, CIRCUITPYUF2, etc.).
_UF2_MOUNT_SEARCH_PATHS: dict[str, list[Path]] = {
    "darwin": [Path("/Volumes")],
    "linux": [
        Path("/media"),
        Path("/run/media"),
    ],
}

#: Seconds between polls of the mount search paths while waiting
#: for a UF2 bootloader drive to appear.
_UF2_POLL_INTERVAL = 0.5

#: Seconds to allow for the UF2 bootloader drive to mount after
#: a programmatic reset.  Budget covers slower hubs and macOS mount
#: quirks.
_UF2_MOUNT_TIMEOUT = 15.0

#: Seconds to allow for the board to re-enumerate after the UF2
#: copy finishes (drive disappears; new firmware boots).
_UF2_REBOOT_TIMEOUT = 30.0

#: Block size for the HTTP download.  Large enough to amortize
#: progress-callback overhead on fast connections, small enough
#: that an 8 MB firmware feels incremental on slow ones.
_DOWNLOAD_CHUNK_SIZE = 64 * 1024


class FlashFirmwareError(Exception):
    """Raised when a flash step fails.

    Message always includes recovery guidance — e.g. "put the board
    in bootloader mode and retry" or "install esptool first".
    Catchers typically surface the message directly to the user
    rather than trying to introspect.
    """


def _infer_reflash_method(url: str) -> str:
    """Pick UF2 or esptool from the URL's file extension.

    Adafruit's CircuitPython S3 bucket and micropython.org both
    name release files with the bootloader-shape extension built
    in: ``.uf2`` for boards that talk to a UF2 mass-storage
    bootloader, ``.bin`` for ESP32-family boards that take esptool
    over USB-CDC.  Lets a resolved URL drive method selection
    without a separate flag.

    Raises:
        ValueError: URL extension isn't ``.uf2`` or ``.bin`` — the
            caller has to pass ``reflash_method`` explicitly.
    """
    lowered = url.split("?", 1)[0].lower()
    if lowered.endswith(".uf2"):
        return ReflashMethod.UF2.value
    if lowered.endswith(".bin"):
        return ReflashMethod.ESPTOOL.value
    raise ValueError(
        f"Cannot infer reflash_method from URL {url!r} — expected "
        f"a .uf2 or .bin extension.  Pass reflash_method explicitly."
    )


def _report(
    on_progress: Callable[[float, str], None] | None,
    fraction: float,
    message: str,
) -> None:
    """Forward a milestone to *on_progress* when supplied."""
    if on_progress is not None:
        on_progress(fraction, message)


def _download_firmware(
    url: str,
    destination: Path,
    *,
    on_progress: Callable[[float, str], None] | None = None,
    urlopen: Callable[..., object] = urllib.request.urlopen,  # injectable
) -> None:
    """Stream *url* to *destination* with coarse progress reporting.

    Args:
        url: Firmware download URL.
        destination: Local path to write.  Parent directories are
            created if missing.
        on_progress: Optional ``(fraction, message)`` callback.  The
            fraction progresses from 0.0 at download-start to 1.0
            when the stream is fully consumed — per-chunk updates
            when ``Content-Length`` is known, coarse start/stop
            otherwise.
        urlopen: Injectable override for the HTTP open call.

    Raises:
        FlashFirmwareError: If the URL is unreachable or the
            destination cannot be written.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    _report(on_progress, 0.0, f"downloading {url}")
    try:
        response = urlopen(url)
    except URLError as error:
        raise FlashFirmwareError(
            f"Failed to download firmware from {url!r}: {error}.  "
            f"Check the URL and your network connection, then retry."
        ) from error

    try:
        total_bytes_header = response.getheader("Content-Length")  # type: ignore[attr-defined]
        total_bytes = int(total_bytes_header) if total_bytes_header else None
        bytes_downloaded = 0
        with destination.open("wb") as output_file:
            while True:
                chunk = response.read(_DOWNLOAD_CHUNK_SIZE)  # type: ignore[attr-defined]
                if not chunk:
                    break
                output_file.write(chunk)
                bytes_downloaded += len(chunk)
                if total_bytes:
                    fraction = bytes_downloaded / total_bytes
                    _report(
                        on_progress, fraction,
                        f"downloading {bytes_downloaded // 1024} / "
                        f"{total_bytes // 1024} KiB",
                    )
    except OSError as error:
        raise FlashFirmwareError(
            f"Failed writing firmware to {destination!r}: {error}"
        ) from error
    finally:
        close_method = getattr(response, "close", None)
        if callable(close_method):
            close_method()
    _report(on_progress, 1.0, "download complete")


_PollResult = TypeVar("_PollResult")


def _poll_until_deadline(
    probe: Callable[[], _PollResult | None],
    *,
    timeout: float,
    interval: float,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
) -> _PollResult | None:
    """Poll *probe* every *interval* seconds until it returns a value.

    Returns the first non-``None`` value *probe* yields, or ``None`` if
    *timeout* seconds elapse first.  *interval* and *timeout* are
    passed in so each wait-for use carries its own hardware-tuned
    budget.
    """
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        result = probe()
        if result is not None:
            return result
        sleep(interval)
    return None


def _uf2_mount_candidates(
    search_paths: list[Path] | None = None,
) -> list[Path]:
    """Return directories where UF2 drives may mount on this platform.

    Defaults are derived from ``sys.platform``; pass *search_paths*
    explicitly to override.  An empty list means no candidates ("the
    platform is unsupported, fall through to an explicit
    ``bootloader_drive_path``").
    """
    if search_paths is not None:
        return list(search_paths)
    return list(_UF2_MOUNT_SEARCH_PATHS.get(sys.platform, []))


def _scan_for_uf2_drive(search_paths: list[Path]) -> Path | None:
    """Return the first child directory containing ``INFO_UF2.TXT``.

    Every UF2 bootloader writes ``INFO_UF2.TXT`` on mount; scanning
    for it is board-agnostic.

    Args:
        search_paths: Parent directories to scan (e.g. ``/Volumes``
            on macOS, ``/media/<user>`` on Linux).
    """
    for search_root in search_paths:
        if not search_root.is_dir():
            continue
        for candidate in search_root.iterdir():
            if not candidate.is_dir():
                continue
            if (candidate / "INFO_UF2.TXT").exists():
                return candidate
    return None


def _wait_for_uf2_drive(
    search_paths: list[Path],
    *,
    timeout: float = _UF2_MOUNT_TIMEOUT,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> Path | None:
    """Poll *search_paths* until a UF2 drive appears or *timeout* expires."""
    return _poll_until_deadline(
        lambda: _scan_for_uf2_drive(search_paths),
        timeout=timeout,
        interval=_UF2_POLL_INTERVAL,
        sleep=sleep,
        monotonic=monotonic,
    )


def _wait_for_drive_gone(
    drive_path: Path,
    *,
    timeout: float = _UF2_REBOOT_TIMEOUT,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> bool:
    """Poll until *drive_path* no longer exists or *timeout* expires.

    A missing UF2 drive after flash indicates the board rebooted
    successfully into the new firmware; returns ``True`` in that
    case.  Timeout returns ``False``, and the caller decides whether
    to surface as an error or just proceed.
    """
    def _probe() -> bool | None:
        if not drive_path.is_dir() or not (drive_path / "INFO_UF2.TXT").exists():
            return True
        return None

    return _poll_until_deadline(
        _probe,
        timeout=timeout,
        interval=_UF2_POLL_INTERVAL,
        sleep=sleep,
        monotonic=monotonic,
    ) is True


def _dispatch_bootloader_reset(device: Device) -> bool:
    """Open *device*'s transport and dispatch its ``reset_into_bootloader``.

    Delegates to :meth:`TransportProtocol.reset_into_bootloader`,
    which knows the right runtime-specific reset script.  Returns
    ``True`` when the command was dispatched; observing actual
    bootloader entry requires a follow-up drive-poll or serial-port-
    snapshot because the board's serial link drops as it resets.
    Returns ``False`` when connect() failed, the runtime does not
    expose a bootloader API, or the dispatch raised.
    """
    try:
        transport = device.create_transport()
        try:
            transport.connect()
        except Exception:  # pragma: no cover — hardware-only connect failures
            return False
        try:
            return transport.reset_into_bootloader()
        finally:
            try:
                transport.disconnect()
            except Exception:  # pragma: no cover — serial may already be gone
                pass
    except Exception:  # pragma: no cover — best-effort hardware path
        return False


def _prompt_manual_bootloader_entry(
    device: Device,
    *,
    prompt: Callable[[str], str] = input,
) -> None:
    """Ask the user to manually put the board in bootloader mode.

    The prompt text is general because the correct physical action
    depends on the board: hold BOOTSEL on a Pi Pico, hold GPIO0 on
    a bare ESP32, double-tap RESET on some Adafruit boards.

    Args:
        device: Target device (used for messaging).
        prompt: Injectable prompt callable; defaults to built-in
            :func:`input`.
    """
    message = (
        f"\n[chumicro-deploy] Could not put {device.address!r} into "
        f"bootloader mode automatically.\n"
        f"[chumicro-deploy] Please put the board into its UF2 "
        f"bootloader manually (e.g. hold BOOTSEL and re-plug) and "
        f"press Enter when the bootloader drive is visible.\n"
        f"[chumicro-deploy] > "
    )
    prompt(message)


def _copy_uf2_to_drive(
    firmware_path: Path,
    drive_path: Path,
    *,
    on_progress: Callable[[float, str], None] | None = None,
) -> None:
    """Copy *firmware_path* onto *drive_path* and flush.

    The UF2 bootloader reads the copied file and writes it to flash
    itself; our job is just to land the bytes on the mount point.
    A file-level flush is emitted before returning so the OS pushes
    the buffer through before we start polling for re-enumeration.

    Args:
        firmware_path: Local .uf2 file downloaded earlier.
        drive_path: Mounted UF2 bootloader drive.
        on_progress: Optional callback.

    Raises:
        FlashFirmwareError: If the copy fails (disk full, drive
            unmounted mid-copy, permission denied).
    """
    _report(on_progress, 0.0, f"copying UF2 to {drive_path}")
    destination = drive_path / firmware_path.name
    try:
        shutil.copy(firmware_path, destination)
    except OSError as error:
        raise FlashFirmwareError(
            f"Copying firmware to {destination!r} failed: {error}.  "
            f"The board is still in bootloader mode — re-run "
            f"flash_firmware() to retry the copy."
        ) from error
    try:
        with destination.open("rb") as handle:
            os.fsync(handle.fileno())
    except OSError:  # pragma: no cover — best-effort flush
        pass
    _report(on_progress, 1.0, "copy complete — waiting for board reboot")


def _flash_firmware_uf2(
    firmware_path: Path,
    device: Device,
    *,
    bootloader_drive_path: Path | None,
    interactive: bool,
    on_progress: Callable[[float, str], None] | None,
    prompt: Callable[[str], str] = input,
    search_paths: list[Path] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Drive the full UF2 reflash flow — bootloader, copy, reboot."""
    _report(on_progress, 0.0, "entering bootloader")
    programmatic_ok = _dispatch_bootloader_reset(device)

    # Locate the UF2 drive: explicit override first, else
    # auto-detect, else interactive prompt, else give up.
    candidate_search_paths = _uf2_mount_candidates(search_paths)
    drive_path: Path | None = bootloader_drive_path
    if drive_path is None:
        drive_path = _wait_for_uf2_drive(
            candidate_search_paths,
            sleep=sleep,
            monotonic=monotonic,
        )

    if drive_path is None or not drive_path.is_dir():
        if not (programmatic_ok and drive_path is not None) and interactive:
            _prompt_manual_bootloader_entry(device, prompt=prompt)
            drive_path = _wait_for_uf2_drive(
                candidate_search_paths,
                sleep=sleep,
                monotonic=monotonic,
            )
        if drive_path is None:
            raise FlashFirmwareError(
                "UF2 bootloader drive did not appear.  Verify the "
                "board is in bootloader mode (a drive with an "
                "INFO_UF2.TXT file should be mounted) and retry, "
                "passing bootloader_drive_path explicitly if "
                "auto-detection does not work on this platform."
            )

    _report(on_progress, 0.5, f"copying firmware to {drive_path}")
    _copy_uf2_to_drive(firmware_path, drive_path, on_progress=on_progress)

    _report(on_progress, 0.9, "waiting for reboot")
    rebooted = _wait_for_drive_gone(
        drive_path, sleep=sleep, monotonic=monotonic,
    )
    if not rebooted:
        raise FlashFirmwareError(
            f"UF2 drive {drive_path!r} did not disappear within "
            f"{_UF2_REBOOT_TIMEOUT:.0f}s.  The flash may still have "
            f"succeeded — check the board's serial output — but the "
            f"reboot signal timed out.  Unplug/replug if the board "
            f"does not come back on its own."
        )
    _report(on_progress, 1.0, "flash complete")


#: Glob pattern for macOS / Linux serial ports that typically host
#: an ESP32 ROM bootloader.  Diffing snapshots of this set detects a
#: bootloader-mode re-enumeration.
_SERIAL_PORT_GLOBS: tuple[str, ...] = (
    "/dev/cu.usbmodem*",
    "/dev/ttyACM*",
    "/dev/ttyUSB*",
)


def _list_candidate_serial_ports(
    globs: tuple[str, ...] = _SERIAL_PORT_GLOBS,
) -> set[str]:
    """Return the set of serial ports currently present on the host."""
    ports: set[str] = set()
    for pattern in globs:
        ports.update(glob.glob(pattern))
    return ports


#: Interval between serial-port presence probes.  Half a second
#: balances responsiveness against the ~1s typical bootloader
#: re-enumeration window on macOS.  Faster polling catches a bounce
#: earlier, but generates more churn while a board is mid-reset.
_SERIAL_PORT_POLL_INTERVAL = 0.5


def _wait_for_new_serial_port(
    baseline: set[str],
    *,
    timeout: float,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    globs: tuple[str, ...] = _SERIAL_PORT_GLOBS,
) -> str | None:
    """Poll for a serial port that was not in *baseline* to appear."""
    def _probe() -> str | None:
        new_ports = _list_candidate_serial_ports(globs) - baseline
        return sorted(new_ports)[0] if new_ports else None

    return _poll_until_deadline(
        _probe,
        timeout=timeout,
        interval=_SERIAL_PORT_POLL_INTERVAL,
        sleep=sleep,
        monotonic=monotonic,
    )


def _prompt_manual_esp32_bootloader(
    device: Device,
    *,
    prompt: Callable[[str], str] = input,
) -> None:
    """Ask the user to manually put an ESP32 board in ROM bootloader.

    For boards where programmatic bootloader entry either isn't
    supported by the runtime (MicroPython on ESP32 boards without a
    working ``machine.bootloader()``) or doesn't produce a bootloader
    port (Lolin S2 Mini where ``machine.bootloader()`` leaves the
    chip half-running).
    """
    message = (
        f"\n[chumicro-deploy] Could not put {device.address!r} into "
        f"ESP32 ROM bootloader automatically.\n"
        f"[chumicro-deploy] Please hold the BOOT (GPIO0) button, "
        f"briefly press RESET, then release BOOT.\n"
        f"[chumicro-deploy] When a new serial port appears "
        f"(typically /dev/cu.usbmodem01 on macOS), press Enter.\n"
        f"[chumicro-deploy] > "
    )
    prompt(message)


def _enter_esp32_rom_bootloader(
    device: Device,
    *,
    interactive: bool,
    prompt: Callable[[str], str] = input,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    globs: tuple[str, ...] = _SERIAL_PORT_GLOBS,
) -> str:
    """Put *device* into ESP32 ROM bootloader and return the new serial port.

    Resolution order:

    1. If *device.address* itself already looks like a bootloader
       port (exists and esptool can reach it later), return it
       unchanged, since that address may already point at a manually-
       entered bootloader.
    2. Otherwise snapshot the current serial ports, dispatch a
       runtime-specific ``reset_into_bootloader`` via the
       transport, and poll for a new port (typically
       ``/dev/cu.usbmodem01`` on macOS).  Whether programmatic
       entry succeeds depends on the board's firmware build, and is
       observable as "a new ROM-bootloader port appears within
       the poll window", not declared per-board.
    3. If no new port appears, and *interactive* is ``True``,
       prompt the user to hold BOOT + press RESET, then poll
       again.  Falls back to a human prompt for any board whose
       firmware can't reach the ROM bootloader programmatically (a
       missing ``machine.bootloader()`` implementation, a board
       without bootstrap-wired RTS/DTR, etc.), so try-and-fall-back
       rather than maintain a per-board table.

    Args:
        device: Target device.
        interactive: When ``True``, fall back to a human prompt
            after the programmatic path fails.  When ``False``,
            raise :class:`FlashFirmwareError` instead.
        prompt: Injectable prompt callable.
        sleep: Injectable sleep for port polling.
        monotonic: Injectable clock for timeouts.
        globs: Serial-port path glob patterns (macOS + Linux
            defaults).

    Returns:
        Absolute path to the serial port now hosting the ROM
        bootloader.

    Raises:
        FlashFirmwareError: If no bootloader port appeared after
            programmatic entry and (for non-interactive flows)
            the user-prompt fallback is disabled, or if the
            user's manual-entry attempt also produces no new port.
    """
    baseline = _list_candidate_serial_ports(globs)

    # When device.address already looks like a bootloader-style port,
    # trust the caller, who put the board in bootloader manually.
    if "cu.usbmodem01" in device.address or device.address.endswith("usbmodem01"):
        return device.address

    # Discard the dispatch result, because the serial-port baseline
    # poll below is the authoritative success signal regardless of
    # what the dispatch reports.
    _dispatch_bootloader_reset(device)

    new_port = _wait_for_new_serial_port(
        baseline, timeout=8.0, sleep=sleep, monotonic=monotonic, globs=globs,
    )
    if new_port is not None:
        return new_port

    if not interactive:
        raise FlashFirmwareError(
            f"This board / firmware does not currently support "
            f"automatically entering bootloader mode "
            f"(no new ROM-bootloader port appeared after the "
            f"programmatic reset on {device.address!r}).\n"
            f"  1. Hold the BOOT button on the board.\n"
            f"  2. While holding BOOT, press and release RESET.\n"
            f"  3. Release BOOT.  A new serial port will appear "
            f"(typically /dev/cu.usbmodem01 on macOS).\n"
            f"  4. Retry with --address pointing at that new port "
            f"(or drop --non-interactive to have this command "
            f"prompt you through the same steps automatically)."
        )

    baseline = _list_candidate_serial_ports(globs)
    _prompt_manual_esp32_bootloader(device, prompt=prompt)
    new_port = _wait_for_new_serial_port(
        baseline, timeout=30.0, sleep=sleep, monotonic=monotonic, globs=globs,
    )
    if new_port is None:
        raise FlashFirmwareError(
            "No new serial port appeared after the manual "
            "bootloader-entry prompt.  Verify the board is "
            "enumerating in ROM bootloader (/dev/cu.usbmodem01 on "
            "macOS) and retry."
        )
    return new_port


def _flash_firmware_esptool(
    firmware_path: Path,
    device: Device,
    *,
    on_progress: Callable[[float, str], None] | None,
    erase_flash: bool = True,
    flash_offset: str = "0x0",
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> None:
    """Shell out to ``esptool`` to write *firmware_path* to *device*.

    esptool manages its own bootloader entry via the USB-CDC RTS/DTR
    dance on boards wired for it (Lolin S2 / Feather S3 / most
    dev kits).  Boards without that wiring require the user to hold
    GPIO0 manually before the command runs.

    Defaults to erasing flash before write-flash, because leftover
    partitions, user data, or half-written sectors from a failed
    previous flash routinely produce confusing "works but boots
    weird" outcomes that aren't worth the upgrade-in-place
    convenience.  Pass ``erase_flash=False`` to keep a CIRCUITPY
    drive or stored wifi credentials across the reflash.  The
    erase runs in its own esptool invocation, because chaining in a
    single command would require staying connected across the
    erase, and some boards re-enter bootloader differently between
    operations.

    Args:
        firmware_path: Local firmware binary.  ESP32 boards expect
            a combined ``.bin`` image at offset ``0x0``.  ``.uf2``
            files on ESP32 boards require TinyUF2 and belong to the
            UF2 reflash path, not this one.
        device: Target device (supplies serial port address).
        on_progress: Optional callback.
        erase_flash: When ``True``, run ``esptool erase-flash``
            before ``write-flash``.  Wipes every user partition
            (CIRCUITPY drive, NVS, stored wifi credentials) —
            irreversible.  Use for recovery / first install, skip
            for ordinary upgrades.
        runner: Injectable subprocess runner.

    Raises:
        FlashFirmwareError: If esptool is not installed, either
            command exits non-zero, or the subprocess fails to
            launch.  Error messages include recovery guidance
            (typically: hold GPIO0 / press BOOT while re-plugging).
    """
    esptool_binary = shutil.which("esptool") or shutil.which("esptool.py")
    if esptool_binary is None:
        raise FlashFirmwareError(
            "esptool not found on PATH.  Install it with "
            "`pip install esptool` (or `pipx install esptool`) and "
            "retry."
        )

    # Erase and write-flash run as two separate esptool calls.  Add
    # `--after no_reset` to the erase step so the chip stays in ROM
    # bootloader for the write step.  esptool's default
    # `--after hard_reset` after erase would leave an empty-flash
    # chip without firmware to boot, and ESP32-S2 does not
    # consistently re-enumerate its ROM bootloader on its own.
    def _invoke(command: list[str], *, step_name: str) -> None:
        try:
            result = runner(
                command, capture_output=True, text=True, check=False,
            )
        except OSError as error:
            raise FlashFirmwareError(
                f"Failed to launch esptool for {step_name}: {error}.  "
                f"Check that {esptool_binary!r} is executable."
            ) from error
        if result.returncode != 0:
            raise FlashFirmwareError(
                f"esptool {step_name} exited {result.returncode}.\n"
                f"  command: {' '.join(command)}\n"
                f"  stderr: {result.stderr.strip()}\n"
                f"Recovery: the board may be in an indeterminate "
                f"state; hold GPIO0 (or press the BOOT button) "
                f"while re-plugging the USB cable, then retry."
            )

    if erase_flash:
        _report(on_progress, 0.0, f"esptool erase-flash via {esptool_binary}")
        _invoke(
            [
                esptool_binary,
                "--port", device.address,
                "--baud", "460800",
                "--after", "no_reset",
                "erase-flash",
            ],
            step_name="erase-flash",
        )
        # Give macOS a moment to release the serial port.  Without
        # this, the next invocation trips "Resource busy" because
        # the kernel still holds the cu.usbmodem FD briefly after
        # esptool returns.
        time.sleep(1.0)

    _report(
        on_progress,
        0.5 if erase_flash else 0.0,
        "esptool write-flash",
    )
    _invoke(
        [
            esptool_binary,
            "--port", device.address,
            "--baud", "460800",
            "write-flash", flash_offset, str(firmware_path),
        ],
        step_name="write-flash",
    )
    _report(on_progress, 1.0, "flash complete")


def flash_firmware(
    url: str,
    device: Device,
    *,
    reflash_method: str | None = None,
    bootloader_drive_path: Path | None = None,
    interactive: bool = True,
    erase_flash: bool = True,
    flash_offset: str = "0x0",
    on_progress: Callable[[float, str], None] | None = None,
) -> None:
    """Download *url* and flash it onto *device*.

    Destructive: overwrites whatever firmware is currently
    installed.  Progress is reported in rough halves: 0.0–0.5
    covers download, 0.5–1.0 covers flash.

    Method selection guide:

    - **``"uf2"``** for RP2040 / RP2350 (Pi Pico family) and any
      board shipping TinyUF2 (some nRF52, SAMD, a handful of ESP32-S2 /
      S3).  Uses the UF2 bootloader drive; requires a ``.uf2`` URL.
      Programmatic bootloader entry works on CircuitPython and on
      MicroPython ports that implement ``machine.bootloader()``.
    - **``"esptool"``** for ESP32 family boards (ESP32, S2, S3, C3,
      C6) regardless of runtime.  Use this whenever the CP
      ``microcontroller.on_next_reset`` drops into the ROM bootloader
      (typical on S2 Mini without TinyUF2) or when installing
      MicroPython on ESP32 hardware.  Requires a ``.bin`` URL, not
      ``.uf2``.  The caller is responsible for
      putting the board in the ROM bootloader (hold GPIO0 / BOOT
      while plugging in).  esptool handles the rest via USB-CDC
      DTR/RTS on boards wired for it, and on bare ESP32 DevKits the
      BOOT button hold is the practical answer.

    Args:
        url: Firmware download URL (typically from
            :func:`resolve_firmware_url`).
        device: Target :class:`Device`.  ``device.address`` is used
            to address the board for both bootloader entry and, in
            the esptool path, the serial flash.  On ESP32 boards
            in ROM bootloader, this is typically
            ``"/dev/cu.usbmodem01"`` (macOS) rather than the
            runtime's normal serial address.
        reflash_method: ``"uf2"`` or ``"esptool"``.  See method
            selection guide above.  When ``None`` (default), the
            method is inferred from the URL extension: ``.uf2`` →
            ``"uf2"``, ``.bin`` → ``"esptool"``.  Pass explicitly
            for ambiguous URLs (e.g. a query-string URL with no
            extension).
        bootloader_drive_path: UF2 path only.  When set, skips
            auto-detection and writes directly to this path.
            Useful when multiple UF2 drives are present or when
            platform detection fails.
        interactive: UF2 path only.  When ``True`` (default) and
            programmatic bootloader entry fails, prompts the user
            to manually put the board in bootloader mode.  Set
            ``False`` in automated flows where stdin isn't
            available — a failure to enter bootloader raises
            :class:`FlashFirmwareError` directly.
        erase_flash: esptool path only.  When ``True`` (default),
            runs ``esptool erase-flash`` before ``write-flash`` —
            wipes every user partition (CIRCUITPY drive, stored
            wifi credentials, NVS) to guarantee a clean slate.
            Pass ``False`` to preserve user data on an in-place
            upgrade.
        flash_offset: esptool path only.  Address to ``write-flash``
            at.  Different firmware sources use different layouts:

              - CircuitPython combined ``.bin`` (Adafruit's
                ``adafruit-circuitpython-<board>-<lang>-<ver>.bin``)
                → ``"0x0"`` (the default).
              - MicroPython ESP32 / S2 / S3 ``.bin`` (separate
                bootloader + partition table + app layout) →
                ``"0x1000"``.

            Using the wrong offset for a MicroPython build writes
            the application image over the bootloader region,
            leaving an unbootable chip that needs a manual BOOT +
            RESET hold and a re-flash.  The flasher cannot
            auto-detect reliably because ``.bin`` files from both
            ecosystems share the extension; callers supply the
            offset explicitly.
        on_progress: Optional ``(fraction, message)`` callback.

    Raises:
        FlashFirmwareError: Download, bootloader entry, drive
            detection, copy, reboot, or esptool invocation failed.
            The message names the step and includes recovery
            guidance.
        ValueError: Unknown *reflash_method*, or
            *reflash_method* is ``None`` and the URL extension is
            neither ``.uf2`` nor ``.bin``.
    """
    if reflash_method is None:
        reflash_method = _infer_reflash_method(url)
    if reflash_method not in ReflashMethod._value2member_map_:
        allowed = ", ".join(f"{member.value!r}" for member in ReflashMethod)
        raise ValueError(
            f"Unsupported reflash_method: {reflash_method!r} "
            f"(expected {allowed})"
        )

    with tempfile.TemporaryDirectory(prefix="chumicro_flash_") as staging:
        staging_path = Path(staging)
        filename = url.rsplit("/", 1)[-1] or "firmware.bin"
        local_firmware = staging_path / filename
        _download_firmware(url, local_firmware, on_progress=on_progress)

        if reflash_method == ReflashMethod.UF2:
            _flash_firmware_uf2(
                local_firmware,
                device,
                bootloader_drive_path=bootloader_drive_path,
                interactive=interactive,
                on_progress=on_progress,
            )
        else:
            _report(on_progress, 0.3, "entering ESP32 ROM bootloader")
            bootloader_port = _enter_esp32_rom_bootloader(
                device, interactive=interactive,
            )
            # Address esptool at the bootloader port rather than the
            # (now-gone) runtime serial port.  The flash completes
            # with a default hard_reset so the board comes back on
            # its usual runtime address, so subsequent operations
            # against the original Device keep working.
            bootloader_device = dataclasses.replace(
                device, address=bootloader_port,
            )
            _flash_firmware_esptool(
                local_firmware,
                bootloader_device,
                erase_flash=erase_flash,
                flash_offset=flash_offset,
                on_progress=on_progress,
            )
