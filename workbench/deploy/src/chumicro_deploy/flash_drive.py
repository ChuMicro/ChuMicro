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


#: Excludes every CP rsync uses regardless of caller — build artifacts,
#: macOS file-level detritus, and the macOS volume-level noise dirs +
#: skip-sentinels :func:`neuter_macos_metadata` plants.  See the
#: docstring on each block in :func:`rsync` for the rationale.
_BASE_RSYNC_EXCLUDES: tuple[str, ...] = (
    "__pycache__",
    "*.pyc",
    ".DS_Store",
    "._*",
    # macOS noise dirs (auto-created, kernel-locked).
    ".Trashes",
    ".Spotlight-V100",
    ".TemporaryItems",
    ".DocumentRevisions-V100",
    # macOS skip sentinels we plant; rsync --delete must not remove them.
    ".fseventsd",
    ".metadata_never_index",
)


def rsync(
    source: Path,
    destination: Path,
    *,
    delete: bool = True,
    additional_excludes: tuple[str, ...] | list[str] = (),
) -> None:
    """Rsync a source directory's contents to a destination.

    Single primitive both the production deploy path
    (:meth:`CircuitpythonTransport.deploy_files`) and the functional-
    test stage path (:meth:`CircuitpythonTransport.stage`) use.  Both
    callers want the same FAT-write reliability (``--checksum`` to
    verify content because FAT32 timestamps are unreliable,
    ``--inplace`` to avoid temp-file rename races on FAT32) — they
    differ only on the *delete-semantic* and the *exclude list*:

    * **Functional tests** call ``delete=True`` with
      ``additional_excludes=("boot.py", "boot_out.txt", "code.py",
      "settings.toml")`` — clean slate between test files, but
      preserve the user-config files the firmware needs.
    * **Production deploys** call ``delete=False`` with no extra
      excludes — preserve user files (``settings.toml``, custom
      modules in ``/lib/`` not currently in the import graph) and
      let the deploy's file map drive what gets written.  The
      ``chumicro-workspace deploy --wipe`` flag covers the
      destructive case.

    The base exclude set (build artifacts + macOS noise / sentinel
    dirs) is shared and unconditional — see :data:`_BASE_RSYNC_EXCLUDES`.

    Args:
        source: Source directory whose contents to sync.
        destination: Destination directory.
        delete: When ``True``, pass ``--delete`` so files in
            destination but not source are removed.  ``False`` is the
            production-deploy default — stale files persist, which
            preserves user data (``settings.toml`` etc.) that's not
            part of the deploy's file map.
        additional_excludes: Extra basenames to add to ``--exclude``.
            Functional-test callers pass user-config filenames so
            ``--delete`` doesn't wipe them.  Production callers leave
            empty.

    Raises:
        FlashDriveError: If rsync is not installed or the sync fails.
    """
    command = [
        "rsync",
        "--recursive",
        "--checksum",
        "--inplace",
    ]
    if delete:
        command.append("--delete")
    for pattern in _BASE_RSYNC_EXCLUDES:
        command.append(f"--exclude={pattern}")
    for pattern in additional_excludes:
        command.append(f"--exclude={pattern}")
    command.append(str(source) + "/")
    command.append(str(destination) + "/")
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


#: Filenames the functional-test stage path adds to ``--exclude`` so
#: ``--delete`` doesn't wipe firmware-required user-config files.
#: Production deploys don't add these — when a deploy's file map
#: contains ``code.py`` (the entrypoint) we want it written, not
#: skipped.
FUNCTIONAL_TEST_EXTRA_EXCLUDES: tuple[str, ...] = (
    "boot.py",
    "boot_out.txt",
    "code.py",
    "settings.toml",
)


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


#: Sentinel files / directories macOS recognises to skip a volume.  Planted
#: at the drive root so subsequent remounts inherit the suppression — the
#: equivalent of ``mdutil -i off`` (which resets on remount) but persistent.
#:
#: ``.Trashes`` is the load-bearing one: macOS preemptively creates
#: ``.Trashes/<UID>/`` on every FAT mount, then sets the inner UID dir
#: read-only at the kernel level so even the mounting user can't
#: ``unlinkat`` it (verified live: ``rsync --delete`` aborts with
#: ``Operation not permitted``).  Planting ``.Trashes`` as a *file*
#: blocks macOS from creating the directory in the first place — the
#: kernel can't ``mkdir`` over an existing non-directory entry.
#: Already-contaminated drives keep their protected dir; the rsync
#: exclude in :func:`rsync` handles those.
_MACOS_SKIP_SENTINELS = (
    ".metadata_never_index",  # Spotlight: skip indexing this volume.
    ".fseventsd/no_log",      # FSEvents daemon: skip logging this volume.
    ".Trashes",               # Trash daemon: file-shaped sentinel blocks dir creation.
)

#: Metadata directories macOS auto-creates on FAT volumes.  Removed defensively
#: at deploy time — they re-appear if macOS still wants them, but the sentinel
#: files above usually persuade it not to.
#:
#: ``.Trashes`` is intentionally absent from this list now that the
#: sentinel above blocks it from being created.  If a drive was
#: already contaminated before the sentinel landed, the rsync
#: ``--exclude=.Trashes`` line in :func:`rsync` lets the deploy
#: proceed without trying to delete the protected directory.
_MACOS_NOISE_DIRS = (
    ".Spotlight-V100",
    ".TemporaryItems",
    ".DocumentRevisions-V100",
)


def neuter_macos_metadata(drive_path: Path) -> None:
    """Suppress macOS auto-created metadata files / dirs on a FAT volume.

    Belt-and-suspenders prevention paired with :func:`disable_spotlight_indexing`
    and :func:`clean_dot_files`.  Plants three sentinel files macOS honours
    persistently across remounts, then removes any noise directories that
    have already accumulated:

    * ``.metadata_never_index`` — Spotlight skips this volume entirely.
    * ``.fseventsd/no_log`` — FSEvents daemon skips logging.
    * ``.Trashes`` (as a *file*) — kernel cannot ``mkdir`` it into the
      preemptively-created ``.Trashes/<UID>/`` directory macOS would
      otherwise plant on every FAT mount and lock down with
      kernel-level read-only perms (the EPERM-on-``unlinkat`` that
      breaks ``rsync --delete``).
    * removes ``.Spotlight-V100`` / ``.TemporaryItems`` /
      ``.DocumentRevisions-V100`` if present.

    Sentinels survive remount (unlike ``mdutil -i off``), so a
    once-deployed CIRCUITPY drive carries the suppression forward
    even if the host changes Spotlight policy mid-session.  Cluster
    cost on FAT12 (Pi Pico W: ~870 KB / 4 KB clusters): three clusters
    for the sentinels, dwarfed by the .Spotlight-V100 directory it
    prevents (often hundreds of KB on a busy host).

    No-op on non-macOS platforms.

    Args:
        drive_path: Mount point of the FAT volume.
    """
    if _sys_module.platform != "darwin":
        return  # pragma: no cover — tests run on macOS

    # Plant sentinels first; cheap and idempotent.
    for relative in _MACOS_SKIP_SENTINELS:
        target = drive_path / relative
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.touch()
        except OSError:
            # Drive may be RO this tick (USB-MSC handoff race) — the
            # caller's normal write path will surface a clearer error
            # than this best-effort sentinel write.
            return

    # Remove already-accumulated noise directories.  shutil.rmtree
    # ignores missing paths; ignore_errors keeps us going if macOS is
    # holding a handle open mid-cleanup.
    for noise_relative in _MACOS_NOISE_DIRS:
        shutil.rmtree(drive_path / noise_relative, ignore_errors=True)


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
