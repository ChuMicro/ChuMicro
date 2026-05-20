"""DeviceBackend — runs tests on a real board via a chumicro-deploy transport.

Owns the connect → stage → execute → recover flow for the device
target.  Stateless — all per-device state lives in the session-
scoped :class:`chumicro_pytest_device.transport_cache._TransportCache`.

Companion module to :mod:`backends` (the protocol + the unix-port
implementation): kept separate so the device-side helpers
(``_clear_entrypoints_or_fail`` / ``_soft_reset_or_fail`` /
``_stage_one_item`` / ``_bulk_stage_for_device``) and the
``_should_soft_reset_before_stage`` policy live next to their single
consumer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from chumicro_deploy import DeviceEntry, TransportProtocol

from .backends import BackendExecuteError, BackendPrepareError
from .collection import _bulk_stage_for_device, _session_effective_deploy_mode
from .session import (
    _encode_runtime_config_extra_files,
    _harness_source_dir,
    _libraries_root,
    _session_cache,
    _session_per_file,
    _target_is_device_unit,
)
from .test_runner import (
    build_device_bootstrap,
    execute_device_bootstrap,
    resolve_library_source_dirs,
)
from .transport_cache import _TransportCache

if TYPE_CHECKING:
    from .collection import DeviceRuntimeItem


#: Transport modes that hold a persistent interpreter across test files.
#: Both CircuitPython ``"ram"`` (inline bootstrap) and MicroPython
#: ``"mount"`` (mpremote ``mount_local``) reuse the same live VM from
#: one file to the next, so ``sys.modules`` accumulates until a soft
#: reset clears it.  Other modes copy files to flash and import fresh
#: per call, so they don't need the inter-file reset.
_IN_MEMORY_MODES = ("ram", "mount")


def _should_soft_reset_before_stage(
    cache: _TransportCache,
    device_entry: DeviceEntry,
    transport: TransportProtocol,
    library_name: str,
    test_file_name: str,
) -> bool:
    """Return whether in-memory re-staging should soft-reset first.

    Both CircuitPython RAM mode and MicroPython mount mode keep the same
    interpreter across test files (raw REPL or persistent serial via
    mpremote).  Without a soft reset between files the previous file's
    modules stay in ``sys.modules`` and consume heap; on Tier-2 boards
    (RP2040 class, 264 KB SRAM) that can exhaust RAM after a handful
    of libraries and fail the next bootstrap with ``MemoryError`` before
    execution even begins.

    The soft reset is a VM-level Ctrl-D via raw REPL — it does not
    toggle USB or re-enumerate the CDC, so it is safe to run between
    every file.

    To preserve batching within a file while reclaiming memory across
    files, soft-reset only when all of the following are true:

    - the transport is in an in-memory mode (``ram`` or ``mount``),
    - the device previously staged a file in this session, and
    - the current staging target differs from the last one.

    Args:
        cache: Session transport cache.
        device_entry: Target device.
        transport: Connected transport instance.
        library_name: Library for the current item.
        test_file_name: Test file for the current item.

    Returns:
        ``True`` when a soft reset should run before ``stage()``.
    """
    if transport.mode not in _IN_MEMORY_MODES:
        return False
    if not cache.has_staged_file(device_entry.identifier):
        return False
    return cache.needs_staging(
        (device_entry.identifier, library_name, test_file_name),
    )


def _clear_entrypoints_or_fail(transport: TransportProtocol) -> None:
    """Drop any stale ``code.py``/``main.py`` left over from a prior deploy.

    The on-device unit + functional sweeps soft-reset between
    libraries/files, and a leftover entrypoint that hard-faults
    would race the reboot.  The sweep's rsync excludes entrypoints
    and the harness never writes one, so a single clear at the
    sweep's start holds for the rest of the session.  ``pytest.fail``
    on error gives a clear single-line failure rather than a
    transport-level traceback.
    """
    try:
        transport.clear_entrypoints()
    except Exception as error:
        pytest.fail(
            f"Failed to clear stale entrypoint before sweep: {error}",
        )


def _soft_reset_or_fail(transport: TransportProtocol, when: str) -> None:
    """Soft-reset the device, raising ``pytest.fail`` with *when* on error.

    *when* is a short phrase describing where the reset sits in the
    sweep (e.g. ``"before test file (--per-file)"``) so the failure
    message names the lifecycle point.
    """
    try:
        transport.soft_reset()
    except Exception as error:
        pytest.fail(f"Device reset failed {when}: {error}")


def _stage_one_item(
    session: pytest.Session,
    transport: TransportProtocol,
    item: DeviceRuntimeItem,
) -> None:
    """Stage one ``DeviceRuntimeItem``'s library closure + test file.

    The per-file staging shape shared by the RAM/mount path and the
    ``--per-file`` flash path: resolve the library's source closure
    (intra-workspace dependency walk), call ``transport.stage()``
    with the single test file, harness, runtime-config extras, and
    the device-unit support flag.  Bulk per-library staging uses
    :func:`_bulk_stage_for_device` instead.
    """
    source_dirs = resolve_library_source_dirs(
        item.library_dir,
        libraries_root=_libraries_root(session),
        test_files=[item.test_file],
    )
    transport.stage(
        source_dirs,
        [item.test_file],
        _harness_source_dir(session),
        extra_files=_encode_runtime_config_extra_files(session.config),
        include_test_support=_target_is_device_unit(session.config),
    )


class DeviceBackend:
    """Backend that runs tests on a real board via a ``chumicro-deploy`` transport.

    Owns the connect → stage → execute → recover flow.  Stateless — all
    per-device state lives in the session-scoped
    :class:`chumicro_pytest_device.transport_cache._TransportCache`.
    """

    def prepare(
        self,
        item: DeviceRuntimeItem,
        device_entry: DeviceEntry,
    ) -> None:
        """Connect the transport and stage source files if needed.

        Raises :class:`BackendPrepareError` on transport-connection
        failure; lets staging exceptions propagate as plain exceptions
        (matching the original behavior for that path).
        """
        cache = _session_cache(item.session)
        deploy_mode = _session_effective_deploy_mode(item.session, device_entry)

        try:
            transport = cache.get_transport(device_entry, deploy_mode)
        except Exception as error:
            raise BackendPrepareError(
                f"Transport connection failed: {error}",
            ) from error

        # Flash/copy modes persist files on the device filesystem.
        # Default (no ``--per-file``): bulk-stage one library's whole
        # test suite + src per rsync (fewest rsyncs; fits the ample
        # flash of PSRAM boards).  ``--per-file``: stage one test file
        # at a time, because a heavy library's *entire* suite + src +
        # harness overflows a 491 KB Pi Pico W drive.  Either way
        # per-library/per-file scope keeps the working-set bounded and
        # rsync ``--delete`` cleans the prior library/file off.  RAM
        # mode embeds source inline, so it re-stages per file.
        is_filesystem_mode = transport.mode not in ("ram", "mount")
        if is_filesystem_mode and _session_per_file(item.session):
            # ``--per-file`` flash: stage exactly *one* test file at a
            # time (this file + the library src + the harness), with a
            # fresh-VM soft reset before each file.  The bulk path
            # below stages a library's *entire* test suite in one
            # rsync; a heavy library's full suite + src + harness
            # exceeds a 491 KB Pi Pico W CIRCUITPY drive (rsync then
            # fails ``No space left on device`` before any test runs).
            # rsync ``--delete`` keeps the drive at src + harness +
            # this one file (~bounded, fits 491 KB) and cleans the
            # prior file — and the prior library — off.  Re-pushing
            # src + harness per file is the deliberate cost: ``--per-
            # file`` exists for the constrained board, where fitting
            # the drive matters more than rsync count.  Idempotent:
            # prepare() runs twice per file batch (DevicePrepareItem
            # then DeviceRunFileItem) — the pending check fires the
            # reset+stage exactly once.
            batch_key = item.batch_key(device_entry)
            if cache.per_file_reset_pending(batch_key):
                if cache.current_staged_library(
                    device_entry.identifier,
                ) is None:
                    _clear_entrypoints_or_fail(transport)
                _soft_reset_or_fail(
                    transport, "before test file (--per-file)",
                )
                _stage_one_item(item.session, transport, item)
                cache.mark_library_staged(
                    device_entry.identifier, item.library_name,
                )
                cache.mark_per_file_reset(batch_key)
        elif is_filesystem_mode:
            current_library = cache.current_staged_library(
                device_entry.identifier,
            )
            if current_library != item.library_name:
                if current_library is None:
                    _clear_entrypoints_or_fail(transport)
                # The flash/copy sweep runs every library over one
                # persistent interpreter.  Soft-reset *before* staging
                # each library so it runs from a fresh VM (cleared
                # sys.modules, full heap): without this, accumulated
                # live modules exhaust a 264 KB board and larger test
                # modules fail to exec (MemoryError).  With the
                # entrypoint cleared above, the reboot drops straight
                # to a clean raw REPL — the same fresh-interpreter
                # guarantee mount/RAM mode already gets per file.
                # Reset before the first library too, so the run never
                # inherits whatever VM state the board booted with.
                _soft_reset_or_fail(transport, "before staging library")
                _bulk_stage_for_device(
                    item.session,
                    device_entry,
                    transport,
                    library_filter=item.library_name,
                )
                cache.mark_library_staged(
                    device_entry.identifier, item.library_name,
                )
        else:
            staging_key = item.batch_key(device_entry)
            if cache.needs_staging(staging_key):
                if _should_soft_reset_before_stage(
                    cache,
                    device_entry,
                    transport,
                    item.library_name,
                    item.test_file.name,
                ):
                    _soft_reset_or_fail(transport, "between test files")
                _stage_one_item(item.session, transport, item)
                cache.mark_staged(staging_key)

    def execute(
        self,
        item: DeviceRuntimeItem,
        device_entry: DeviceEntry,
    ) -> str:
        """Run every test in ``item.test_file`` on the device.

        On execution failure, attempts ``transport.recover()`` so the
        next file can run independently; if recovery itself fails,
        evicts the transport from the cache so the next item reconnects
        from scratch.  Always raises :class:`BackendExecuteError` —
        the caller turns that into a single ``pytest.fail``.
        """
        cache = _session_cache(item.session)
        transport = cache.get_transport(
            device_entry,
            _session_effective_deploy_mode(item.session, device_entry),
        )
        # Run ALL tests in the file (no name_filter) to amortize the
        # per-invocation overhead.
        bootstrap = build_device_bootstrap(
            device_entry, transport, item.test_file, None,
        )
        try:
            return execute_device_bootstrap(transport, bootstrap)
        except Exception as error:
            # Try to recover the board so the next file can run
            # independently of this failure; if recovery itself
            # fails, evict the transport so the next item reconnects
            # from scratch.  Without this, every subsequent file
            # cascade-failed because the cached transport was stuck
            # mid-raw-REPL or mid-mpremote.
            error_message = f"Device execution failed: {error}"
            recovery_failed = False
            try:
                transport.recover()
            except Exception as recover_error:  # pragma: no cover - hardware-only
                recovery_failed = True
                error_message = (
                    f"{error_message}\n"
                    f"Recovery failed: {recover_error}; "
                    f"evicting transport for {device_entry.identifier}"
                )
            if recovery_failed:
                cache.invalidate_device(device_entry.identifier)
            raise BackendExecuteError(error_message) from error
