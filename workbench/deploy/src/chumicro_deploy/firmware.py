"""Firmware URL resolution + flashing.

Two surfaces:

- :func:`resolve_firmware_url` — canonical download URL from a
  board id + runtime + version (pure, no network).
- :func:`flash_firmware` — download and apply firmware to a
  connected board.  Destructive: overwrites whatever's currently
  installed.  UF2 path writes to a bootloader drive after entering
  bootloader mode; esptool path shells out to the ``esptool`` CLI
  over serial.

The UF2 path tries programmatic bootloader entry through the
connected transport first, then falls back to an interactive prompt
so users on ESP32 ROM bootloaders (no Python-side bootloader entry
available) can still drive the flow.  Both paths document their
recovery strategies in the exception messages — every failure mode
leaves the board in a known state or points the user at the fix.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import URLError

if TYPE_CHECKING:  # pragma: no cover — type-only
    from .device import Device

_DEFAULT_LANGUAGE = "en_US"

#: Adafruit publishes CP firmware at a stable path shape:
#:   ``https://downloads.circuitpython.org/bin/<board_id>/<lang>/\
#:   adafruit-circuitpython-<board_id>-<lang>-<version>.uf2``
#: Version format matches the Adafruit release (e.g. ``10.1.4`` for
#: stable, ``10.2.0-rc.0`` for pre-release).  This is the template
#: the ``resolve_firmware_url`` helper formats.
CIRCUITPYTHON_FIRMWARE_URL_TEMPLATE = (
    "https://downloads.circuitpython.org/bin/{board_id}/{language}/"
    "adafruit-circuitpython-{board_id}-{language}-{version}.uf2"
)


class UnresolvedFirmwareError(Exception):
    """Raised when the firmware URL cannot be built from inputs.

    Typical causes:

    - Runtime is ``"micropython"``.  MP firmware URLs embed a
      per-build date that can't be inferred from the version alone;
      scraping the listing page is on the Slice 1e.2 / 1f roadmap.
    - Runtime is unrecognised (not ``circuitpython`` / ``micropython``).
    - A required field (board_id, version) is empty.
    """


def resolve_firmware_url(
    board_id: str,
    runtime: str,
    version: str,
    *,
    language: str = _DEFAULT_LANGUAGE,
) -> str:
    """Return the canonical firmware download URL.

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
            if any required field is empty.
    """
    if not board_id:
        raise UnresolvedFirmwareError("board_id is required")
    if not version:
        raise UnresolvedFirmwareError("version is required")
    if runtime == "circuitpython":
        return CIRCUITPYTHON_FIRMWARE_URL_TEMPLATE.format(
            board_id=board_id, version=version, language=language,
        )
    if runtime == "micropython":
        raise UnresolvedFirmwareError(
            "MicroPython firmware URLs embed a per-build date that "
            "cannot be inferred from the version alone.  Live listing "
            "lookup is not yet implemented; supply the URL directly "
            "until Slice 1e.2 adds scraping."
        )
    raise UnresolvedFirmwareError(
        f"Unsupported runtime: {runtime!r} "
        f"(expected 'circuitpython' or 'micropython')"
    )


# ---------------------------------------------------------------------------
# flash_firmware — download + apply new firmware to a connected board
# ---------------------------------------------------------------------------


#: Bootloader-mode scripts the transport can exec to put the board
#: into its UF2 bootloader.  CP has a canonical API;
#: MicroPython's ``machine.bootloader()`` works on RP2040/RP2350 but
#: is absent on many ESP32 ports (where esptool is the right path
#: anyway).
_BOOTLOADER_SCRIPTS: dict[str, str] = {
    "circuitpython": (
        "import microcontroller\n"
        "microcontroller.on_next_reset(microcontroller.RunMode.BOOTLOADER)\n"
        "microcontroller.reset()\n"
    ),
    "micropython": (
        "import machine\n"
        "machine.bootloader()\n"
    ),
}

#: Where a UF2 bootloader drive typically mounts per platform.
#: Polling every candidate directory for an INFO_UF2.TXT file keeps
#: the check board-agnostic — we don't need to hard-code per-board
#: drive labels (RPI-RP2, SAMD51, CIRCUITPYUF2, etc.).
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
#: a programmatic reset.  Pi Pico W typically takes ~3 s; larger
#: budget covers slower hubs and macOS mount quirks.
_UF2_MOUNT_TIMEOUT = 15.0

#: Seconds to allow for the board to re-enumerate after the UF2
#: copy finishes (drive disappears; new firmware boots).
_UF2_REBOOT_TIMEOUT = 30.0

#: Block size for the HTTP download — large enough to amortize
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
    urlopen: Callable[..., object] = urllib.request.urlopen,  # injectable for tests
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
        urlopen: Injectable override, used by tests.

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


def _uf2_mount_candidates(
    search_paths: list[Path] | None = None,
) -> list[Path]:
    """Return directories where UF2 drives may mount on this platform.

    Defaults are derived from ``sys.platform``; tests inject
    *search_paths* directly.  An empty list means no candidates —
    callers treat that as "platform unsupported, prompt user to
    pass ``bootloader_drive_path``".
    """
    if search_paths is not None:
        return list(search_paths)
    return list(_UF2_MOUNT_SEARCH_PATHS.get(sys.platform, []))


def _scan_for_uf2_drive(search_paths: list[Path]) -> Path | None:
    """Return the first child directory containing ``INFO_UF2.TXT``.

    INFO_UF2.TXT is the canonical marker the UF2 bootloader writes
    on every mount; scanning for it is board-agnostic.

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
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        found = _scan_for_uf2_drive(search_paths)
        if found is not None:
            return found
        sleep(_UF2_POLL_INTERVAL)
    return None


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
    case.  Timeout returns ``False`` — caller decides whether to
    surface as an error or just proceed.
    """
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if not drive_path.is_dir() or not (drive_path / "INFO_UF2.TXT").exists():
            return True
        sleep(_UF2_POLL_INTERVAL)
    return False


def _enter_uf2_bootloader_programmatic(
    device: Device,
) -> bool:
    """Try to put *device* into UF2 bootloader via the transport.

    Returns ``True`` on success, ``False`` when the runtime doesn't
    support programmatic entry or the board didn't respond.
    Exceptions are caught — this is a best-effort path that is
    expected to fail sometimes (ESP32 ROM bootloader, boards in
    safe mode, disconnected serial).  The caller falls back to an
    interactive prompt.
    """
    script = _BOOTLOADER_SCRIPTS.get(device.transport)
    if script is None:
        return False
    transport = device.create_transport()
    try:
        transport.connect()
        try:
            # Bootloader entry resets the board; the transport
            # usually never gets a clean response.  Swallow all
            # exceptions — the drive-detection poll is the
            # authoritative success signal.
            try:
                transport.execute(script)
            except Exception:  # pragma: no cover — hardware-only failure modes
                pass
        finally:
            try:
                transport.disconnect()
            except Exception:  # pragma: no cover — serial may already be gone
                pass
    except Exception:  # pragma: no cover — connect-level failure
        return False
    return True


def _prompt_manual_bootloader_entry(
    device: Device,
    *,
    prompt: Callable[[str], str] = input,
) -> None:
    """Ask the user to manually put the board in bootloader mode.

    Used when :func:`_enter_uf2_bootloader_programmatic` returns
    ``False`` or when UF2 drive detection fails.  The prompt text
    is general because the correct physical action depends on the
    board: hold BOOTSEL on a Pi Pico, hold GPIO0 on a bare ESP32,
    double-tap RESET on some Adafruit boards.

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
    # Flush host-side buffers before we start polling for re-enum.
    try:
        with destination.open("rb") as handle:
            import os

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
    # Step 1: put the board in bootloader mode.
    _report(on_progress, 0.0, "entering bootloader")
    programmatic_ok = _enter_uf2_bootloader_programmatic(device)

    # Step 2: locate the UF2 drive (explicit override → auto-detect
    # → interactive prompt → give up).
    candidate_search_paths = (
        _uf2_mount_candidates(search_paths)
    )
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

    # Step 3: copy the .uf2 onto the drive.
    _report(on_progress, 0.5, f"copying firmware to {drive_path}")
    _copy_uf2_to_drive(firmware_path, drive_path, on_progress=on_progress)

    # Step 4: wait for the board to reboot into the new firmware.
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


def _flash_firmware_esptool(
    firmware_path: Path,
    device: Device,
    *,
    on_progress: Callable[[float, str], None] | None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> None:
    """Shell out to ``esptool`` to write *firmware_path* to *device*.

    esptool manages its own bootloader entry via the USB-CDC RTS/DTR
    dance on boards wired for it (Lolin S2 / Feather S3 / most
    dev kits).  Boards without that wiring need the user to hold
    GPIO0 manually before the command runs; the caller is
    responsible for prompting in that case.

    Args:
        firmware_path: Local firmware binary (typically .bin; some
            MicroPython releases ship .uf2 that's really just a
            raw-binary wrapper esptool does not understand — a .bin
            is always safer).
        device: Target device (supplies serial port address).
        on_progress: Optional callback.
        runner: Injectable subprocess runner for tests.

    Raises:
        FlashFirmwareError: If esptool is not installed, exits
            non-zero, or the subprocess fails to launch.
    """
    esptool_binary = shutil.which("esptool") or shutil.which("esptool.py")
    if esptool_binary is None:
        raise FlashFirmwareError(
            "esptool not found on PATH.  Install it with "
            "`pip install esptool` (or `pipx install esptool`) and "
            "retry."
        )

    _report(on_progress, 0.0, f"flashing via esptool: {esptool_binary}")
    command = [
        esptool_binary,
        "--port", device.address,
        "--baud", "460800",
        "write_flash", "0x0", str(firmware_path),
    ]
    try:
        result = runner(
            command, capture_output=True, text=True, check=False,
        )
    except OSError as error:
        raise FlashFirmwareError(
            f"Failed to launch esptool: {error}.  "
            f"Check that {esptool_binary!r} is executable."
        ) from error

    if result.returncode != 0:
        raise FlashFirmwareError(
            f"esptool exited {result.returncode}.\n"
            f"  command: {' '.join(command)}\n"
            f"  stderr: {result.stderr.strip()}\n"
            f"Recovery: the board may be in an indeterminate state; "
            f"hold GPIO0 (or press the BOOT button) while plugging "
            f"in, then retry."
        )
    _report(on_progress, 1.0, "flash complete")


def flash_firmware(
    url: str,
    device: Device,
    *,
    reflash_method: str,
    bootloader_drive_path: Path | None = None,
    interactive: bool = True,
    on_progress: Callable[[float, str], None] | None = None,
) -> None:
    """Download *url* and flash it onto *device*.

    Destructive — overwrites whatever firmware is currently
    installed.  Progress is reported in rough halves: 0.0–0.5
    covers download, 0.5–1.0 covers flash.

    Args:
        url: Firmware download URL (typically from
            :func:`resolve_firmware_url`).
        device: Target :class:`Device`.  ``device.address`` is used
            to address the board for both bootloader entry and, in
            the esptool path, the serial flash.
        reflash_method: ``"uf2"`` for UF2-bootloader boards (RP2040,
            RP2350, SAMD family, nRF52, ESP32-S2/S3 with TinyUF2).
            ``"esptool"`` for ESP32 family boards booting the ROM
            bootloader (typically MicroPython ESP32 images).
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
        on_progress: Optional ``(fraction, message)`` callback.

    Raises:
        FlashFirmwareError: Download, bootloader entry, drive
            detection, copy, reboot, or esptool invocation failed.
            The message names the step and includes recovery
            guidance.
        ValueError: Unknown *reflash_method*.
    """
    if reflash_method not in ("uf2", "esptool"):
        raise ValueError(
            f"Unsupported reflash_method: {reflash_method!r} "
            f"(expected 'uf2' or 'esptool')"
        )

    import tempfile

    with tempfile.TemporaryDirectory(prefix="chumicro_flash_") as staging:
        staging_path = Path(staging)
        filename = url.rsplit("/", 1)[-1] or "firmware.bin"
        local_firmware = staging_path / filename
        _download_firmware(url, local_firmware, on_progress=on_progress)

        if reflash_method == "uf2":
            _flash_firmware_uf2(
                local_firmware,
                device,
                bootloader_drive_path=bootloader_drive_path,
                interactive=interactive,
                on_progress=on_progress,
            )
        else:
            _flash_firmware_esptool(
                local_firmware, device, on_progress=on_progress,
            )
