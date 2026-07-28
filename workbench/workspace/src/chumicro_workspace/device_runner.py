"""Background-thread bootstrap runner: overlap a host orchestrator with a board run.

The board prints checkpoint markers on its stdout (``SERVER_READY
ip=... port=...``, ``MQTT_CONNECTED broker=...``) and the host
orchestrator reacts mid-execute: open a TCP connection, publish a
command, wait for the next marker.  That overlap requires the board's
bootstrap to run concurrently with the host code that drives it.

:class:`DeviceBootstrapRunner` spawns a daemon thread that calls
``transport.execute(bootstrap, on_line=...)``; the ``on_line`` callback
parses each captured stdout line and pushes any markers onto the
internal :class:`MarkerQueue`.  The host code calls :meth:`wait_for`
to block on a specific marker, then later :meth:`wait_for_completion`
to join the thread and read the captured stdout.

The board side stays single-threaded cooperative; this module adds
no constraints to what runs on the device.  All concurrency is
host-side.

Consumed by `chumicro_workspace.deploy_api` (programmatic demo /
tooling entry point) and by `chumicro_pytest_device` (the pytest
collection layer that drives functional tests).
"""

from __future__ import annotations

import threading
from types import TracebackType

from chumicro_deploy import ExtendedTransportProtocol, TransportProtocol

from .markers import Marker, MarkerQueue


class RunnerNotStartedError(RuntimeError):
    """Raised when :meth:`DeviceBootstrapRunner.wait_for_completion` is
    called before :meth:`DeviceBootstrapRunner.start`."""


class DeviceBootstrapRunner:
    """Runs a device bootstrap on a background thread and exposes its output.

    Usage:

        runner = DeviceBootstrapRunner(transport, bootstrap)
        runner.start()
        marker = runner.wait_for("SERVER_READY", timeout_s=10)
        # ... do host-side work using marker.values ...
        captured_stdout = runner.wait_for_completion(timeout_s=30)
        runner.shutdown()

    Or as a context manager, where :meth:`shutdown` is called on exit even
    if the body raises::

        with DeviceBootstrapRunner(transport, bootstrap) as runner:
            runner.start()
            ...

    :meth:`start` is callable only once per instance; a second call
    raises :class:`RuntimeError` rather than silently spawning a
    second thread that would race the first.
    """

    def __init__(
        self,
        transport: TransportProtocol,
        bootstrap: str | list[str],
    ) -> None:
        self._transport = transport
        self._bootstrap = bootstrap
        self._marker_queue: MarkerQueue = MarkerQueue()
        self._thread: threading.Thread | None = None
        self._captured_output: str | None = None
        self._error: BaseException | None = None
        self._started = False

    @property
    def marker_queue(self) -> MarkerQueue:
        """The marker queue the on_line callback pushes into.

        Exposed so tests and future fixtures can inspect or drive the
        queue directly when the wait_for / push surface isn't enough.
        """
        return self._marker_queue

    def start(self) -> None:
        """Spawn the background thread that runs the bootstrap on the device.

        Raises:
            RuntimeError: :meth:`start` has already been called on this
                instance.
        """
        if self._started:
            raise RuntimeError(
                "DeviceBootstrapRunner.start() may only be called once "
                "per instance; create a new runner for a new bootstrap.",
            )
        self._started = True
        self._thread = threading.Thread(
            target=self._run, name="DeviceBootstrapRunner", daemon=True,
        )
        self._thread.start()

    def wait_for(self, name: str, *, timeout_s: float) -> Marker:
        """Block until a marker named *name* arrives on the device's stdout.

        Forwards to :meth:`MarkerQueue.wait_for`.  Non-matching markers
        that arrive while waiting are retained for later waits; on
        timeout, raises :class:`MarkerTimeoutError` whose message names
        what did arrive (including marker-shaped lines that failed to
        parse).

        It is fine to call this before :meth:`start` (the queue is
        already constructed; the bg thread will start pushing as soon
        as the bootstrap begins printing).
        """
        return self._marker_queue.wait_for(name, timeout_s=timeout_s)

    def wait_for_completion(self, *, timeout_s: float) -> str:
        """Join the background thread and return captured stdout.

        Args:
            timeout_s: Seconds to wait for the bootstrap to finish.
                A board that hangs (e.g. host failed to hit its
                endpoint, board's own deadline is longer than this one)
                surfaces here as :class:`TimeoutError` rather than
                hanging the test process indefinitely.

        Returns:
            The full captured stdout string the bootstrap produced.
            Re-raises any exception the underlying
            ``transport.execute`` raised on the bg thread.

        Raises:
            RunnerNotStartedError: :meth:`start` was never called.
            TimeoutError: The bootstrap did not complete within
                *timeout_s* seconds.
        """
        if self._thread is None:
            raise RunnerNotStartedError(
                "wait_for_completion() called before start().",
            )
        self._thread.join(timeout=timeout_s)
        if self._thread.is_alive():
            raise TimeoutError(
                f"Device bootstrap did not finish within {timeout_s:.3f}s",
            )
        if self._error is not None:
            raise self._error
        assert self._captured_output is not None
        return self._captured_output

    def shutdown(self, *, timeout_s: float | None = None) -> None:
        """Best-effort join the bg thread.  Idempotent; safe to call any time.

        Does not interrupt the bootstrap.  The board is expected to
        carry its own deadline and exit on its own.

        Args:
            timeout_s: Optional bound on the join.  ``None`` (default)
                joins without timeout, which is fine when the bg thread
                is known to have completed (after a successful
                :meth:`wait_for_completion`).  Pass a finite value to
                give up after that many seconds, useful on the
                cleanup path after a host-side abort where the bg
                thread is still mid-execute and would otherwise block
                until the board's own deadline expires.  A timed-out
                join keeps the thread handle so a later call can reap
                it (e.g. after the transport is closed and the blocked
                read fails fast); an unreaped daemon thread dies at
                interpreter exit.
        """
        thread = self._thread
        if thread is None:
            return
        if thread.is_alive():
            thread.join(timeout=timeout_s)
            if thread.is_alive():
                return
        self._thread = None

    def __enter__(self) -> DeviceBootstrapRunner:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.shutdown()

    def _run(self) -> None:
        """Background-thread body.  Calls transport.execute with the marker
        dispatcher wired to on_line, captures stdout and any error."""

        def on_line(line: str) -> None:
            self._marker_queue.offer_line(line)

        try:
            if isinstance(self._bootstrap, list):
                # Chunked CP RAM-mode bootstrap; cast to the extended
                # protocol so the type checker sees execute_scripts.
                extended_transport = self._transport
                assert isinstance(extended_transport, ExtendedTransportProtocol)
                self._captured_output = extended_transport.execute_scripts(
                    self._bootstrap, on_line=on_line,
                )
            else:
                self._captured_output = self._transport.execute(
                    self._bootstrap, on_line=on_line,
                )
        except BaseException as error:
            # Stash any exception for wait_for_completion to re-raise on
            # the main thread; otherwise a transport failure on the bg
            # thread would silently disappear.
            self._error = error
            # An empty captured-stdout placeholder so wait_for_completion's
            # assertion holds if the caller swallows the re-raise.
            if self._captured_output is None:
                self._captured_output = ""
