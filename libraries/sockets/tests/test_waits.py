"""Cross-runtime tests for the socket I/O wait markers ReadWait / WriteWait.

Runs on CPython (via pytest), MicroPython and CircuitPython (via
chumicro_test_harness).  Checks the poll-interest each marker reports,
that the optional deadline passes through unchanged (absolute, ignoring
now_ms) and defaults to None, and that one instance is re-yieldable —
repeated reads return stable values so a steady EAGAIN loop reuses it.
"""

from chumicro_runner import IO_READ, IO_WRITE
from chumicro_sockets.testing import FakeSocket
from chumicro_sockets.waits import ReadWait, WriteWait


def test_read_wait_reports_read_interest():
    sock = FakeSocket()
    wait = ReadWait(sock)
    assert wait.io_socket is sock
    assert wait.io_interest(0) == IO_READ


def test_write_wait_reports_write_interest():
    sock = FakeSocket()
    wait = WriteWait(sock)
    assert wait.io_socket is sock
    assert wait.io_interest(0) == IO_WRITE


def test_interest_ignores_now_ms():
    # io_interest reports a fixed poll direction regardless of the tick.
    read_wait = ReadWait(FakeSocket())
    write_wait = WriteWait(FakeSocket())
    assert read_wait.io_interest(0) == read_wait.io_interest(999999) == IO_READ
    assert write_wait.io_interest(0) == write_wait.io_interest(999999) == IO_WRITE


def test_deadline_defaults_to_none():
    # No deadline given, so next_deadline is None and the scheduler parks
    # on the poll indefinitely.
    assert ReadWait(FakeSocket()).next_deadline(0) is None
    assert WriteWait(FakeSocket()).next_deadline(0) is None


def test_deadline_passes_through_as_absolute_tick():
    # The deadline is an absolute ticks_ms value handed back unchanged for
    # any now_ms the scheduler asks with — it does not fold in the clock.
    read_wait = ReadWait(FakeSocket(), deadline_ms=1234)
    write_wait = WriteWait(FakeSocket(), deadline_ms=5678)
    assert read_wait.next_deadline(0) == 1234
    assert read_wait.next_deadline(9999) == 1234
    assert write_wait.next_deadline(0) == 5678


def test_instance_is_re_yieldable():
    # One marker built before an EAGAIN loop and yielded every spin: each
    # read hands back the same socket, interest, and deadline, so a steady
    # loop reuses the instance and allocates nothing.
    sock = FakeSocket()
    wait = ReadWait(sock, deadline_ms=42)
    for now_ms in (0, 10, 20):
        assert wait.io_socket is sock
        assert wait.io_interest(now_ms) == IO_READ
        assert wait.next_deadline(now_ms) == 42
