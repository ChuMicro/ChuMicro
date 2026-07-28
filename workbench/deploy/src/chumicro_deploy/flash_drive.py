"""CircuitPython flash-mode USB-drive staging and FAT32 hygiene helpers.

Every helper here operates on filesystem paths or subprocess calls
and has no transport state to carry, so they live as module-level
functions instead of methods on a class.  :func:`flush_volume` takes
an injected sleep callable so tests can skip the real settle delay.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys as _sys_module
from collections.abc import Callable
from pathlib import Path

from .host_platform import install_hint_for_rsync
from .runtime_marker import file_targets_runtime, is_test_support_module


class FlashDriveError(Exception):
    """Raised when a flash-drive staging operation fails."""


#: Seconds to wait after ``sync``/``os.sync()`` so the USB controller
#: finishes writing to FAT32 media.  Without this pause, the device may
#: read stale content even after sync returns.
FLUSH_SETTLE_DELAY = 0.5

#: Floor for the rsync timeout.  Handles cold-start work (USB
#: enumeration, FAT init, raw REPL handoff) regardless of how small
#: the deploy is.  Set generously: false-positives (slow board
#: treated as wedged) are far worse than slow detection of a real
#: wedge.  Anything actually wedged in D-state will hit the next
#: ``write()`` syscall almost immediately, so waiting 4 minutes
#: doesn't materially slow the wedge-detection path.
RSYNC_TIMEOUT_MIN_SECONDS = 240.0

#: Base seconds added to every rsync timeout regardless of size.
#: Covers handshake / enumeration / checksum-sweep jitter that
#: doesn't scale with payload size.
RSYNC_TIMEOUT_BASE_SECONDS = 120.0

#: Per-MB allowance for rsync.  600 s/MB ≈ 1.7 KB/s, sized for the
#: slowest sustained USB-MSC FAT32 write rate.
#: Generous on purpose: a false-positive timeout surfaces as "wedge!"
#: recovery noise, while a real wedge is a clear failure regardless
#: of how long we waited.
#:
#: To override per-call (e.g. an integration test on a known-fast
#: rig), pass ``timeout=`` explicitly to :func:`rsync`.
RSYNC_TIMEOUT_PER_MB_SECONDS = 600.0

#: Hard cap on ``sync``.  A clean flush wraps in single-digit seconds
#: even with 1 MB pending.  30 s is the same "USB stack wedged" guard
#: as the rsync floor.
SYNC_TIMEOUT_SECONDS = 30.0

#: Hard cap on the small metadata helpers (``xattr``, ``mdutil``,
#: ``dot_clean``).  These touch the staging tree (xattr) or the drive
#: at the root level (mdutil / dot_clean), and a healthy invocation
#: returns immediately.  10 s catches the wedged-USB case without
#: penalizing slow USB enumeration.
METADATA_HELPER_TIMEOUT_SECONDS = 10.0


def _directory_size_bytes(path: Path) -> int:
    """Return the sum of file sizes under *path* (recursive).

    Symlinks count once for their target size; broken symlinks and
    files that race-deleted between iteration and stat are ignored
    (a real I/O error surfaces downstream when content is actually
    accessed).
    """
    total = 0
    if not path.is_dir():
        return 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:  # pragma: no cover - race-deletion guard
            continue
    return total


def compute_rsync_timeout_seconds(staging_size_bytes: int) -> float:
    """Pick an rsync timeout proportional to staging-tree size.

    Formula::

        max(RSYNC_TIMEOUT_BASE_SECONDS + size_mb * RSYNC_TIMEOUT_PER_MB_SECONDS,
            RSYNC_TIMEOUT_MIN_SECONDS)

    Scales the deadline so fast boards fail fast on a real wedge
    while slow boards still have headroom to finish.

    Args:
        staging_size_bytes: Sum of file sizes in the local staging
            tree, typically from :func:`_directory_size_bytes`.
    """
    size_mb = staging_size_bytes / (1024 * 1024)
    return max(
        RSYNC_TIMEOUT_BASE_SECONDS + (size_mb * RSYNC_TIMEOUT_PER_MB_SECONDS),
        RSYNC_TIMEOUT_MIN_SECONDS,
    )


def _run_subprocess_with_timeout(
    command: list[str],
    *,
    timeout: float,
    on_timeout_message: str,
    error_class: type[Exception],
    capture_output: bool = True,
    text: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run *command* with a hard timeout and a clear timeout-message.

    Wraps :func:`subprocess.run` with the timeout-as-error pattern so
    every USB-touching subprocess gets the same diagnostic when the
    USB stack wedges.  ``TimeoutExpired`` is raised by
    :func:`subprocess.run` only when the *child* process can be reaped.
    If the child is in D-state on a stuck USB I/O, ``run()`` itself
    hangs in ``waitpid``, so the timeout enforcement is best-effort
    on the most pathological cases.  But for the common
    "rsync got 95% through and the next ``write()`` hangs" scenario
    the timeout fires correctly and we surface a recoverable error
    instead of a wedged process.
    """
    try:
        return subprocess.run(
            command,
            capture_output=capture_output,
            text=text,
            check=check,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as timeout_error:
        raise error_class(on_timeout_message) from timeout_error


def merge_packages(
    source_directory: Path,
    staging_destination: Path,
    *,
    target_runtime: str | None = None,
    include_test_support: bool = False,
) -> None:
    """Copy top-level packages from a source directory to a staging dir.

    Merges into the staging destination using ``dirs_exist_ok=True`` so
    multiple source directories can contribute packages.  Operates on
    the local filesystem (not the USB drive), so ``shutil.copytree``
    is reliable here.

    Args:
        source_directory: A ``src/`` directory containing packages.
        staging_destination: Local staging directory to merge into.
        target_runtime: When set, ``.py`` files carrying a
            ``__chumicro_runtimes__`` marker for a different runtime
            are skipped (in addition to ``__pycache__`` / ``*.pyc``).
            ``None`` (the default) keeps every ``.py`` file regardless
            of its marker.
        include_test_support: When ``False`` (the default), ``.py``
            files marked with ``__chumicro_test_support__ = True`` are
            skipped.  Pass ``True`` to merge them too, e.g. when
            staging a test-fake bundle for on-device test runs.
    """
    if not source_directory.is_dir():
        return
    pattern_ignore = shutil.ignore_patterns("__pycache__", "*.pyc")

    def _ignore(directory: str, names: list[str]) -> set[str]:
        ignored = set(pattern_ignore(directory, names))
        if target_runtime is not None:
            directory_path = Path(directory)
            for name in names:
                if name in ignored:
                    continue
                if not name.endswith(".py"):
                    continue
                if not file_targets_runtime(
                    directory_path / name, target_runtime=target_runtime,
                ):
                    ignored.add(name)
        for name in names:
            if name in ignored or not name.endswith(".py"):
                continue
            if is_test_support_module(
                Path(directory) / name,
            ) and not include_test_support:
                ignored.add(name)
        return ignored

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
            ignore=_ignore,
            dirs_exist_ok=True,
        )


#: Patterns excluded from every CP rsync: build artifacts, macOS
#: file-level detritus, and the macOS volume-level noise dirs plus
#: the skip-sentinels planted in the staging tree.  The inline
#: comments inside the tuple explain each block.
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


def _rsync_exclude_and_endpoint_args(
    source: Path,
    destination: Path,
    *,
    additional_excludes: tuple[str, ...] | list[str],
) -> list[str]:
    """Return the ``--exclude=…`` flags + trailing-slash endpoint args.

    Combines :data:`_BASE_RSYNC_EXCLUDES` with the caller's additions,
    then appends ``str(source) + "/"`` and ``str(destination) + "/"``.
    Centralizes the exclude set and the trailing-slash convention in
    one place.
    """
    args: list[str] = []
    for pattern in _BASE_RSYNC_EXCLUDES:
        args.append(f"--exclude={pattern}")
    for pattern in additional_excludes:
        args.append(f"--exclude={pattern}")
    args.append(str(source) + "/")
    args.append(str(destination) + "/")
    return args


def rsync(
    source: Path,
    destination: Path,
    *,
    delete: bool = True,
    additional_excludes: tuple[str, ...] | list[str] = (),
    timeout: float | None = None,
) -> None:
    """Rsync a source directory's contents to a destination.

    Single FAT-write primitive: ``--checksum`` verifies content
    (FAT32 timestamps are unreliable) and ``--inplace`` avoids
    temp-file rename races on FAT32.  Two parameter shapes:

    * **Clean push**: ``delete=True`` with
      ``additional_excludes=DEVICE_KEEP_SET``.  Clean slate, only the
      closed keep set survives.
    * **Additive push**: ``delete=False`` with no extra excludes.
      Stale files persist.  Used when other board files are
      hand-managed.

    The base exclude set (build artifacts + macOS noise / sentinel
    dirs) is shared and unconditional; see :data:`_BASE_RSYNC_EXCLUDES`.

    Args:
        source: Source directory whose contents to sync.
        destination: Destination directory.
        delete: When ``True``, pass ``--delete`` so files in
            destination but not source are removed (clean slate;
            only ``additional_excludes`` survive).  ``False`` is the
            additive shape, where stale files persist.
        additional_excludes: Extra basenames to add to ``--exclude``.
            Pass :data:`DEVICE_KEEP_SET` on clean pushes so
            ``--delete`` doesn't wipe the device-required keep set;
            leave empty for additive pushes.
        timeout: Override the auto-computed timeout (seconds).  Default
            ``None`` lets :func:`compute_rsync_timeout_seconds` pick
            a value scaled to the staging-tree size.  Pass an explicit
            value when a deterministic deadline is needed.

    Raises:
        FlashDriveError: If rsync is not installed or the sync fails.
    """
    if timeout is None:
        timeout = compute_rsync_timeout_seconds(_directory_size_bytes(source))
    command = [
        "rsync",
        "--recursive",
        "--checksum",
        "--inplace",
    ]
    if delete:
        command.append("--delete")
    command.extend(_rsync_exclude_and_endpoint_args(
        source, destination, additional_excludes=additional_excludes,
    ))
    try:
        _run_subprocess_with_timeout(
            command,
            timeout=timeout,
            on_timeout_message=(
                f"rsync to {destination} hung past {timeout:.0f}s "
                f"(scaled from staging-tree size).  Most common cause "
                "is the board's USB-CDC firmware hung mid-write (the "
                "CP runtime got into a bad state during the previous "
                "test, or the board's USB stack hiccupped).  Reboot "
                "the board (unplug + replug) and re-run.  If the rsync "
                "is just genuinely slow on this board (Lolin S2 / "
                "ESP32-S2 CP can run ~10× slower than Pi Pico W on "
                "USB-MSC FAT writes), bump RSYNC_TIMEOUT_PER_MB_SECONDS "
                "in chumicro_deploy.flash_drive.  Without this timeout "
                "the rsync subprocess would have entered uninterruptible "
                "kernel I/O wait, where ``kill -9`` is impossible until "
                "the board is physically power-cycled."
            ),
            error_class=FlashDriveError,
            text=True,
        )
    except FileNotFoundError as not_found_error:
        raise FlashDriveError(
            "rsync is required for flash deploy mode but was not found.  "
            f"{install_hint_for_rsync()}"
        ) from not_found_error
    except subprocess.CalledProcessError as rsync_error:
        raise FlashDriveError(
            f"rsync failed: {rsync_error.stderr}"
        ) from rsync_error


#: Device-generated / device-required files that survive a clean
#: deploy on every path.  The CP clean ``--exclude`` and the diff
#: scope both derive from this one tuple rather than hard-coding
#: their own list, so "what survives a deploy" cannot drift between
#: paths.
#:
#: * ``boot_out.txt``: CP writes it only on a *hard* reboot, and a
#:   deploy soft-reboots, so wiping it strands the drive without
#:   identity until the next power cycle and breaks the next deploy's
#:   UID drive-match on multi-board hosts.
#: * ``boot.py``: a device necessity, and a project that ships its
#:   own ``boot.py`` overwrites it as payload (payload always wins).
#: * ``_chu_kv.msgpack``: the only filesystem-backed kvstore case
#:   (MP non-NVS boards), and CP ``nvm`` / ESP32 ``nvs`` are
#:   off-filesystem and never at risk.
#:
#: ``settings.toml`` is deliberately NOT here: a board-resident one is
#: a competing wifi authority vs chumicro's config-driven wifi
#: (``runtime_config.msgpack`` + host ``secrets.toml``), so it is
#: evicted on every path, with a one-time loud notice when one is
#: actually present.
DEVICE_KEEP_SET: tuple[str, ...] = (
    "boot.py",
    "boot_out.txt",
    "_chu_kv.msgpack",
)


def verify_rsync(
    source: Path,
    destination: Path,
    *,
    additional_excludes: tuple[str, ...] | list[str] = (),
    timeout: float = 30.0,
) -> list[str]:
    """Confirm *destination*'s contents match *source* via rsync dry-run.

    Runs ``rsync --recursive --checksum --dry-run --itemize-changes``
    (the same flags :func:`rsync` uses, plus dry-run + itemize) and
    returns the list of paths rsync reports as needing update.  When
    the previous real :func:`rsync` call committed every byte, the
    list is empty.  Non-empty means content on the volume diverged
    from the staging tree, which is the signal for FAT corruption,
    USB-MSC partial-write, or a drive that quietly went read-only
    after the writes started.

    Itemize-changes flag positions: position 1 is the update marker
    (``<`` / ``>`` / ``c`` / ``h`` mean "would transfer"; ``.`` /
    ``*`` mean "no update needed").  We filter on the first character
    so cosmetic time / permission deltas (``.f..T....``) don't fire
    a false positive.  Only real content / size diffs do.

    Args:
        source: Staging tree that was rsynced to *destination*.
        destination: Mount point that should now mirror *source*.
        additional_excludes: Extra basenames passed through to
            ``--exclude`` so the dry-run scope matches the original
            rsync's scope exactly.
        timeout: Subprocess deadline (seconds).  Verification reads
            every file from the FAT volume.

    Returns:
        Sorted list of source-relative paths that the verification
        rsync would update.  Empty on success.

    Raises:
        FlashDriveError: rsync is missing or the subprocess errored
            for a reason other than "would-update detected" (which
            shows up in stdout, not as a non-zero exit).
    """
    command = [
        "rsync",
        "--recursive",
        "--checksum",
        "--dry-run",
        "--itemize-changes",
    ]
    command.extend(_rsync_exclude_and_endpoint_args(
        source, destination, additional_excludes=additional_excludes,
    ))
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except FileNotFoundError as not_found_error:
        raise FlashDriveError(
            "rsync is required for verification but was not found.  "
            f"{install_hint_for_rsync()}"
        ) from not_found_error
    except subprocess.CalledProcessError as rsync_error:
        raise FlashDriveError(
            f"rsync verification failed: {rsync_error.stderr}"
        ) from rsync_error
    except subprocess.TimeoutExpired as timeout_error:
        raise FlashDriveError(
            f"rsync verification hung past {timeout:.0f}s.  The FAT "
            "volume may have wedged after the main rsync.  Tap RESET "
            "and re-deploy."
        ) from timeout_error
    needs_update = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        marker = line[0]
        if marker in ("<", ">", "c", "h"):
            parts = line.split(None, 1)
            if len(parts) == 2:
                needs_update.append(parts[1])
    return sorted(needs_update)


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
        return  # pragma: no cover -tests run on macOS
    try:
        subprocess.run(
            ["xattr", "-cr", str(path)],
            capture_output=True,
            check=False,
            timeout=METADATA_HELPER_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        print("WARNING: xattr not found: skipping extended attribute removal")
    except subprocess.TimeoutExpired:  # pragma: no cover -defensive
        print(
            "WARNING: xattr -cr hung past "
            f"{METADATA_HELPER_TIMEOUT_SECONDS:.0f}s, continuing without it"
        )


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
        return  # pragma: no cover -tests run on macOS
    try:
        subprocess.run(
            ["dot_clean", str(drive_path)],
            capture_output=True,
            check=False,
            timeout=METADATA_HELPER_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        print("WARNING: dot_clean not found: skipping ._ file cleanup")
    except subprocess.TimeoutExpired:  # pragma: no cover -defensive
        print(
            "WARNING: dot_clean hung past "
            f"{METADATA_HELPER_TIMEOUT_SECONDS:.0f}s, continuing without it"
        )


#: Sentinel files / directories macOS recognizes to skip a volume.  Planted
#: at the drive root so subsequent remounts inherit the suppression, the
#: equivalent of ``mdutil -i off`` (which resets on remount) but persistent.
#:
#: ``.Trashes`` is the load-bearing one: macOS preemptively creates
#: ``.Trashes/<UID>/`` on every FAT mount, then sets the inner UID dir
#: read-only at the kernel level so even the mounting user can't
#: ``unlinkat`` it (``rsync --delete`` aborts with ``Operation not
#: permitted``).  Planting ``.Trashes`` as a *file*
#: blocks macOS from creating the directory in the first place,
#: because the kernel can't ``mkdir`` over an existing non-directory
#: entry.  Already-contaminated drives keep their protected dir, and
#: the rsync exclude in :func:`rsync` handles those.
_MACOS_SKIP_SENTINELS = (
    ".metadata_never_index",  # Spotlight: skip indexing this volume.
    ".fseventsd/no_log",      # FSEvents daemon: skip logging this volume.
    ".Trashes",               # Trash daemon: file-shaped sentinel blocks dir creation.
)

#: Metadata directories macOS auto-creates on FAT volumes.  Removed defensively
#: at deploy time.  They re-appear if macOS still wants them, but the sentinel
#: files above usually persuade it not to.
#:
#: ``.Trashes`` is deliberately absent here: the sentinel above
#: blocks its creation, and on a drive already carrying the protected
#: directory the ``--exclude=.Trashes`` line in :func:`rsync` lets
#: the deploy proceed without trying to delete it.
_MACOS_NOISE_DIRS = (
    ".Spotlight-V100",
    ".TemporaryItems",
    ".DocumentRevisions-V100",
)


def plant_macos_sentinels_in_staging(staging_path: Path) -> None:
    """Plant macOS skip-sentinels into a local staging directory.

    The sentinels (see :data:`_MACOS_SKIP_SENTINELS` for what each
    suppresses) go at the staging-tree root so rsync ships them onto
    CIRCUITPY in the same pass as the payload.  No host-side write to
    the live drive before rsync starts, since every such write can
    wedge rsync in uninterruptible kernel I/O.

    No-op on non-macOS platforms.

    Args:
        staging_path: Local staging-tree root.  rsync will copy
            everything under this into the CIRCUITPY drive root.
    """
    if _sys_module.platform != "darwin":
        return  # pragma: no cover -tests run on macOS
    for relative in _MACOS_SKIP_SENTINELS:
        target = staging_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()


def cleanup_macos_noise_dirs_post_rsync(drive_path: Path) -> None:
    """Remove already-accumulated macOS noise directories from the drive.

    Called *after* rsync so the wedge-risky on-drive writes stay
    inside the single rsync pass.  Clears the noise dirs a drive
    picked up from earlier macOS mounts (:data:`_MACOS_NOISE_DIRS`);
    ``rsync --delete`` can't, since they're excluded and partly
    kernel-locked on FAT.  ``shutil.rmtree(ignore_errors=True)`` walks
    them best-effort, so a drive the sentinels already keep clean is a
    no-op.

    No-op on non-macOS platforms.

    Args:
        drive_path: Mount point of the CIRCUITPY drive.
    """
    if _sys_module.platform != "darwin":
        return  # pragma: no cover -tests run on macOS
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

    The settle delay goes through the injected *sleep* callable so
    tests can use a fake time source to skip it without sleeping
    for real.

    Args:
        drive_path: Path on the volume to flush.
        sleep: Callable that sleeps for the given number of seconds.
        settle_delay: Seconds to wait after the sync.
    """
    if _sys_module.platform == "darwin":
        try:
            subprocess.run(
                ["sync"],
                check=True,
                capture_output=True,
                timeout=SYNC_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:  # pragma: no cover -defensive
            print(
                f"WARNING: sync hung past {SYNC_TIMEOUT_SECONDS:.0f}s: "
                "USB stack may be wedged.  Falling back to os.sync()"
            )
            os.sync()
        except Exception:  # pragma: no cover
            print("WARNING: sync command failed: falling back to os.sync()")
            os.sync()
    else:
        os.sync()  # pragma: no cover -tests run on macOS

    sleep(settle_delay)
