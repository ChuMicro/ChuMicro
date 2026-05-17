"""Tests for FakeSocket — the in-memory test double."""

from chumicro_sockets.testing import EAGAIN, FakeSocket
from chumicro_test_harness.assertions import raises


class TestSendCapture:
    def test_send_appends_to_sent(self) -> None:
        sock = FakeSocket()
        sock.send(b"hello ")
        sock.send(b"world")
        assert bytes(sock.sent) == b"hello world"

    def test_send_returns_length(self) -> None:
        sock = FakeSocket()
        assert sock.send(b"abc") == 3

    def test_send_accepts_memoryview(self) -> None:
        sock = FakeSocket()
        view = memoryview(b"abcdef")
        assert sock.send(view) == 6
        assert bytes(sock.sent) == b"abcdef"


class TestRecvScripting:
    def test_dequeues_in_order(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(b"first")
        sock.enqueue_recv(b"second")
        buffer = bytearray(16)
        assert sock.recv_into(buffer, 5) == 5
        assert bytes(buffer[:5]) == b"first"
        # Second chunk waits for the next call.
        sock.recv_into(buffer, 16)
        assert bytes(buffer[:6]) == b"second"

    def test_partial_consume_pushes_back_remainder(self) -> None:
        """A short read keeps the unconsumed tail at the head of the queue."""
        sock = FakeSocket()
        sock.enqueue_recv(b"abcdef")
        buffer = bytearray(8)
        nbytes_first = sock.recv_into(buffer, 3)
        assert nbytes_first == 3
        assert bytes(buffer[:3]) == b"abc"
        # The tail "def" should still be in the queue.
        assert sock.pending_recv_chunks == 1
        nbytes_second = sock.recv_into(buffer, 8)
        assert nbytes_second == 3
        assert bytes(buffer[:3]) == b"def"

    def test_empty_queue_returns_zero(self) -> None:
        sock = FakeSocket()
        buffer = bytearray(4)
        assert sock.recv_into(buffer, 4) == 0

    def test_nbytes_zero_uses_buffer_length(self) -> None:
        sock = FakeSocket()
        sock.enqueue_recv(b"abcdef")
        buffer = bytearray(4)
        nbytes_read = sock.recv_into(buffer, 0)
        assert nbytes_read == 4
        assert bytes(buffer) == b"abcd"

    def test_enqueue_rejects_non_bytes(self) -> None:
        sock = FakeSocket()
        with raises(TypeError):
            sock.enqueue_recv("not bytes")  # type: ignore[arg-type]


class TestEAGAINInjection:
    def test_send_eagain_consumes_one_retry(self) -> None:
        sock = FakeSocket()
        sock.enqueue_eagain_for_send(2)
        with raises(OSError) as caught_first:
            sock.send(b"x")
        assert caught_first.value.args[0] == EAGAIN
        with raises(OSError) as caught_second:
            sock.send(b"x")
        assert caught_second.value.args[0] == EAGAIN
        # Third send succeeds — the script is exhausted.
        sock.send(b"x")
        assert bytes(sock.sent) == b"x"

    def test_recv_eagain_consumes_one_retry(self) -> None:
        sock = FakeSocket()
        sock.enqueue_eagain_for_recv(1)
        sock.enqueue_recv(b"hello")
        buffer = bytearray(16)
        with raises(OSError) as caught:
            sock.recv_into(buffer, 16)
        assert caught.value.args[0] == EAGAIN
        # Second call returns the queued chunk.
        nbytes_read = sock.recv_into(buffer, 16)
        assert nbytes_read == 5
        assert bytes(buffer[:5]) == b"hello"


class TestCloseSemantics:
    def test_close_is_idempotent(self) -> None:
        sock = FakeSocket()
        sock.close()
        sock.close()  # no-op, no exception
        assert sock.closed

    def test_send_after_close_raises_ebadf(self) -> None:
        sock = FakeSocket()
        sock.close()
        with raises(OSError) as caught:
            sock.send(b"x")
        # 9 = EBADF, what stdlib uses for "operation on closed fd".
        assert caught.value.args[0] == 9

    def test_recv_after_close_raises_ebadf(self) -> None:
        sock = FakeSocket()
        sock.close()
        buffer = bytearray(4)
        with raises(OSError) as caught:
            sock.recv_into(buffer, 4)
        assert caught.value.args[0] == 9


class TestBlockingFlags:
    def test_setblocking_toggles_state(self) -> None:
        sock = FakeSocket()
        assert sock.blocking is True
        sock.setblocking(False)
        assert sock.blocking is False
        assert sock.timeout == 0.0

    def test_settimeout_none_blocking(self) -> None:
        sock = FakeSocket()
        sock.settimeout(None)
        assert sock.blocking is True
        assert sock.timeout is None

    def test_settimeout_value_non_blocking(self) -> None:
        sock = FakeSocket()
        sock.settimeout(2.5)
        assert sock.blocking is False
        assert sock.timeout == 2.5


class TestFileno:
    def test_default_fileno_is_positive_int(self) -> None:
        sock = FakeSocket()
        assert sock.fileno() > 0

    def test_set_fileno_overrides(self) -> None:
        sock = FakeSocket()
        sock.set_fileno(42)
        assert sock.fileno() == 42
        sock.set_fileno(-1)  # CP-radio-fake convention
        assert sock.fileno() == -1
