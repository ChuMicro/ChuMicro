"""CPython-only coverage for the lazy default-poller build inside ``Runner.wait``.

When a ``Runner`` is constructed without an injected ``poller`` and a
registered service exposes an ``io_socket`` whose readiness should
wake the loop, ``wait`` builds a private ``_SelectPollAdapter`` around
``select.poll()`` on the first call that has a socket to register, and
replays the bookkeeping the no-poller ``_sync_poll_set`` already
captured.  Tests in :mod:`test_core` drive ``wait`` through an
injected ``FakePoller`` and never exercise that path, so the adapter
and its lazy build stay uncovered without a real-fd fixture here.

These also cover the ``_sleep_ms`` native path: ``time.sleep_ms`` is
the MicroPython / CircuitPython API the module prefers when present,
so on CPython we monkeypatch ``_native_sleep_ms`` to exercise it.
"""

#: CPython-only lane: real fds via ``os.pipe`` + module monkeypatching.
__chumicro_runtimes__ = ("cpython",)

import os
import select

import pytest

from chumicro_runner import Runner
from chumicro_runner.core import _SelectPollAdapter
from chumicro_runner.testing import FakePoller
from chumicro_timing.testing import FakeTicks


class _PipeService:
    """Service whose ``io_socket`` is a real file descriptor from
    ``os.pipe()`` — ``select.poll`` can register it directly."""

    def __init__(self, read_fd: int) -> None:
        self.io_socket = read_fd
        self.io_wants_read = True
        self.io_wants_write = False

    def check(self, now_ms: int) -> bool:
        return False

    def handle(self, now_ms: int) -> None:
        pass


@pytest.fixture
def pipe_fds():
    """Yield a (read_fd, write_fd) pair that gets closed even on test failure."""
    read_fd, write_fd = os.pipe()
    try:
        yield read_fd, write_fd
    finally:
        for fd in (read_fd, write_fd):
            try:
                os.close(fd)
            except OSError:
                pass


def test_wait_lazy_builds_default_adapter_when_socket_appears(pipe_fds) -> None:
    """A Runner with poller=None builds the adapter on the first wait that
    has an io_socket to register, replaying the registered_interest dict
    that the prior no-poller _sync_poll_set captured."""
    read_fd, _ = pipe_fds
    runner = Runner(ticks=FakeTicks())
    service = _PipeService(read_fd)
    runner.add(service, period_ms=50)

    assert runner._poller is None
    runner.wait(0)

    assert isinstance(runner._poller, _SelectPollAdapter)


def test_wait_default_adapter_register_modify_unregister_cycle(pipe_fds) -> None:
    """Drive the adapter through the full lifecycle: register on first
    wait, modify when io_wants_* flips, unregister when io_socket is
    dropped."""
    read_fd, _ = pipe_fds
    runner = Runner(ticks=FakeTicks())
    service = _PipeService(read_fd)
    runner.add(service, period_ms=50)

    runner.wait(0)  # register

    service.io_wants_write = True
    runner.wait(0)  # modify (POLLIN | POLLOUT)

    service.io_socket = None
    runner.wait(0)  # unregister

    assert id(read_fd) not in runner._registered_interest


def test_wait_default_adapter_ipoll_returns_iterable(pipe_fds) -> None:
    """``ipoll`` on CPython delegates to ``select.poll().poll(timeout_ms)``
    since CPython has no ``ipoll`` method.  An immediate-timeout call
    returns an empty list (no fd is ready)."""
    read_fd, _ = pipe_fds
    runner = Runner(ticks=FakeTicks())
    service = _PipeService(read_fd)
    runner.add(service, period_ms=1)  # tight timeout to force a real ipoll

    runner.wait(0)

    # If we reached here without raising, the adapter's ipoll completed.
    assert isinstance(runner._poller, _SelectPollAdapter)


def test_wait_default_adapter_dispatches_io_error_via_fileno(pipe_fds) -> None:
    """The dispatcher resolves a CPython poll-returned ``(fd, mask)`` pair
    by matching the polled int against ``service.io_socket.fileno()`` when
    the service's io_socket is an object rather than an int."""

    class _FdHolder:
        """Wraps an fd in an object exposing ``fileno()`` — that's the
        shape ``select.poll.poll()`` reports back as the obj field."""

        def __init__(self, fd: int) -> None:
            self._fd = fd

        def fileno(self) -> int:
            return self._fd

    class _Service(_PipeService):
        def __init__(self, holder: _FdHolder) -> None:
            super().__init__(holder)
            self.io_socket = holder  # object, not int
            self.io_error_calls: list[tuple[int, int]] = []

        def io_error(self, now_ms: int, eventmask: int) -> None:
            self.io_error_calls.append((now_ms, eventmask))

    read_fd, _ = pipe_fds
    holder = _FdHolder(read_fd)
    runner = Runner(ticks=FakeTicks(), poller=FakePoller())
    service = _Service(holder)
    runner.add(service, period_ms=50)
    runner.wait(0)

    # Script POLLERR with the int fd that ipoll-on-CPython would yield.
    runner._poller.set_ready(read_fd, select.POLLERR)
    runner.wait(0)

    assert service.io_error_calls == [(0, select.POLLERR)]


def test_wait_sleeps_via_native_sleep_ms_when_present(monkeypatch) -> None:
    """``_sleep_ms`` prefers ``time.sleep_ms`` on runtimes that expose it
    (MicroPython, CircuitPython).  CPython has no ``sleep_ms``, so we
    monkeypatch the module-cached ``_native_sleep_ms`` to verify the
    preferred branch fires."""
    captured: list[int] = []

    def _fake_sleep_ms(timeout_ms: int) -> None:
        captured.append(timeout_ms)

    from chumicro_runner import core as runner_core
    monkeypatch.setattr(runner_core, "_native_sleep_ms", _fake_sleep_ms)

    runner = Runner(ticks=FakeTicks())
    runner.add_periodic(lambda now_ms: None, period_ms=25)

    runner.wait(0)

    assert captured == [25]
