"""mqtt client: recv-N-vs-send-1 rate convergence (PUBACK pacing).

A single recv can surface many small QoS-1 PUBLISHes while the drain
sends one packet per tick.  The pacing design keeps the two rates
converged: each tick's PUBACKs coalesce into ONE front-of-queue batch
the drain flushes outside the per-tick packet budget, and the recv is
suppressed while a previous batch is still unsent (TCP-window
backpressure).  Own file per the suite-slimming convention.
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
from chumicro_runner import IO_READ, IO_WRITE
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks

_PUBACK_PREFIX = b"\x40\x02"


def _puback(packet_id):
    return _PUBACK_PREFIX + bytes((packet_id >> 8, packet_id & 0xFF))


class _RecvCountingSocket(FakeSocket):
    """FakeSocket that counts recv_into calls (suppression assertions)."""

    def __init__(self) -> None:
        super().__init__()
        self.recv_calls = 0

    def recv_into(self, buffer: bytearray, nbytes: int = 0) -> int:
        self.recv_calls += 1
        return super().recv_into(buffer, nbytes)


def _connected_client(sock, ticks, **overrides):
    """Build a socket-only client and drive it to CONNECTED."""
    client = new_client(sock, ticks, **overrides)
    sock.enqueue_recv(canned_connack_bytes(return_code=0))
    client.connect()
    drive(client, ticks, count=2)
    assert client.state == ProtocolState.CONNECTED
    return client


class TestCoalescedPubackBatch:
    def test_flood_tick_queues_one_batch_entry_in_receipt_order(self):
        # 20 QoS-1 publishes in one recv used to appendleft 20 queue
        # entries against a one-send-per-tick drain.  Now they coalesce
        # into ONE entry (20 x 4-byte PUBACKs, receipt order), so queue
        # growth per tick is bounded at one entry regardless of the
        # inbound rate.
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks)
        sock.sent = bytearray()  # MP bytearray lacks .clear()
        sock.enqueue_recv(b"".join(
            canned_publish_bytes("t", b"x", qos=1, packet_id=index + 1)
            for index in range(20)
        ))
        # Block the drain this tick so the queued shape is observable.
        sock.enqueue_eagain_for_send(1)
        drive(client, ticks, count=1)
        assert len(client._tx_queue) == 1  # noqa: SLF001
        assert len(client._tx_queue[0]) == 20 * 4  # noqa: SLF001
        assert client._puback_batch_queued  # noqa: SLF001

        # Next tick the socket accepts the batch: every ack lands, in
        # receipt order, and the client never approached the hard cap.
        drive(client, ticks, count=1)
        sent = bytes(sock.sent)
        assert len(sent) == 20 * 4
        previous_index = -1
        for packet_id in range(1, 21):
            position = sent.index(_puback(packet_id))
            assert position > previous_index
            previous_index = position
        assert client.state == ProtocolState.CONNECTED
        assert client.last_error is None

    def test_puback_batch_precedes_queued_user_packet(self):
        # The batch rides at the front of the queue: acks the broker is
        # waiting on beat user publishes onto the wire, and the user
        # packet still drains the SAME tick because the batch send does
        # not consume the packet budget.
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks)
        sock.sent = bytearray()
        client.publish("user/topic", b"payload", qos=0)
        sock.enqueue_recv(canned_publish_bytes("in", b"x", qos=1, packet_id=9))
        drive(client, ticks, count=1)
        sent = bytes(sock.sent)
        assert _puback(9) in sent
        assert b"user/topic" in sent
        assert sent.index(_puback(9)) < sent.index(b"user/topic")


class TestRecvSuppression:
    def test_recv_skipped_while_batch_unsent_then_resumes(self):
        # While the batch can't reach the wire (send EAGAIN) the client
        # stops reading: unread bytes stay in the kernel buffer where
        # the TCP window throttles the broker, instead of piling up
        # acks toward the hard cap.  This also pins cross-tick PUBACK
        # receipt order — a second batch can never queue in front of an
        # unsent first.
        sock = _RecvCountingSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks)
        sock.sent = bytearray()
        sock.enqueue_recv(canned_publish_bytes("a", b"x", qos=1, packet_id=1))
        sock.enqueue_recv(canned_publish_bytes("b", b"y", qos=1, packet_id=2))
        sock.enqueue_eagain_for_send(1)
        drive(client, ticks, count=1)  # reads pid 1, batch blocked on EAGAIN
        calls_after_blocked_tick = sock.recv_calls

        drive(client, ticks, count=1)  # suppressed read; batch flushes
        assert sock.recv_calls == calls_after_blocked_tick  # no recv attempted
        assert not client._puback_batch_queued  # noqa: SLF001

        drive(client, ticks, count=2)  # reads pid 2, acks it
        assert sock.recv_calls > calls_after_blocked_tick
        sent = bytes(sock.sent)
        assert sent.index(_puback(1)) < sent.index(_puback(2))
        assert client.state == ProtocolState.CONNECTED

    def test_io_interest_drops_read_while_suppressed(self):
        # A suppressed tick skips its recv, so advertising read
        # interest would spin the runner against unread bytes.
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks)
        sock.enqueue_recv(canned_publish_bytes("a", b"x", qos=1, packet_id=1))
        sock.enqueue_eagain_for_send(1)
        drive(client, ticks, count=1)
        assert client._puback_batch_queued  # noqa: SLF001
        interest = client.io_interest(ticks.ticks_ms())
        assert not (interest & IO_READ)
        assert interest & IO_WRITE  # still wanted, for the flush

        drive(client, ticks, count=1)  # batch flushes
        assert client.io_interest(ticks.ticks_ms()) & IO_READ  # restored


class TestKeepaliveUnderSustainedInbound:
    def test_pingreq_reaches_wire_during_qos1_flood(self):
        # Every tick carries inbound QoS-1 traffic; the coalesced batch
        # leaves the per-tick packet budget unspent, so the PINGREQ the
        # keepalive check queues still reaches the wire instead of
        # starving behind a perpetual ack backlog.
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks, keep_alive_seconds=2)
        sock.sent = bytearray()
        ticks.advance(1_500)  # past the 1 s half-interval ping mark
        for packet_id in range(1, 5):
            sock.enqueue_recv(canned_publish_bytes(
                "flood", b"x", qos=1, packet_id=packet_id,
            ))
            drive(client, ticks, count=1)
        sent = bytes(sock.sent)
        assert b"\xc0\x00" in sent  # PINGREQ made it out mid-flood
        for packet_id in range(1, 5):
            assert _puback(packet_id) in sent
        assert client.state == ProtocolState.CONNECTED
