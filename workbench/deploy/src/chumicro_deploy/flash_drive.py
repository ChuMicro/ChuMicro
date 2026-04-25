"""CircuitPython flash-mode USB-drive staging and FAT32 hygiene helpers.

Extracted from :mod:`circuitpython_transport` so the raw-REPL transport
stays focused on serial protocol concerns and the flash-drive staging
lives in one coherent module.

Contents:

- :func:`merge_packages` — copy top-level packages from a ``src/``
  directory into a local staging tree (no device I/O).
- :func:`rsync` — rsync a staging tree onto the CIRCUITPY USB drive,
  excluding files that should persist across tests
  (boot.py, settings.toml, etc.).
- :func:`strip_extended_attributes` — macOS-only: strip xattrs before
  rsync to prevent ``._`` resource fork files from reaching FAT32.
- :func:`clean_dot_files` — macOS-only: ``dot_clean`` to merge or
  remove leftover ``._`` files on the drive after rsync.
- :func:`disable_spotlight_indexing` — macOS-only: turn off Spotlight
  indexing on the volume to prevent index metadata slowing writes.
- :func:`flush_volume` — ``sync`` + settle-delay so FAT32 media is
  consistent before the device reads new content.

All helpers are module-level functions (not methods on a class) because
they operate on filesystem paths or subprocess calls and have no
transport state to carry.  :func:`flush_volume` takes an injected
sleep callable so tests can skip the real settle delay
(Decision 0010 — constructor injection).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys as _sys_module
from collections.abc import Callable
from pathlib import Path

from .host_platform import install_hint_for_rsync


class FlashDriveError(Exception):
    """Raised when a flash-drive staging operation fails."""


#: Seconds to wait after ``sync``/``os.sync()`` so the USB controller
#: finishes writing to FAT32 media.  Without this pause, the device may
#: read stale content even after sync returns.
FLUSH_SETTLE_DELAY = 0.5


def merge_packages(
    source_directory: Path,
    staging_destination: Path,
) -> None:
    """Copy top-level packages from a source directory to a staging dir.

    Merges into the staging destination using ``dirs_exist_ok=True`` so
    multiple source directories can contribute packages.  Operates on
    the local filesystem (not the USB drive), so ``shutil.copytree``
    is reliable here.

    Args:
        source_directory: A ``src/`` directory containing packages.
        staging_destination: Local staging directory to merge into.
    """
    if not source_directory.is_dir():
        return
    for child in sorted(source_directory.iterdir()):
        if not child.is_dir():
            continue
        init_file = child / "__init__.py"
        if not init_file.exists():
            continue
        target = staging_destination / child.name
        shutil.copytree(
            child,
            target,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            dirs_exist_ok=True,
        )


def rsync(source: Path, destination: Path) -> None:
    """Rsync a source directory's contents to a destination.

    Uses ``--checksum`` to verify content (FAT32 timestamps are
    unreliable), ``--inplace`` to write directly into files (avoids
    temp-file rename races on FAT32), and ``--delete`` to remove stale
    files from the destination.

    Device config files and build artifacts that live on the drive but
    are not part of the test deployment are excluded from deletion.

    Args:
        source: Source directory whose contents to sync.
        destination: Destination directory.

    Raises:
        FlashDriveError: If rsync is not installed or the sync fails.
    """
    command = [
        "rsync",
        "--recursive",
        "--checksum",
        "--inplace",
        "--delete",
        "--exclude=__pycache__",
        "--exclude=*.pyc",
        "--exclude=.DS_Store",
        "--exclude=._*",
        "--exclude=boot.py",
        "--exclude=boot_out.txt",
        "--exclude=code.py",
        "--exclude=settings.toml",
        str(source) + "/",
        str(destination) + "/",
    ]
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError as not_found_error:
        raise FlashDriveError(
            "rsync is required for flash deploy mode but was not found.  "
            f"{install_hint_for_rsync()}"
        ) from not_found_error
    except subprocess.CalledProcessError as rsync_error:
        raise FlashDriveError(
            f"rsync failed: {rsync_error.stderr}"
        ) from rsync_error


def strip_extended_attributes(path: Path) -> None:
    """Remove macOS extended attributes from all files under *path*.

    Extended attributes (xattrs) cause slow transfers to FAT32 volumes
    and generate ``._`` resource fork files.  Stripping them from the
    staging directory before rsync prevents these artifacts from
    reaching the device.

    No-op on non-macOS platforms.

    Args:
        path: Root directory to strip recursively.
    """
    if _sys_module.platform != "darwin":
        return  # pragma: no cover — tests run on macOS
    try:
        subprocess.run(
            ["xattr", "-cr", str(path)],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        print("WARNING: xattr not found — skipping extended attribute removal")


def clean_dot_files(drive_path: Path) -> None:
    """Merge or remove ``._`` resource fork files on a FAT32 volume.

    macOS creates ``._`` files on FAT32 drives even when rsync excludes
    them, because the OS itself writes them during filesystem
    operations.  ``dot_clean`` merges these back into the native file
    or removes them if the native file is absent.

    No-op on non-macOS platforms.

    Args:
        drive_path: Mount point of the FAT32 volume.
    """
    if _sys_module.platform != "darwin":
        return  # pragma: no cover — tests run on macOS
    try:
        subprocess.run(
            ["dot_clean", str(drive_path)],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        print("WARNING: dot_clean not found — skipping ._ file cleanup")


def disable_spotlight_indexing(drive_path: Path) -> None:
    """Disable Spotlight indexing on a mounted volume.

    Spotlight indexing creates ``.Spotlight-V100`` metadata and slows
    down FAT32 writes.  ``mdutil -i off`` is idempotent but resets on
    remount, so it is called each time the drive is used.

    May require elevated privileges on some macOS versions; if the
    command fails, indexing continues and no error is raised.

    No-op on non-macOS platforms.

    Args:
        drive_path: Mount point of the volume.
    """
    if _sys_module.platform != "darwin":
        return  # pragma: no cover — tests run on macOS
    try:
        subprocess.run(
            ["mdutil", "-i", "off", str(drive_path)],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        print("WARNING: mdutil not found — skipping Spotlight indexing disable")


def flush_volume(
    drive_path: Path,
    *,
    sleep: Callable[[float], None],
    settle_delay: float = FLUSH_SETTLE_DELAY,
) -> None:
    """Flush pending writes to the volume containing *drive_path*.

    On macOS, calls the ``sync`` command; on other platforms, uses
    ``os.sync()``.  Always waits briefly afterward to let the USB
    controller finish writing to FAT32 media.

    The settle delay goes through the injected *sleep* callable (per
    Decision 0010 — constructor injection) so tests can use a fake
    time source to skip it without sleeping for real.

    Args:
        drive_path: Path on the volume to flush.
        sleep: Callable that sleeps for the given number of seconds.
            Typically ``transport._time.sleep`` from a CircuitpythonTransport.
        settle_delay: Seconds to wait after the sync.
    """
    if _sys_module.platform == "darwin":
        try:
            subprocess.run(["sync"], check=True, capture_output=True)
        except Exception:  # pragma: no cover
            print("WARNING: sync command failed — falling back to os.sync()")
            os.sync()
    else:
        os.sync()  # pragma: no cover — tests run on macOS

    # Allow time for the USB controller to finish writing to the FAT32
    # media.  Without this pause, the device may read stale content
    # even after sync returns.
    sleep(settle_delay)
