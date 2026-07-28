"""Host-side CIRCUITPY drive discovery, identity, and scope-listing helpers.

Every helper here works on host paths only, with no serial I/O, so they
can be exercised in unit tests against ``tmp_path``-built fixtures
without standing up a fake transport.

Three concerns live here:

- **Mount discovery**: :func:`_circuitpy_base_paths` +
  :func:`_circuitpy_volume_candidates` walk the OS-specific mount
  roots and return every directory that looks like a mounted
  CIRCUITPY drive.
- **Identity probing**: :func:`_read_boot_out_text` +
  :func:`_read_boot_out_identity` parse the ``UID:`` + machine-string
  fields out of a drive's ``boot_out.txt``.  Two finders
  (:func:`find_circuitpy_drive_for_uid`,
  :func:`find_circuitpy_drive_for_machine`) wrap them for the common
  "which mount belongs to this board?" lookup.
- **Scope listing**: :func:`_list_scope_on_drive` walks a mounted
  drive and returns the in-scope file set for diff-deploy.
"""

from __future__ import annotations

import errno
import getpass
import os
from pathlib import Path

from . import flash_drive

_CIRCUITPY_VOLUME_NAME = "CIRCUITPY"


def _format_probe_error(drive_path: Path | str, error: OSError) -> str:
    """Translate a probe-write OSError into a recovery-friendly message.

    Distinguishes three classes of failure on the drive:

    - ``ENOSPC``: drive is full.  Includes the exact errno phrasing
      (``No space left on device``) so the recovery classifier picks
      it up.
    - ``EROFS``: drive remounted read-only (rare on CIRCUITPY but
      possible after a USB hiccup or a board that booted into
      protected mode).
    - Anything else (typically ``EACCES`` from a stale Finder-eject
      mount) is kept as the original "not found or not writable"
      wrapper that documents both candidate causes.
    """
    error_name = error.__class__.__name__
    error_text = str(error) or error_name
    if error.errno == errno.ENOSPC:
        return (
            f"CIRCUITPY drive at {drive_path} is full "
            f"({error_name}: {error_text})"
        )
    if error.errno == errno.EROFS:
        return (
            f"CIRCUITPY drive at {drive_path} is read-only "
            f"({error_name}: {error_text})"
        )
    return (
        f"CIRCUITPY drive not found or not writable: {drive_path} "
        f"({error_name}: {error_text})"
    )


def _resolve_username() -> str:
    """Return the host user name, with a fallback for environments
    that do not export ``$USER``.

    Reads ``$USER`` first (the value Linux desktops use for
    ``/media/<user>/`` mount paths); falls back to
    :func:`getpass.getuser` (which consults ``LOGNAME`` / ``LNAME`` /
    ``USERNAME`` and finally ``pwd.getpwuid(os.getuid())``) when
    ``$USER`` is unset, e.g. inside slim containers.  Returns the
    empty string when even the password database is unavailable so
    the caller can skip building malformed ``/media//CIRCUITPY``
    paths and try the macOS ``/Volumes/`` candidate instead.
    """
    user = os.environ.get("USER", "")
    if user:
        return user
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return ""


def _circuitpy_base_paths() -> list[Path]:
    """Return the OS-specific base directories that CIRCUITPY mounts under.

    macOS uses ``/Volumes``.  Linux uses ``/media/<user>`` and, under
    systemd, ``/run/media/<user>``.  Centralizes the per-OS list so
    volume discovery has one source.
    """
    username = _resolve_username()
    bases = [Path("/Volumes")]
    if username:
        bases.append(Path("/media") / username)
        bases.append(Path("/run/media") / username)
    return bases


def _circuitpy_volume_candidates() -> list[Path]:
    """Return every mounted CIRCUITPY* directory across the base paths.

    macOS assigns ``/Volumes/CIRCUITPY`` by mount order, and additional
    CircuitPython boards get ``/Volumes/CIRCUITPY 1``, ``CIRCUITPY 2``,
    etc.  Globs all of them so the drive-verification path can scan
    every mounted device to find the one whose ``boot_out.txt``
    matches the connected board.  Bare-name match is included.
    """
    found: list[Path] = []
    for base in _circuitpy_base_paths():
        if not base.is_dir():
            continue
        for candidate in sorted(base.glob(f"{_CIRCUITPY_VOLUME_NAME}*")):
            if candidate.is_dir():
                found.append(candidate)
    return found


def _read_boot_out_text(drive_path: Path) -> str | None:
    """Return the full text of ``boot_out.txt`` on *drive_path*, or ``None``.

    Single error-swallowing policy: a missing or unreadable file yields
    ``None`` so callers degrade gracefully.
    """
    boot_out = drive_path / "boot_out.txt"
    if not boot_out.is_file():
        return None
    try:
        return boot_out.read_text(encoding="utf-8", errors="replace")
    except OSError:  # pragma: no cover - hard to mock read_text
        return None


def _read_boot_out_identity(
    drive_path: Path,
) -> tuple[str | None, str | None]:
    """Return ``(uid, machine)`` from ``boot_out.txt`` in one file read.

    CircuitPython writes ``boot_out.txt`` at boot with a header line::

        Adafruit CircuitPython 10.2.0-rc.0 on 2026-04-16; Raspberry Pi Pico W with rp2040

    plus a ``UID:...`` line.  Callers that need both values pay one
    read instead of two on a USB FAT mount.

    Either field is ``None`` when the file is missing, unreadable,
    or doesn't carry that field.
    """
    text = _read_boot_out_text(drive_path)
    if text is None:
        return None, None
    uid: str | None = None
    machine: str | None = None
    lines = text.splitlines()
    if lines:
        first_line = lines[0]
        semicolon_index = first_line.find(";")
        if semicolon_index != -1:
            machine = first_line[semicolon_index + 1:].strip()
    for line in lines:
        if line.startswith("UID:"):
            uid = line[len("UID:"):].strip().upper()
            break
    return uid, machine


def find_circuitpy_drive_for_uid(target_uid: str) -> str | None:
    """Return the mounted CIRCUITPY drive whose UID matches *target_uid*.

    Scans every mounted ``CIRCUITPY*`` volume, reads the ``UID:...``
    line from ``boot_out.txt``, and returns the first path whose UID
    equals *target_uid* (case-insensitive).  Returns ``None`` when no
    mount matches.  Preferred over machine-string matching since UID
    disambiguates two boards of the same model.
    """
    if not target_uid:
        return None
    target = target_uid.upper()
    for candidate in _circuitpy_volume_candidates():
        uid, _machine = _read_boot_out_identity(candidate)
        if uid and uid == target:
            return str(candidate)
    return None


def find_circuitpy_drive_for_machine(target_machine: str) -> str | None:
    """Return the mounted CIRCUITPY drive whose board matches *target_machine*.

    Fallback path when UID-based discovery isn't possible (older
    firmware that doesn't expose the UID probe, or a ``boot_out.txt``
    missing its ``UID:...`` line).  Scans every mounted ``CIRCUITPY*``
    volume, reads ``boot_out.txt``, and returns the first path whose
    board identity equals *target_machine*.  Returns ``None`` when no
    mount matches.  Cannot disambiguate two boards of the same model,
    so prefer :func:`find_circuitpy_drive_for_uid` when the UID is
    known.
    """
    if not target_machine:
        return None
    for candidate in _circuitpy_volume_candidates():
        _uid, machine = _read_boot_out_identity(candidate)
        if machine and machine == target_machine:
            return str(candidate)
    return None


def _list_scope_on_drive(drive: Path, *, clean_slate: bool = False) -> list[str]:
    """Walk a CIRCUITPY drive and return the diff's in-scope paths.

    ``clean_slate=True`` (the deploy default) puts *every* drive file
    in scope except the closed keep set
    (:data:`flash_drive.DEVICE_KEEP_SET`) and macOS-managed noise, so
    the diff reconciles the whole drive and a stale board
    ``settings.toml`` / leftover user file is removed.  All macOS
    noise (``.Spotlight-V100``, ``.fseventsd``, ``._`` AppleDouble,
    ``.metadata_never_index``, …) is dot-prefixed and the chumicro
    payload never is, so "no path part starts with a dot" excludes
    the whole noise class without enumerating it.

    ``clean_slate=False`` is the additive scope (the ``--no-wipe``
    opt-out): only the four entrypoint / state files
    (:data:`~chumicro_deploy.protocol.DEPLOY_SCOPE_FILES`) plus
    ``/lib/**``, so a board ``settings.toml`` and other root files
    are preserved.
    """
    if clean_slate:
        keep = set(flash_drive.DEVICE_KEEP_SET)
        found: list[str] = []
        for path in sorted(drive.rglob("*")):
            relative = path.relative_to(drive)
            if any(part.startswith(".") for part in relative.parts):
                continue
            if path.is_file() and path.name not in keep:
                found.append(f"/{relative.as_posix()}")
        return found

    found = []
    for filename in ("code.py", "main.py", "active.py", "runtime_config.msgpack"):
        if (drive / filename).is_file():
            found.append(f"/{filename}")
    lib_root = drive / "lib"
    if lib_root.is_dir():
        for path in sorted(lib_root.rglob("*")):
            if path.is_file():
                relative_path = path.relative_to(drive).as_posix()
                found.append(f"/{relative_path}")
    return found
