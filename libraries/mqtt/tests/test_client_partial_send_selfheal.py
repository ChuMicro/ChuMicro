"""mqtt client: a partial send from a dead socket is not replayed (A6).

Negative-suite A6 — broker FIN mid-``_drain_tx_queue`` with a partial
send in flight.  The failure mode the suite names: ``_partial_send =
(packet, offset)`` captured against the dead socket gets flushed onto the
*new* socket after self-heal, so the broker sees a garbage prefix and
resets.

``_reset_transient_state`` (run on every self-heal) nulls
``_partial_send``, so the orphaned tail is dropped and the recovered
connection opens clean with a fresh CONNECT.  This pins that: the new
socket must never carry the dead socket's unsent tail.

The board bake times the kill against a real partial send; this fake
manufactures the partial deterministically with a socket whose one armed
``send`` reports a short write.
"""

from chumicro_mqtt import MQTTClient, ProtocolState
from chumicro_mqtt.testing import canned_connack_bytes, drive
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_timing.testing import FakeTicks

# A distinctive topic + payload so the orphaned tail is unmistakable if
# it ever leaks onto the recovery socket.
_ORPHAN_TOPIC = "orphan/mid-send"
_ORPHAN_PAYLOAD = b"TAIL-TAIL-TAIL-TAIL"


class _ArmablePartialSocket(FakeSocket):
    """FakeSocket whose next ``send`` (once armed) writes only one byte.

    The connect handshake uses ordinary full-write sends; arming after
    CONNECTED makes exactly the following publish land partially, leaving
    ``_partial_send`` pending on this (about-to-die) socket.
    """

    def __init__(self) -> None:
        super().__init__()
        self._armed = False

    def arm_partial(self) -> None:
        self._armed = True

    def send(self, data: bytes) -> int:
        if self._armed:
            self._armed = False
            self._raise_if_closed()
            view = memoryview(data)
            self.sent.extend(view[:1])  # short write: one byte only
            return 1
        return super().send(data)


def _factory(*socks):
    iterator = iter(socks)

    def factory():
        return FakeSocketConnector(
            actions=["dns_ok", "tcp_ok"], socket=next(iterator),
        )

    return factory


class TestPartialSendNotReplayedAfterSelfHeal:
    def test_dead_socket_partial_tail_is_dropped_not_flushed_on_new_socket(self) -> None:
        dead_sock = _ArmablePartialSocket()
        heal_sock = FakeSocket()
        ticks = FakeTicks()
        dead_sock.enqueue_recv(canned_connack_bytes(return_code=0))
        client = MQTTClient(
            transport_factory=_factory(dead_sock, heal_sock),
            client_id="a6-partial",
            ticks=ticks,
        )
        client.connect()
        drive(client, ticks, count=3)
        assert client.state == ProtocolState.CONNECTED

        # Arm the short write, then publish: the packet lands one byte
        # deep and parks in _partial_send against the doomed socket.
        dead_sock.sent = bytearray()
        dead_sock.arm_partial()
        client.publish(_ORPHAN_TOPIC, _ORPHAN_PAYLOAD, qos=0)
        drive(client, ticks, count=1)
        assert client._partial_send is not None  # noqa: SLF001
        assert len(dead_sock.sent) == 1  # only the one-byte prefix reached the wire

        # The socket dies (POLLERR/HUP surfaced by the runner) -> FAILED.
        client.io_error(ticks.ticks_ms(), 0x08)
        assert client.state == ProtocolState.FAILED

        # Self-heal rebuilds onto heal_sock and reconnects.
        heal_sock.enqueue_recv(canned_connack_bytes(return_code=0))
        drive(client, ticks, count=4)
        assert client.state == ProtocolState.CONNECTED

        # The orphaned partial send is gone, and the recovery socket saw
        # a clean CONNECT first — no garbage tail prefixing the stream.
        assert client._partial_send is None  # noqa: SLF001
        recovered = bytes(heal_sock.sent)
        assert recovered[:1] == b"\x10"  # CONNECT control byte leads
        assert _ORPHAN_PAYLOAD not in recovered
        assert _ORPHAN_TOPIC.encode("utf-8") not in recovered
