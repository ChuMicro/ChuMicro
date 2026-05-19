"""Host-side CIRCUITPY drive discovery, identity, and scope-listing helpers.

Extracted from :mod:`circuitpython_transport` so the raw-REPL transport
stays focused on serial-protocol concerns and the FAT-volume probing
lives in one coherent module.  Every helper here works on host paths
only — no serial I/O — so they can be exercised in unit tests against
``tmp_path``-built fixtures without standing up a fake transport.

Three concerns live here:

- **Mount discovery** — :func:`_circuitpy_base_paths` +
  :func:`_circuitpy_volume_candidates` walk the OS-specific mount
  roots and return every directory that looks like a mounted
  CIRCUITPY drive.
- **Identity probing** — :func:`_read_boot_out_text` +
  :func:`_read_boot_out_identity` parse the ``UID:`` + machine-string
  fields out of a drive's ``boot_out.txt``.  Two finders
  (:func:`find_circuitpy_drive_for_uid`,
  :func:`find_circuitpy_drive_for_machine`) wrap them for the common
  "which mount belongs to this board?" lookup.
- **Scope listing** — :func:`_list_scope_on_drive` walks a mounted
  drive and returns the in-scope file set for diff-deploy.

:func:`_format_probe_error` and :func:`_resolve_username` are
ancillary host-side helpers consumed by the drive-resolution path
in the transport.
"""

from __future__ import annotations

import errno
import getpass
import os
from pathlib import Path

from . import flash_drive

#: Volume name CircuitPython uses by default.
_CIRCUITPY_VOLUME_NAME = "CIRCUITPY"


def _format_probe_error(drive_path: Path | str, error: OSError) -> str:
    """Translate a probe-write OSError into a recovery-friendly message.

    The transport's ``.chu-probe`` write distinguishes three classes of
    failure on the drive:

    - ``ENOSPC`` — drive is full.  Includes the exact errno phrasing
      (``No space left on device``) so the recovery classifier's
      :data:`~chumicro_deploy.recovery._FLASH_DRIVE_STATE_PATTERNS`
      check picks it up.
    - ``EROFS`` — drive remounted read-only (rare on CIRCUITPY but
      possible after a USB hiccup or a board that booted into
      protected mode).
    - Anything else (typically ``EACCES`` from a stale Finder-eject
      mount) — kept as the original "not found or not writable"
      wrapper that documents both candidate causes.

    The first two are *drive-found* states, so the message no longer
    leads with "not found" — that was misleading when, e.g., the user
    was running a disk-full demo and saw the drive in Finder while
    chumicro-deploy claimed it wasn't there.
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

    macOS: ``/Volumes``.  Linux: ``/media/<user>``.  Linux (systemd):
    ``/run/media/<user>``.  Used by :func:`_circuitpy_volume_candidates`
    so the discovery list lives in one place.
    """
    username = _resolve_username()
    bases = [Path("/Volumes")]
    if username:
        bases.append(Path("/media") / username)
        bases.append(Path("/run/media") / username)
    return bases


def _circuitpy_volume_candidates() -> list[Path]:
    """Return every mounted CIRCUITPY* directory across the base paths.

    macOS assigns ``/Volumes/CIRCUITPY`` by mount order; additional
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

    Centralized so the identity reader has one error-swallowing policy.
    A missing or unreadable file yields ``None`` and the caller
    degrades gracefully.
    """
    boot_out = drive_path / "boot_out.txt"
    if not boot_out.is_file():
        return None
    try:
        return boot_out.read_text(encoding="utf-8", errors="replace")
    except OSError:  # pragma: no cover — hard to mock read_text
        return None


def _read_boot_out_identity(
    drive_path: Path,
) -> tuple[str | None, str | None]:
    """Return ``(uid, machine)`` from ``boot_out.txt`` in one file read.

    CircuitPython writes ``boot_out.txt`` at boot with a header line::

        Adafruit CircuitPython 10.2.0-rc.0 on 2026-04-16; Raspberry Pi Pico W with rp2040

    plus a ``UID:...`` line.  Both fields are needed by the
    transport's drive-verification path on every deploy and by the
    per-candidate identity sweep in
    :func:`find_circuitpy_drive_for_uid` /
    :func:`find_circuitpy_drive_for_machine`; reading once and
    extracting both avoids redundant I/O on a USB FAT mount.

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
    mount matches.  This is the preferred discovery path —
    transport-side identity verification only falls back to
    :func:`find_circuitpy_drive_for_machine` when the UID probe is
    unavailable on either side of the comparison.
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
    mount matches.  Cannot disambiguate two boards of the same model
    — prefer :func:`find_circuitpy_drive_for_uid` when the UID is
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

    Flash-mode helper for the transport's ``list_files_in_scope``.

    ``clean_slate=True`` (the deploy default) puts *every* drive file
    in scope except the closed keep set
    (:data:`flash_drive.DEVICE_KEEP_SET`) and macOS-managed noise — so
    the diff reconciles the whole drive and a stale board
    ``settings.toml`` / leftover user file is removed.  All macOS
    noise (``.Spotlight-V100``, ``.fseventsd``, ``._`` AppleDouble,
    ``.metadata_never_index``, …) is dot-prefixed and the chumicro
    payload never is, so "no path part starts with a dot" excludes
    the whole noise class without enumerating it.

    ``clean_slate=False`` is the legacy additive scope (the
    ``--no-wipe`` opt-out): only the four canonical state files plus
    ``/lib/**``, so a board ``settings.toml`` and other root files
    are preserved.
    """
    if clean_slate:
        keep = set(flash_drive.DEVICE_KEEP_SET)
        found: list[str] = []
        for path in sorted(drive.rglob("*")):
            relative = path.relative_to(drive)
            if any(part.startswith(".") for part in relative.parts):
                continue  # macOS noise / sentinels are all dot-prefixed
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
