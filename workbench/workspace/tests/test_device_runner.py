"""Unit tests for the background-thread bootstrap runner."""

from __future__ import annotations

import threading
import time

import pytest
from chumicro_deploy.testing import FakeTransport
from chumicro_workspace.device_runner import (
    DeviceBootstrapRunner,
    RunnerNotStartedError,
)
from chumicro_workspace.markers import MarkerTimeoutError


class _SlowFakeTransport:
    """Like FakeTransport but holds execute() open until released.

    The runner is a concurrency primitive, so a few tests need to
    observe state mid-execute (e.g. shutdown idempotency).  A real
    FakeTransport returns synchronously and gives no observation
    window; this stand-in blocks on an Event so the test can poke
    runner state with the bg thread genuinely in-flight.
    """

    mode = "ram"

    def __init__(self, release_event: threading.Event, output: str = "") -> None:
        self._release_event = release_event
        self._output = output
        self.execute_calls: list[str] = []

    def execute(
        self,
        bootstrap_script: str,
        *,
        on_line=None,
    ) -> str:
        self.execute_calls.append(bootstrap_script)
        if on_line is not None and self._output:
            for output_line in self._output.splitlines():
                on_line(output_line)
        # Block until the test signals release.
        self._release_event.wait(timeout=5.0)
        return self._output


class TestDeviceBootstrapRunnerHappyPath:
    """Start, wait_for, wait_for_completion against an immediate-return fake."""

    def test_wait_for_returns_marker_dispatched_during_execute(self) -> None:
        transport = FakeTransport(
            execute_output="SERVER_READY ip=10.0.0.1 port=8080\nPASS test_ok (0.001s)\n",
        )
        runner = DeviceBootstrapRunner(transport, "boot")
        runner.start()

        marker = runner.wait_for("SERVER_READY", timeout_s=2.0)

        assert marker.values == {"ip": "10.0.0.1", "port": "8080"}
        captured = runner.wait_for_completion(timeout_s=2.0)
        assert "PASS test_ok" in captured
        runner.shutdown()

    def test_chunked_bootstrap_routes_to_execute_scripts(self) -> None:
        # A list bootstrap is the CircuitPython RAM-mode shape; runner
        # has to recognise it and call execute_scripts instead.
        transport = FakeTransport(
            execute_output="SERVER_READY ip=10.0.0.1 port=9000\n",
        )
        runner = DeviceBootstrapRunner(transport, ["chunk-a", "chunk-b"])
        runner.start()

        marker = runner.wait_for("SERVER_READY", timeout_s=2.0)
        assert marker.values["port"] == "9000"

        runner.wait_for_completion(timeout_s=2.0)
        # Verify the fake recorded a chunked-execute call rather than
        # an execute call.
        assert any(name == "execute_scripts" for name, _ in transport.calls)
        runner.shutdown()


class TestDeviceBootstrapRunnerErrorPaths:
    """start guards, wait_for_completion timeouts, exception propagation."""

    def test_start_called_twice_raises(self) -> None:
        transport = FakeTransport(execute_output="")
        runner = DeviceBootstrapRunner(transport, "boot")
        runner.start()
        runner.wait_for_completion(timeout_s=1.0)
        with pytest.raises(RuntimeError, match="may only be called once"):
            runner.start()

    def test_wait_for_completion_before_start_raises(self) -> None:
        runner = DeviceBootstrapRunner(FakeTransport(), "boot")
        with pytest.raises(RunnerNotStartedError):
            runner.wait_for_completion(timeout_s=0.1)

    def test_wait_for_completion_times_out_on_slow_bootstrap(self) -> None:
        release = threading.Event()
        transport = _SlowFakeTransport(release_event=release)
        runner = DeviceBootstrapRunner(transport, "boot")
        runner.start()
        try:
            with pytest.raises(TimeoutError, match=r"did not finish within"):
                runner.wait_for_completion(timeout_s=0.1)
        finally:
            release.set()
            runner.shutdown()

    def test_wait_for_completion_reraises_transport_error(self) -> None:
        boom = RuntimeError("device offline")
        transport = FakeTransport(execute_raises=boom)
        runner = DeviceBootstrapRunner(transport, "boot")
        runner.start()
        with pytest.raises(RuntimeError, match="device offline"):
            runner.wait_for_completion(timeout_s=2.0)
        runner.shutdown()

    def test_wait_for_raises_marker_timeout_when_marker_never_arrives(self) -> None:
        # Bootstrap completes silently — no SERVER_READY ever lands.
        transport = FakeTransport(execute_output="PASS test_ok (0.001s)\n")
        runner = DeviceBootstrapRunner(transport, "boot")
        runner.start()
        try:
            with pytest.raises(MarkerTimeoutError, match=r"SERVER_READY"):
                runner.wait_for("SERVER_READY", timeout_s=0.2)
        finally:
            runner.wait_for_completion(timeout_s=2.0)
            runner.shutdown()


class TestDeviceBootstrapRunnerShutdown:
    """Shutdown is idempotent and works as a context-manager hook."""

    def test_shutdown_without_start_is_a_noop(self) -> None:
        runner = DeviceBootstrapRunner(FakeTransport(), "boot")
        runner.shutdown()  # must not raise
        runner.shutdown()  # twice is still fine

    def test_shutdown_after_completion_is_idempotent(self) -> None:
        transport = FakeTransport(execute_output="")
        runner = DeviceBootstrapRunner(transport, "boot")
        runner.start()
        runner.wait_for_completion(timeout_s=1.0)
        runner.shutdown()
        runner.shutdown()  # second call is a no-op

    def test_timed_out_shutdown_keeps_handle_for_later_reap(self) -> None:
        # The deploy_api teardown sequence: a shutdown that gives up on
        # a still-running bootstrap must not discard the thread handle —
        # once the blocker clears (a closed transport failing the read
        # fast), a follow-up shutdown reaps the thread instead of
        # leaving it stale holding the dead transport.
        release = threading.Event()
        transport = _SlowFakeTransport(release_event=release)
        runner = DeviceBootstrapRunner(transport, "boot")
        runner.start()

        runner.shutdown(timeout_s=0.05)  # times out; bootstrap still blocked
        # Reaching into _thread: this test observes the concurrency
        # primitive's internal handle, same rationale as _SlowFakeTransport.
        assert runner._thread is not None and runner._thread.is_alive()

        release.set()  # stands in for disconnect() failing the read fast
        runner.shutdown(timeout_s=2.0)
        assert runner._thread is None

    def test_shutdown_with_timeout_returns_when_thread_still_alive(self) -> None:
        """``shutdown(timeout_s=...)`` bounds the join so the driver
        cleanup path doesn't block on a wedged bg thread."""
        release = threading.Event()
        transport = _SlowFakeTransport(release_event=release)
        runner = DeviceBootstrapRunner(transport, "boot")
        runner.start()
        try:
            start = time.monotonic()
            runner.shutdown(timeout_s=0.1)
            elapsed = time.monotonic() - start
            # Should return within the timeout plus a small fudge
            # rather than block on the slow transport.
            assert elapsed < 1.0
        finally:
            release.set()
            runner.shutdown()  # final join now that the thread can exit

    def test_context_manager_shuts_down_even_on_exception(self) -> None:
        release = threading.Event()
        transport = _SlowFakeTransport(release_event=release)
        captured_runner: DeviceBootstrapRunner | None = None
        with pytest.raises(RuntimeError, match="test-induced failure"):
            with DeviceBootstrapRunner(transport, "boot") as runner:
                captured_runner = runner
                runner.start()
                # Release before the raise so shutdown can join cleanly.
                release.set()
                raise RuntimeError("test-induced failure")
        assert captured_runner is not None
        # After __exit__, the bg thread is joined.
        # (No assertion on internal _thread; the contract is that
        # shutdown doesn't hang or leave a runnable thread behind.)


class TestDeviceBootstrapRunnerMarkerQueueAccess:
    """marker_queue property is exposed for tests/future fixtures."""

    def test_marker_queue_property_returns_the_internal_queue(self) -> None:
        runner = DeviceBootstrapRunner(FakeTransport(), "boot")
        queue_one = runner.marker_queue
        queue_two = runner.marker_queue
        # Same instance; not a fresh queue per access.
        assert queue_one is queue_two

    def test_wait_for_called_before_start_still_works(self) -> None:
        # Some test shapes will instantiate + call wait_for in the same
        # turn the bg thread is meant to start; the queue is already
        # alive at construction time, so a wait_for that times out
        # quickly is the expected shape, not a crash.
        runner = DeviceBootstrapRunner(FakeTransport(), "boot")
        with pytest.raises(MarkerTimeoutError):
            runner.wait_for("READY", timeout_s=0.05)


class TestDeviceBootstrapRunnerConcurrency:
    """Real producer thread + main thread consumer (round-trips through queue.Queue)."""

    def test_marker_arrives_during_execute_and_is_observed_after(self) -> None:
        # FakeTransport's execute dispatches all lines synchronously
        # then returns; with the bg thread, the host sees the marker
        # on the queue regardless of whether wait_for was called before
        # or after the bg thread completes.
        transport = FakeTransport(
            execute_output="SOMETHING_ELSE foo=bar\nSERVER_READY ip=10.0.0.1 port=1234\n",
        )
        runner = DeviceBootstrapRunner(transport, "boot")
        runner.start()
        # Give the bg thread a moment to dispatch.
        time.sleep(0.05)
        marker = runner.wait_for("SERVER_READY", timeout_s=2.0)
        assert marker.values["port"] == "1234"
        runner.wait_for_completion(timeout_s=2.0)
        runner.shutdown()
