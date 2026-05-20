"""Session-scoped cache for device transports + batch results.

Owns the "one transport per device id" + "one parsed batch result per
(device, library, file)" lookups the plugin uses during a sweep.
Kept here as a leaf module so it can be imported by both
:mod:`device_backend` (the consumer) and :mod:`plugin` (the
session-state wiring) without any cycle.
"""

from __future__ import annotations

from chumicro_deploy import DeviceEntry, TransportProtocol

from .result_parser import RunResult
from .test_runner import build_transport_for_entry


class _TransportCache:
    """Session-scoped cache for device transports and batch results.

    Avoids reconnecting for every test item.  Stores one transport
    per device ID and tracks the last-staged library *and test file*
    to avoid redundant staging while ensuring re-staging when the
    test file changes (critical for RAM mode where test file content
    is part of the staged sources).

    Also caches batch execution results: the first test item for a
    given ``(device, library, file)`` combo runs *all* tests in the
    file at once and caches the parsed output.  Subsequent items
    look up their result from the cache.  This amortizes the per-
    invocation overhead of transports like ``mpremote`` that spawn
    a fresh subprocess per ``execute()`` call.
    """

    def __init__(self) -> None:
        self._transports: dict[str, TransportProtocol] = {}
        self._last_staged: dict[str, tuple[str, str]] = {}
        #: Library currently staged on each device (flash/copy modes).
        #: Bulk staging is scoped to ONE library at a time so the
        #: drive working-set stays bounded — a 491 KB Pi Pico W
        #: CIRCUITPY drive can't hold every library's source +
        #: every library's test files at once.  When a test for a
        #: different library runs, the next stage rsync uses
        #: ``--delete`` to clean the prior library off the drive.
        self._staged_library: dict[str, str] = {}
        #: Batch keys that have already had their ``--per-file`` soft
        #: reset issued.  ``prepare()`` runs twice per file batch
        #: (DevicePrepareItem then DeviceRunFileItem); without this the
        #: per-file reset would fire twice.  Mirrors how
        #: ``_staged_library`` makes the per-library reset idempotent.
        self._per_file_reset_done: set[tuple[str, str, str]] = set()
        #: Cached batch results keyed by (device_id, library, file).
        #: Value is (parsed_result_or_None, raw_output_or_error).
        self._batch_results: dict[
            tuple[str, str, str], tuple[RunResult | None, str]
        ] = {}
        #: Deploy mode resolved once per device (session-scoped — the
        #: transport is cached per device, so the mode cannot change
        #: mid-session).  The first resolution for a device computes it
        #: from the full closure of every test targeting that device
        #: and memoizes here; later calls reuse it, which also makes
        #: any RAM→flash override message print exactly once.
        self._resolved_deploy_mode: dict[str, str] = {}

    def get_transport(
        self, device_entry: DeviceEntry, deploy_mode: str | None,
    ) -> TransportProtocol:
        """Get or create a connected transport for the device.

        Args:
            device_entry: A ``DeviceEntry`` from the config loader.
            deploy_mode: Deploy mode override, or ``None``.

        Returns:
            A connected transport instance.
        """
        key = device_entry.identifier
        if key not in self._transports:
            transport = build_transport_for_entry(device_entry, deploy_mode=deploy_mode)
            transport.connect()
            self._transports[key] = transport
        return self._transports[key]

    def peek_transport(self, device_id: str) -> TransportProtocol | None:
        """Return the connected transport for a device without creating one.

        Use this when the caller wants to act on an existing transport
        (e.g. probe metadata for PR-summary rendering) but should NOT
        connect a fresh one as a side effect.  Returns ``None`` when no
        transport is cached yet.
        """
        return self._transports.get(device_id)

    def needs_staging(self, batch_key: tuple[str, str, str]) -> bool:
        """Check whether the library/test file needs to be staged.

        In RAM mode, staged sources include the test file content.
        Re-staging is needed when either the library or the test file
        changes.

        Args:
            batch_key: ``(device_id, library_name, test_file_name)``
                from ``DeviceRuntimeItem.batch_key``.

        Returns:
            ``True`` if staging is needed.
        """
        device_id, library_name, test_file_name = batch_key
        return self._last_staged.get(device_id) != (library_name, test_file_name)

    def mark_staged(self, batch_key: tuple[str, str, str]) -> None:
        """Record that a library/test file has been staged on a device.

        Args:
            batch_key: ``(device_id, library_name, test_file_name)``
                from ``DeviceRuntimeItem.batch_key``.
        """
        device_id, library_name, test_file_name = batch_key
        self._last_staged[device_id] = (library_name, test_file_name)

    def resolved_deploy_mode(self, device_id: str) -> str | None:
        """Return the memoized session deploy mode for a device, if any."""
        return self._resolved_deploy_mode.get(device_id)

    def set_resolved_deploy_mode(self, device_id: str, mode: str) -> None:
        """Memoize the resolved session deploy mode for a device."""
        self._resolved_deploy_mode[device_id] = mode

    def has_staged_file(self, device_id: str) -> bool:
        """Return whether the device has staged a RAM-mode file already.

        Args:
            device_id: Device identifier.

        Returns:
            ``True`` when at least one ``(library, file)`` staging record
            exists for the device.
        """
        return device_id in self._last_staged

    def get_batch_result(
        self, batch_key: tuple[str, str, str],
    ) -> tuple[RunResult | None, str] | None:
        """Return cached batch result, or ``None`` if not yet executed.

        Args:
            batch_key: ``(device_id, library_name, test_file_name)``
                from ``DeviceRuntimeItem.batch_key``.

        Returns:
            Tuple of ``(parsed_result, raw_output)`` if cached, else
            ``None``.  When the batch execution failed,
            ``parsed_result`` is ``None`` and ``raw_output`` contains
            the error message.
        """
        return self._batch_results.get(batch_key)

    def cache_batch_result(
        self,
        batch_key: tuple[str, str, str],
        parsed_result: RunResult | None,
        raw_output: str,
    ) -> None:
        """Store a batch execution result.

        Args:
            batch_key: ``(device_id, library_name, test_file_name)``
                from ``DeviceRuntimeItem.batch_key``.
            parsed_result: Parsed harness output, or ``None`` on failure.
            raw_output: Raw device output or error message.
        """
        self._batch_results[batch_key] = (parsed_result, raw_output)

    def current_staged_library(self, device_id: str) -> str | None:
        """Return the library currently bulk-staged on a device.

        In flash/copy modes, staging is scoped to ONE library at a
        time — the rsync payload (library src + that library's test
        files) plus boot files must fit on the drive.  Pi Pico W
        CIRCUITPY drives are 491 KB; staging every library at once
        overflows.  Per-library staging keeps the drive working-set
        bounded; rsync ``--delete`` cleans the prior library when
        switching.

        Args:
            device_id: Device identifier.

        Returns:
            The library name currently staged, or ``None`` when no
            library is staged yet (i.e. fresh transport).
        """
        return self._staged_library.get(device_id)

    def mark_library_staged(self, device_id: str, library_name: str) -> None:
        """Record that a library has been bulk-staged onto a device.

        Args:
            device_id: Device identifier.
            library_name: The library whose source + test files now
                live on the device.  Replaces any previously-staged
                library marker.
        """
        self._staged_library[device_id] = library_name

    def per_file_reset_pending(self, batch_key: tuple[str, str, str]) -> bool:
        """Return whether this file batch still needs its ``--per-file`` reset.

        ``prepare()`` runs twice per file batch (DevicePrepareItem then
        DeviceRunFileItem); only the first should soft-reset.

        Args:
            batch_key: ``(device_id, library_name, test_file_name)``.
        """
        return batch_key not in self._per_file_reset_done

    def mark_per_file_reset(self, batch_key: tuple[str, str, str]) -> None:
        """Record that this file batch has had its ``--per-file`` reset.

        Args:
            batch_key: ``(device_id, library_name, test_file_name)``.
        """
        self._per_file_reset_done.add(batch_key)

    def invalidate_device(self, device_id: str) -> None:
        """Drop all cached state for a device after a fatal transport error.

        Called when a batch execution fails and ``transport.recover()``
        cannot guarantee the board is in a usable state.  Removes the
        transport (so the next item reconnects from scratch), the
        staging records (so the next item re-stages), and the
        fully-staged marker.  Cached batch results are kept so subsequent
        items from the same file still see the original failure rather
        than retrying and getting confusing partial output.

        Args:
            device_id: Device identifier.
        """
        transport = self._transports.pop(device_id, None)
        if transport is not None:
            try:
                transport.disconnect()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
        self._last_staged.pop(device_id, None)
        self._staged_library.pop(device_id, None)
        self._per_file_reset_done = {
            key for key in self._per_file_reset_done if key[0] != device_id
        }

    def disconnect_all(self) -> None:
        """Disconnect all cached transports.

        ``disconnect()`` is pure teardown — exits raw REPL (Ctrl-B)
        and closes the serial port.  It deliberately does NOT touch
        ``supervisor.runtime.autoreload`` or fire an explicit Ctrl-D
        soft-reboot: those caused a double-reboot wedge on ESP32-S2
        USB-CDC firmware where the post-Ctrl-D soft-reboot landed
        before the host had finished closing the serial port.

        Net effect at session end: each board is left in friendly
        REPL with the serial port closed.  On the ``deploy_files``
        path autoreload is already back to default-on (the deploy
        soft-reboot reset it); on the functional-test path autoreload
        stays off until the user resets / power-cycles the board,
        which is acceptable because tests drive the raw REPL directly
        and never depend on ``code.py``-style reload-on-edit.
        """
        for transport in self._transports.values():
            try:
                transport.disconnect()
            except Exception:  # pragma: no cover
                pass
        self._transports.clear()
        self._last_staged.clear()
        self._staged_library.clear()
        self._batch_results.clear()
