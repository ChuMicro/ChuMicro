"""Firmware URL resolution + flashing.

Two surfaces: :func:`resolve_firmware_url` (pure URL formatter) and
:func:`flash_firmware` (download + apply, destructive).  See
:func:`flash_firmware`'s docstring for the UF2-vs-esptool method
selection and per-path recovery strategies.
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
            specific failure; see :class:`UnresolvedFirmwareError`.
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
# flash_firmware: download + apply new firmware to a connected board
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

    Message always includes recovery guidance, e.g. "put the board
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
        ValueError: URL extension isn't ``.uf2`` or ``.bin``, so the
            caller has to pass ``reflash_method`` explicitly.
    """
    lowered = url.split("?", 1)[0].lower()
    if lowered.endswith(".uf2"):
        return ReflashMethod.UF2.value
    if lowered.endswith(".bin"):
        return ReflashMethod.ESPTOOL.value
    raise ValueError(
        f"Cannot infer reflash_method from URL {url!r}: expected "
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
            when the stream is fully consumed, with per-chunk updates
            when ``Content-Length`` is known and coarse start/stop
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
        # file:// URLs return a response object without `getheader`; in
        # that case we skip the size-known progress branch.
        total_bytes_header = (
            response.getheader("Content-Length")  # type: ignore[attr-defined]
            if hasattr(response, "getheader") else None
        )
        try:
            total_bytes = int(total_bytes_header) if total_bytes_header else None
        except ValueError:
            # A malformed Content-Length only costs the progress percent,
            # not the download (streamed in chunks), so fall back to
            # unknown size.
            total_bytes = None
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
    *timeout* seconds elapse first.  Each caller passes its own
    *interval* and *timeout* because bootloader polling and drive-gone
    polling have different hardware-tuned budgets.
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
        except Exception:  # pragma: no cover -hardware-only connect failures
            return False
        try:
            return transport.reset_into_bootloader()
        finally:
            try:
                transport.disconnect()
            except Exception:  # pragma: no cover -serial may already be gone
                pass
    except Exception:  # pragma: no cover -best-effort hardware path
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
    Then fsync the file so the OS pushes the buffer to the drive
    before we start polling for re-enumeration.

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
            f"The board is still in bootloader mode, so re-run "
            f"flash_firmware() to retry the copy."
        ) from error
    try:
        with destination.open("rb") as handle:
            os.fsync(handle.fileno())
    except OSError:  # pragma: no cover -best-effort flush
        pass
    _report(on_progress, 1.0, "copy complete, waiting for board reboot")


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
    """Drive the full UF2 reflash flow: bootloader, copy, reboot."""
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
            f"succeeded (check the board's serial output), but the "
            f"reboot signal timed out.  Unplug/replug if the board "
            f"does not come back on its own."
        )
    _report(on_progress, 1.0, "flash complete")


#: Glob pattern for macOS / Linux serial ports that typically host
#: an ESP32 ROM bootloader.  Comparing the set before and after a
#: reset catches a board entering bootloader mode (a new port appears,
#: an old one disappears, or both).
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

    Tries three steps in order until one returns a bootloader port:

    1. If *device.address* already looks like a ROM-bootloader port
       (``cu.usbmodem01``), return it unchanged.
    2. Snapshot existing serial ports, dispatch a runtime-specific
       ``reset_into_bootloader`` via the transport, and poll up to 8s
       for a new port to appear.
    3. When step 2 produces no new port and *interactive* is ``True``,
       prompt the user to hold BOOT and press RESET, then poll for
       30s.  This is the fallback for boards whose firmware cannot
       reach the ROM bootloader programmatically.

    Args:
        device: Target device.
        interactive: When ``False``, raise :class:`FlashFirmwareError`
            after step 2 fails instead of prompting.
        prompt: Injectable prompt callable.
        sleep: Injectable sleep for port polling.
        monotonic: Injectable clock for timeouts.
        globs: Serial-port path glob patterns (macOS + Linux defaults).

    Returns:
        Absolute path to the serial port now hosting the ROM bootloader.

    Raises:
        FlashFirmwareError: When no bootloader port appears and either
            *interactive* is ``False`` or the manual fallback also
            produces no new port.
    """
    baseline = _list_candidate_serial_ports(globs)

    # When device.address already looks like a bootloader-style port,
    # trust the caller, who put the board in bootloader manually.
    if "cu.usbmodem01" in device.address or device.address.endswith("usbmodem01"):
        return device.address

    # When the runtime CDC is gone and a usbmodem01-style port is
    # already present, the user put the board in bootloader before
    # invoking us.  Return that port without trying to dispatch a
    # reset through the now-vanished runtime port.
    if device.address not in baseline:
        for port in baseline:
            if "cu.usbmodem01" in port or port.endswith("usbmodem01"):
                return port

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
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Shell out to ``esptool`` to write *firmware_path* to *device*.

    Runs as two separate esptool invocations: an optional
    ``erase-flash`` followed by ``write-flash``.  The erase step uses
    ``--after no-reset`` so the chip stays in ROM bootloader for the
    write that follows.  Erase defaults to on because leftover
    partitions or half-written sectors from a failed previous flash
    routinely produce "boots weird" outcomes.

    Args:
        firmware_path: Local firmware binary.  ESP32 boards expect a
            combined ``.bin`` image at ``flash_offset`` (default
            ``0x0``).
        device: Target device, supplies the serial port address.
        on_progress: Optional progress callback.
        erase_flash: When ``True`` (the default), wipe every user
            partition (CIRCUITPY drive, NVS, stored wifi credentials)
            before writing.  Set ``False`` to preserve those across
            a reflash.
        flash_offset: Write offset for the firmware image.
        runner: Injectable subprocess runner.
        sleep: Injectable sleep for the inter-invocation settle delay
            (default ``time.sleep``).  Tests pass a no-op to skip the
            real wait.

    Raises:
        FlashFirmwareError: When esptool is missing, the subprocess
            fails to launch, or either command exits non-zero.  Error
            messages carry recovery guidance (hold GPIO0 / press BOOT
            while re-plugging).
    """
    # This function speaks esptool v5: the subcommands below use the
    # hyphenated v5 names (``erase-flash``, ``write-flash``), which v4
    # rejects with "invalid choice".  Prefer the bare ``esptool``
    # name, which only v5 installs.  v5 also ships an ``esptool.py``
    # deprecation shim, so the fallback still lands on v5 for a host
    # whose PATH carries only the old name.
    # ``CHUMICRO_ESPTOOL_BINARY`` pins one binary when a host has
    # several (an IDF environment alongside the workspace venv).
    esptool_binary = (
        os.environ.get("CHUMICRO_ESPTOOL_BINARY")
        or shutil.which("esptool")
        or shutil.which("esptool.py")
    )
    if esptool_binary is None:
        raise FlashFirmwareError(
            "esptool not found on PATH.  It ships as a dependency of "
            "chumicro-deploy, so a missing binary usually means a "
            "half-built environment: reinstall chumicro-deploy, or "
            "install it directly with `pip install 'esptool>=5.2'`."
        )

    # Erase and write-flash run as two separate esptool calls.  Add
    # `--after no-reset` to the erase step so the chip stays in ROM
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

    # ``--before no-reset`` tells esptool the chip is already in ROM
    # bootloader and to skip the DTR/RTS reset dance on port open.  On
    # ESP32-S2 boards with native USB-OTG, the default DTR/RTS pulses
    # can knock an already-in-bootloader chip back out of bootloader
    # before esptool finishes its sync.
    if erase_flash:
        _report(on_progress, 0.0, f"esptool erase-flash via {esptool_binary}")
        _invoke(
            [
                esptool_binary,
                "--port", device.address,
                "--baud", "460800",
                "--before", "no-reset",
                "--after", "no-reset",
                "erase-flash",
            ],
            step_name="erase-flash",
        )
        # Give macOS a moment to release the serial port.  Without
        # this, the next invocation trips "Resource busy" because
        # the kernel still holds the cu.usbmodem FD briefly after
        # esptool returns.
        sleep(1.0)

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
            "--before", "no-reset",
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

    Destructive: overwrites whatever firmware is currently installed.
    Progress is reported in rough halves, 0.0 to 0.5 covers download
    and 0.5 to 1.0 covers flash.

    Method selection:

    - **``"uf2"``** for RP2040 / RP2350 (Pi Pico family) and any
      board shipping TinyUF2.  Requires a ``.uf2`` URL and writes
      through the UF2 bootloader drive.  Programmatic bootloader
      entry works on CircuitPython and on MicroPython ports that
      implement ``machine.bootloader()``.
    - **``"esptool"``** for ESP32 family boards (ESP32, S2, S3, C3,
      C6) regardless of runtime.  Requires a ``.bin`` URL.  The
      caller puts the board in ROM bootloader (the helper handles
      programmatic entry on boards wired for USB-CDC DTR/RTS, and
      prompts for a manual BOOT-hold otherwise).

    When *reflash_method* is ``None``, the method is inferred from
    the URL extension (``.uf2`` to UF2, ``.bin`` to esptool).

    Args:
        url: Firmware download URL, typically from
            :func:`resolve_firmware_url`.
        device: Target :class:`Device`.  ``device.address`` addresses
            the board for both bootloader entry and, on the esptool
            path, the serial flash.
        reflash_method: ``"uf2"``, ``"esptool"``, or ``None`` to infer
            from the URL extension.
        bootloader_drive_path: UF2 path only.  Skips auto-detection
            and writes directly to this path.
        interactive: UF2 / esptool path.  When ``True`` (the default)
            and programmatic bootloader entry fails, prompts the user
            to enter bootloader manually.  Set ``False`` to raise
            :class:`FlashFirmwareError` instead.
        erase_flash: esptool path only.  When ``True`` (the default),
            wipes user partitions (CIRCUITPY drive, NVS, stored wifi
            credentials) before writing.  Set ``False`` to preserve
            them across an in-place upgrade.
        flash_offset: esptool path only.  Defaults to ``"0x0"`` for
            CircuitPython's combined image.  Use ``"0x1000"`` for
            MicroPython ESP32 / S2 / S3 builds (which ship separate
            bootloader, partition table, and app sections).  Wrong
            offset writes the app image over the bootloader region
            and leaves an unbootable chip until a manual reflash.
        on_progress: Optional ``(fraction, message)`` callback.

    Raises:
        FlashFirmwareError: Download, bootloader entry, drive
            detection, copy, reboot, or esptool invocation failed.
            The message names the step and carries recovery guidance.
        ValueError: Unknown *reflash_method*, or *reflash_method* is
            ``None`` and the URL extension is neither ``.uf2`` nor
            ``.bin``.
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
        filename = Path(url.rsplit("/", 1)[-1]).name or "firmware.bin"
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
