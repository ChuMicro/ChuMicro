"""Socket-generator helpers — connect / send_all / recv_until / recv_exact.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).  Drives each helper directly (``gen.send``
+ ``gen.throw``) so assertions hit the helper's own logic rather than
the scheduler wrapper that drives it.

The wrapper's resume value (what ``handle()`` ``.send()``-s back into
the generator) is ``now_ms``.  ``connect`` threads it into
``connector.tick(now_ms)``; ``send_all`` / ``recv_until`` /
``recv_exact`` ignore it.  Tests drive with ``gen.send(0)`` as the
resume convention.
"""

import errno

from chumicro_runner import IO_READ, IO_WRITE
from chumicro_sockets.generators import connect, recv_exact, recv_until, send_all
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_test_harness import raises

# -- connect ---------------------------------------------------------


def test_connect_returns_socket_when_connector_reaches_ready():
    sock = FakeSocket()
    connector = FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=sock)
    gen = connect(connector)

    # Prime: connector ticks dns_ok -> awaiting_tcp, yields the connector.
    first = gen.send(None)
    assert first is connector

    # Resume; connector ticks tcp_ok -> ready, gen returns the sock.
    try:
        gen.send(0)
    except StopIteration as stop:
        assert stop.value is sock
    else:
        raise AssertionError("connect did not return after tcp_ok")


def test_connect_yields_the_connector_for_wrapper_inspection():
    # The wrapper reads io_socket / io_interest off whatever was yielded;
    # the connector exposes those natively, so yielding the connector is
    # the duck-typed handoff.
    sock = FakeSocket()
    connector = FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=sock)
    gen = connect(connector)

    first = gen.send(None)
    # The yielded object must be the connector itself — the wrapper
    # reads its io_* attributes for poll registration.
    assert first is connector
    assert hasattr(first, "io_socket")
    assert hasattr(first, "io_interest")


def test_connect_raises_when_connector_fails():
    connector = FakeSocketConnector(actions=["fail:dns refused"])
    gen = connect(connector)
    with raises(OSError):
        gen.send(None)


def test_connect_cancel_via_close_calls_connector_cancel():
    # GeneratorExit (from gen.close()) must reach the finally so the
    # in-flight connector is cancelled — otherwise an abandoned connect
    # leaks its socket.
    connector = FakeSocketConnector(actions=["dns_ok"])  # stops at awaiting_tcp
    gen = connect(connector)
    gen.send(None)  # advance to first yield

    gen.close()  # consumer aborts
    assert connector.state == "failed"
    assert connector.last_error is not None


class _FakeTicks:
    """Hand-driven tick source: each ``ticks_ms`` reads the next scripted value.

    ``ticks_add`` / ``ticks_diff`` are plain arithmetic — the tests stay
    well inside the wrap-safe range, so no masking is needed.
    """

    def __init__(self, readings):
        self._readings = list(readings)
        self._last = self._readings[0] if self._readings else 0

    def ticks_ms(self):
        if self._readings:
            self._last = self._readings.pop(0)
        return self._last

    def ticks_add(self, base, delta):
        return base + delta

    def ticks_diff(self, end, start):
        return end - start


def test_connect_raises_etimedout_when_deadline_elapses():
    # Connector never leaves awaiting_tcp (dns_ok, then no more actions),
    # so the deadline check trips.  Readings: deadline anchor 0 (-> 10),
    # then 5 (still inside), then 20 (past) -> ETIMEDOUT.
    connector = FakeSocketConnector(actions=["dns_ok"])
    ticks = _FakeTicks([0, 5, 20])
    gen = connect(connector, timeout_ms=10, ticks=ticks)

    first = gen.send(None)  # dns_ok -> awaiting_tcp, deadline still ahead
    assert first is connector

    with raises(OSError) as captured:
        gen.send(0)  # stays awaiting_tcp; now past the deadline
    assert captured.value.args[0] == errno.ETIMEDOUT
    # The connector was cancelled so an abandoned connect frees its socket.
    assert connector.state == "failed"
    assert connector.last_error is not None


def test_connect_timeout_requires_ticks():
    connector = FakeSocketConnector(actions=["dns_ok"])
    gen = connect(connector, timeout_ms=10)
    with raises(ValueError):
        gen.send(None)


# -- send_all --------------------------------------------------------


def test_send_all_writes_complete_payload_in_one_pass():
    sock = FakeSocket()
    gen = send_all(sock, b"hello world")
    # No EAGAIN scripted -> single full send, no yields needed; gen returns.
    try:
        gen.send(None)
    except StopIteration:
        pass
    assert bytes(sock.sent) == b"hello world"


def test_send_all_yields_write_wait_on_eagain_then_retries():
    sock = FakeSocket()
    sock.enqueue_eagain_for_send(count=2)  # first two send calls raise EAGAIN
    gen = send_all(sock, b"abc")

    # First yield: EAGAIN -> a wait with io_socket=sock, io_interest == IO_WRITE.
    first = gen.send(None)
    assert first.io_socket is sock
    assert first.io_interest(0) == IO_WRITE

    # Second yield: still EAGAIN, same wait shape.
    second = gen.send(0)
    assert second.io_socket is sock
    assert second.io_interest(0) == IO_WRITE

    # Third resume: send succeeds, gen returns.
    try:
        gen.send(0)
    except StopIteration:
        pass
    assert bytes(sock.sent) == b"abc"


def test_send_all_caches_write_wait_across_yields():
    # Confirms the cache-and-reuse rule the helper docs: a single
    # wait object is reused for every EAGAIN, no per-yield allocation.
    sock = FakeSocket()
    sock.enqueue_eagain_for_send(count=3)
    gen = send_all(sock, b"x")

    waits = []
    while True:
        try:
            waits.append(gen.send(0 if waits else None))
        except StopIteration:
            break

    assert len(waits) == 3
    # All three yields handed back the same instance.
    assert waits[0] is waits[1]
    assert waits[1] is waits[2]


def test_send_all_raises_when_peer_closes_mid_send():
    # send() returning 0 means the peer closed; helper raises OSError so
    # the caller can distinguish from normal short-send.
    class _PeerClosedSock:
        def send(self, data):  # noqa: ARG002
            return 0

    with raises(OSError):
        gen = send_all(_PeerClosedSock(), b"x")
        gen.send(None)


def test_send_all_propagates_non_eagain_oserror():
    class _BrokenSock:
        def send(self, data):  # noqa: ARG002
            raise OSError(errno.ECONNRESET, "connection reset")

    with raises(OSError):
        gen = send_all(_BrokenSock(), b"x")
        gen.send(None)


# -- recv_until ------------------------------------------------------


def test_recv_until_returns_buffer_including_separator():
    sock = FakeSocket()
    sock.enqueue_recv(b"hello\nleftover")
    gen = recv_until(sock, b"\n", max_bytes=100)
    try:
        gen.send(None)
    except StopIteration as stop:
        assert stop.value == b"hello\n"


def test_recv_until_yields_read_wait_on_eagain():
    sock = FakeSocket()
    sock.enqueue_eagain_for_recv(count=2)
    sock.enqueue_recv(b"line\n")
    gen = recv_until(sock, b"\n", max_bytes=100)

    first = gen.send(None)
    assert first.io_socket is sock
    assert first.io_interest(0) == IO_READ

    second = gen.send(0)
    assert second.io_socket is sock
    assert second.io_interest(0) == IO_READ

    try:
        gen.send(0)
    except StopIteration as stop:
        assert stop.value == b"line\n"


def test_recv_until_caches_read_wait_across_yields():
    sock = FakeSocket()
    sock.enqueue_eagain_for_recv(count=3)
    sock.enqueue_recv(b"\n")
    gen = recv_until(sock, b"\n", max_bytes=100)

    waits = []
    while True:
        try:
            waits.append(gen.send(0 if waits else None))
        except StopIteration:
            break

    assert len(waits) == 3
    assert waits[0] is waits[1] is waits[2]


def test_recv_until_raises_when_exceeding_max_bytes():
    sock = FakeSocket()
    sock.enqueue_recv(b"x" * 50)  # 50 bytes, no separator
    gen = recv_until(sock, b"\n", max_bytes=10)
    with raises(OSError):
        gen.send(None)


def test_recv_until_returns_when_separator_within_cap_in_final_chunk():
    # The separator ends at byte 6 (within max_bytes=10) even though the
    # chunk carries trailing bytes past the cap; the message must be
    # returned, not rejected as too-long.
    sock = FakeSocket()
    sock.enqueue_recv(b"hello\ntrailing-bytes-past-cap")
    gen = recv_until(sock, b"\n", max_bytes=10)
    try:
        gen.send(None)
    except StopIteration as stop:
        assert stop.value == b"hello\n"
    else:
        raise AssertionError("recv_until did not return")


def test_recv_until_raises_when_separator_lands_past_cap():
    # The separator is at byte 15, past max_bytes=10 — too long, reject.
    sock = FakeSocket()
    sock.enqueue_recv(b"x" * 15 + b"\n")
    gen = recv_until(sock, b"\n", max_bytes=10)
    with raises(OSError):
        gen.send(None)


def test_recv_until_raises_when_peer_closes_before_separator():
    sock = FakeSocket()
    sock.enqueue_recv(b"partial")
    sock.simulate_peer_close()
    gen = recv_until(sock, b"\n", max_bytes=100)
    with raises(OSError):
        gen.send(None)


def test_recv_until_rejects_non_positive_max_bytes():
    sock = FakeSocket()
    with raises(ValueError):
        recv_until(sock, b"\n", max_bytes=0).send(None)
    with raises(ValueError):
        recv_until(sock, b"\n", max_bytes=-5).send(None)


def test_recv_until_handles_separator_split_across_chunks():
    sock = FakeSocket()
    sock.enqueue_recv(b"first")
    sock.enqueue_recv(b" second\n")
    gen = recv_until(sock, b"\n", max_bytes=100)
    try:
        gen.send(None)
    except StopIteration as stop:
        assert stop.value == b"first second\n"


def test_recv_until_propagates_non_eagain_oserror():
    class _BrokenSock:
        def recv_into(self, buffer):  # noqa: ARG002
            raise OSError(errno.ECONNRESET, "connection reset")

    with raises(OSError):
        recv_until(_BrokenSock(), b"\n", max_bytes=100).send(None)


# -- recv_exact ------------------------------------------------------


def test_recv_exact_returns_exactly_n_bytes_when_available():
    sock = FakeSocket()
    sock.enqueue_recv(b"hello world!!!")
    gen = recv_exact(sock, 5, max_bytes=4096)
    try:
        gen.send(None)
    except StopIteration as stop:
        assert stop.value == b"hello"


def test_recv_exact_loops_across_short_recvs():
    sock = FakeSocket()
    sock.enqueue_recv(b"ab")
    sock.enqueue_recv(b"cd")
    sock.enqueue_recv(b"ef")
    gen = recv_exact(sock, 6, max_bytes=4096)
    try:
        gen.send(None)
    except StopIteration as stop:
        assert stop.value == b"abcdef"


def test_recv_exact_yields_read_wait_on_eagain():
    sock = FakeSocket()
    sock.enqueue_recv(b"ab")
    sock.enqueue_eagain_for_recv(count=1)
    sock.enqueue_recv(b"cd")
    gen = recv_exact(sock, 4, max_bytes=4096)

    first = gen.send(None)
    assert first.io_socket is sock
    assert first.io_interest(0) == IO_READ

    try:
        gen.send(0)
    except StopIteration as stop:
        assert stop.value == b"abcd"


def test_recv_exact_raises_when_peer_closes_before_n_bytes():
    sock = FakeSocket()
    sock.enqueue_recv(b"ab")
    sock.simulate_peer_close()
    gen = recv_exact(sock, 5, max_bytes=4096)
    with raises(OSError):
        gen.send(None)


def test_recv_exact_rejects_non_positive_n():
    sock = FakeSocket()
    with raises(ValueError):
        recv_exact(sock, 0, max_bytes=4096).send(None)
    with raises(ValueError):
        recv_exact(sock, -1, max_bytes=4096).send(None)


def test_recv_exact_rejects_non_positive_max_bytes():
    sock = FakeSocket()
    with raises(ValueError):
        recv_exact(sock, 4, max_bytes=0).send(None)
    with raises(ValueError):
        recv_exact(sock, 4, max_bytes=-1).send(None)


def test_recv_exact_rejects_byte_count_above_max_bytes():
    sock = FakeSocket()
    with raises(ValueError):
        recv_exact(sock, 5000, max_bytes=4096).send(None)


def test_recv_exact_allows_byte_count_equal_to_max_bytes():
    sock = FakeSocket()
    sock.enqueue_recv(b"abcd")
    gen = recv_exact(sock, 4, max_bytes=4)
    try:
        gen.send(None)
    except StopIteration as stop:
        assert stop.value == b"abcd"


def test_recv_exact_propagates_non_eagain_oserror():
    class _BrokenSock:
        def recv_into(self, buffer):  # noqa: ARG002
            raise OSError(errno.ECONNRESET, "connection reset")

    with raises(OSError):
        recv_exact(_BrokenSock(), 4, max_bytes=4096).send(None)
