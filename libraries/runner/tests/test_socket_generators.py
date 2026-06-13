"""Runner driving generators: ``sleep_until`` plus socket integration.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).  Covers the runner-owned ``sleep_until``
helper directly and end-to-end under ``Runner.add_generator``, then
drives a full connect / send / recv lifecycle through the runner using
the socket helpers that now live in ``chumicro_sockets.generators`` —
proving the scheduler wrapper and the socket helpers compose.
"""

from chumicro_runner import Runner
from chumicro_runner.generators import sleep_until
from chumicro_sockets.generators import connect, recv_until, send_all
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_timing.testing import FakeTicks

# -- sleep_until -----------------------------------------------------


def test_sleep_until_yields_deadline_wait():
    gen = sleep_until(1000)
    first = gen.send(None)
    # The yielded wait carries the absolute deadline the wrapper reads.
    assert first.next_deadline == 1000
    assert getattr(first, "io_socket", None) is None
    try:
        gen.send(0)
    except StopIteration:
        pass
    else:
        raise AssertionError("sleep_until did not return after its single yield")


def test_sleep_until_resumes_after_deadline_under_runner():
    ticks = FakeTicks()
    resumed = []

    def sleeper():
        yield from sleep_until(ticks.ticks_add(ticks.ticks_ms(), 500))
        resumed.append(True)

    runner = Runner(ticks=ticks)
    handle = runner.add_generator(sleeper())

    # Before the deadline the wrapper's check() gate stays closed.
    runner.tick()
    assert not handle.done
    assert resumed == []

    # Advancing past the deadline opens the gate and the generator finishes.
    ticks.advance(500)
    runner.tick()
    assert handle.done
    assert resumed == [True]


# -- Full-stack socket integration through Runner.add_generator ------


def test_connect_handles_yield_from_in_outer_generator():
    # The canonical use site — ``sock = yield from connect(connector)``.
    sock = FakeSocket()
    connector = FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=sock)

    received_sock = []

    def outer():
        result = yield from connect(connector)
        received_sock.append(result)

    runner = Runner(ticks=FakeTicks())
    handle = runner.add_generator(outer())
    while not handle.done:
        runner.tick()

    assert received_sock == [sock]


def test_full_lifecycle_connect_send_recv_under_runner():
    # Drives a complete generator service under the runner — connect
    # advances the connector, send_all writes a probe, recv_until reads
    # the echo.  Verifies the helpers compose end-to-end through
    # Runner.add_generator without manual gen.send plumbing.
    sock = FakeSocket()
    sock.enqueue_recv(b"echo:hello\n")
    connector = FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=sock)
    received = []

    def echo_run():
        connected_sock = yield from connect(connector)
        try:
            yield from send_all(connected_sock, b"hello\n")
            reply = yield from recv_until(connected_sock, b"\n", max_bytes=100)
            received.append(reply)
        finally:
            connected_sock.close()

    runner = Runner(ticks=FakeTicks())
    handle = runner.add_generator(echo_run())
    while not handle.done:
        runner.tick()

    assert bytes(sock.sent) == b"hello\n"
    assert received == [b"echo:hello\n"]
    assert sock.closed is True
