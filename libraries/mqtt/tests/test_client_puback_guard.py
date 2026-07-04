"""mqtt client: PUBACK-backlog hard-cap guard (fault instead of drop).

Split from ``test_client_backpressure.py`` so each file fits the
unix-lane heap budget (suite-slimming convention).
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


class TestPubackHardCapGuard:
    """A PUBACK owed while the tx queue sits at its structural hard cap
    faults the client to FAILED instead of silently dropping (or
    evicting) a protocol packet.  Interim guard until inbound dispatch
    is rate-converged with the one-send-per-tick drain: self-heal
    rebuilds cleanly, and the broker redelivers whatever was never
    acked, so correctness survives the fault."""

    def _client_at_hard_cap(self, sock, ticks, **overrides):
        """Connected client whose tx queue is filled to the hard cap."""
        sock.enqueue_recv(canned_connack_bytes(return_code=0))
        client = new_client(sock, ticks, max_tx_queue_size=1, **overrides)
        client.connect()
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED
        while client._enqueue_internal_tx(b"\xc0\x00"):  # noqa: SLF001
            pass
        assert len(client._tx_queue) == client._tx_queue_hard_cap  # noqa: SLF001
        return client

    def test_inbound_qos1_puback_faults_at_hard_cap(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = self._client_at_hard_cap(sock, ticks)
        hard_cap = client._tx_queue_hard_cap  # noqa: SLF001

        sock.enqueue_recv(canned_publish_bytes(
            "topic/in", b"hi", qos=1, packet_id=7,
        ))
        client.handle(ticks.ticks_ms())
        assert client.state == ProtocolState.FAILED
        assert "PUBACK backlog" in str(client.last_error)
        # Detected before the appendleft: nothing was evicted from the
        # far end to make room.
        assert len(client._tx_queue) == hard_cap  # noqa: SLF001

    def test_oversized_qos1_puback_faults_at_hard_cap(self) -> None:
        sock = FakeSocket()
        ticks = FakeTicks()
        client = self._client_at_hard_cap(sock, ticks, rx_buffer_size=32)

        # Keep the queue pinned at the cap while the rolling drain runs
        # (each tick's drain attempt hits a scripted EAGAIN).
        sock.enqueue_eagain_for_send(20)
        # 73-byte wire size > 32-byte rx buffer routes through the
        # oversized tier; the topic + packet_id prelude fits, so a
        # PUBACK is still owed once the drain completes.
        sock.enqueue_recv(canned_publish_bytes(
            "abc", b"x" * 64, qos=1, packet_id=9,
        ))
        for _ in range(10):
            drive(client, ticks, count=1)
            if client.state == ProtocolState.FAILED:
                break
        assert client.state == ProtocolState.FAILED
        assert "PUBACK backlog" in str(client.last_error)
