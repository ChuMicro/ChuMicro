"""mqtt client: ``_read_inbound`` honors ``recv_budget_per_tick``.

Split from ``test_client_backpressure.py`` (suite-slimming convention).
The 16K-buffer / 8K-payload multi-tick drain test — the mqtt
heap-budget floor — lives alone in
``test_client_bounded_recv_drain.py`` so it runs with as few
co-resident test objects as possible.
"""

from chumicro_mqtt import (
    ProtocolState,
)
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_publish_bytes,
    drive,
    new_client,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks


class _CountingSocket(FakeSocket):
    """FakeSocket that counts bytes received via recv_into.

    Used by the bounded-recv tests to assert per-tick read budget
    is honored without leaking the assertion into FakeSocket itself.
    """

    def __init__(self) -> None:
        super().__init__()
        self.bytes_received_total = 0
        self.bytes_received_per_call: list[int] = []

    def recv_into(self, buffer: bytearray, nbytes: int = 0) -> int:
        got = super().recv_into(buffer, nbytes)
        if got > 0:
            self.bytes_received_total += got
            self.bytes_received_per_call.append(got)
        return got

class TestBoundedRecvPerTick:
    """``_read_inbound`` honors ``recv_budget_per_tick``.

    A 100 KB inbound PUBLISH would otherwise monopolize the tick
    while the kernel TCP buffer drains, and side tasks (LED blink,
    LCD update, control loop) would stutter.
    """

    def _connected_client(self, sock: _CountingSocket, ticks: FakeTicks, **kwargs):
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        client = new_client(sock, ticks, **kwargs)
        client.connect()
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED
        # Reset counters after the CONNACK consume so the budget tests
        # only measure inbound-publish reads.
        sock.bytes_received_total = 0
        sock.bytes_received_per_call.clear()
        return client

    def test_budget_caps_bytes_consumed_per_tick(self) -> None:
        """A single tick cannot consume more than ``recv_budget_per_tick``."""
        sock = _CountingSocket()
        ticks = FakeTicks()
        client = self._connected_client(sock, ticks, recv_budget_per_tick=512)

        # Queue a 4 KB payload in a single chunk.  FakeSocket honors
        # recv_into's *nbytes* cap so we'll consume in pieces.
        big_publish = canned_publish_bytes("topic/a", b"x" * 4096, qos=0)
        sock.enqueue_recv(big_publish)

        client.handle(ticks.ticks_ms())
        assert sock.bytes_received_total <= 512

    def test_default_budget_is_1024_bytes(self) -> None:
        """Default 1024-byte recv budget holds without explicit configuration."""
        sock = _CountingSocket()
        ticks = FakeTicks()
        client = self._connected_client(sock, ticks)  # default budget

        # Stuff a multi-KB blob.  Assert the default 1024-byte cap holds.
        big_publish = canned_publish_bytes("topic/a", b"x" * 8192, qos=0)
        sock.enqueue_recv(big_publish)
        client.handle(ticks.ticks_ms())
        assert sock.bytes_received_total <= 1024

    def test_small_payload_drains_in_a_single_tick(self) -> None:
        """The budget never makes the *easy* case slower."""
        sock = _CountingSocket()
        ticks = FakeTicks()
        client = self._connected_client(sock, ticks, recv_budget_per_tick=1024)

        small = b"hello"
        sock.enqueue_recv(canned_publish_bytes("topic/small", small, qos=0))

        seen: list[bytes] = []
        client.on_message = lambda topic, payload: seen.append(payload)
        client.handle(ticks.ticks_ms())
        assert seen == [small]
