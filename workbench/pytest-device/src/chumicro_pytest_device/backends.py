"""Execution backends for harness-shaped test files.

A :class:`Backend` is the pluggable bit that knows *how* to run a
single ``functional_tests/`` or ``tests/`` file: where to send the
source, what to spawn, what to read back.  The caller (the pytest
items in :mod:`chumicro_pytest_device.plugin`) owns everything that
isn't backend-specific — batch-result caching, harness output
parsing, ``pytest.fail`` orchestration, PR-summary collection.

Two backends are defined:

- :class:`DeviceBackend` — runs the file on a real board via the
  ``chumicro-deploy`` transport.  Owns connect, stage, soft-reset,
  recover semantics.
- :class:`UnixPortBackend` — runs the file in a MicroPython /
  CircuitPython unix-port subprocess.  No transport, no staging;
  resolves the runtime binary and spawns
  ``<binary> support/test_harness/run_cross_runtime.py --worker``.

Both raise :class:`BackendPrepareError` or :class:`BackendExecuteError`
on failure so the caller can route the message through ``pytest.fail``
uniformly.

Note on the ``TYPE_CHECKING`` import: backends call back into the
plugin module to read session-scoped helpers like the transport cache
and library/harness paths.  At runtime that's a normal import (the
plugin module is already loaded when items are running); at type-check
time we defer it so static analysis doesn't see the cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from chumicro_deploy import DeviceEntry
    from chumicro_pytest_device.plugin import DeviceRuntimeItem


class BackendPrepareError(Exception):
    """Raised by ``Backend.prepare`` when setup fails.

    The caller turns this into a ``pytest.fail`` with the message
    preserved; the file-level batch result is cached as a failure so
    every per-test item from that file also fails fast.
    """


class BackendExecuteError(Exception):
    """Raised by ``Backend.execute`` when running the test batch fails.

    Backends handle their own best-effort recovery (transport recover,
    process cleanup) *before* raising so the next file can run
    independently of this failure.
    """


@runtime_checkable
class Backend(Protocol):
    """Pluggable execution backend protocol."""

    name: str
    """Short backend identifier — ``"device"`` or ``"unix-port"``."""

    def prepare(
        self,
        item: DeviceRuntimeItem,
        target: DeviceEntry,
    ) -> None:
        """Set up whatever the backend needs before executing tests.

        Args:
            item: The pytest item being prepared (gives access to
                ``test_file``, ``library_dir``, ``session``).
            target: The selected device entry for this item.  For
                ``DeviceBackend`` this is a real board; for
                ``UnixPortBackend`` it's a synthetic entry whose
                ``runtime`` field picks the binary.

        Raises:
            BackendPrepareError: On any setup failure.
        """

    def execute(
        self,
        item: DeviceRuntimeItem,
        target: DeviceEntry,
    ) -> str:
        """Run every ``test_*`` in ``item.test_file`` once.

        Args:
            item: As in :meth:`prepare`.
            target: As in :meth:`prepare`.

        Returns:
            Raw stdout from the harness, ready for
            :func:`chumicro_pytest_device.result_parser.parse_output`.

        Raises:
            BackendExecuteError: On any execution failure, after the
                backend's own recovery has run.
        """
