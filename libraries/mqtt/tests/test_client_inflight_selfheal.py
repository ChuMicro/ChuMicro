"""mqtt client: QoS-1 in-flight table across a self-heal (A5 / D4, unit half).

The negative suite pins two mirror-image contracts on the in-flight
QoS-1 table when the connection drops and self-heals:

  * clean_session=True (D4 / the safe default): the in-flight table is
    reset on self-heal — the broker forgot the session, so stale entries
    must not linger or leak across the reconnect.
  * clean_session=False (A5): the in-flight table is *preserved* across
    self-heal and its entries redeliver with DUP=1 once their ack
    deadline expires on the recovered connection — the broker resumed the
    persistent session and expects the outstanding publishes again.

Both are hardware-queued on the bake (they need a clean_session harness
toggle + a persistent broker), so this fast unit layer pins the client
mechanism (``MQTTClient._attempt_self_heal`` gating the reset on
``clean_session``) that the bake can't yet reach.  Own file per the
suite-split convention.
"""

from chumicro_mqtt import MQTTClient, ProtocolState
from chumicro_mqtt.testing import canned_connack_bytes, drive
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_timing.testing import FakeTicks

_PAST_ACK_TIMEOUT_MS = 10_000  # ack_timeout defaults to 5 s


def _factory(*socks):
    iterator = iter(socks)

    def factory():
        return FakeSocketConnector(
            actions=["dns_ok", "tcp_ok"], socket=next(iterator),
        )

    return factory


def _connected_with_one_inflight(clean_session, sock_one, sock_two, ticks):
    """Drive a factory-backed client to CONNECTED with one QoS-1 publish
    outstanding (no PUBACK), ready for a forced self-heal."""
    sock_one.enqueue_recv(canned_connack_bytes(return_code=0))
    client = MQTTClient(
        transport_factory=_factory(sock_one, sock_two),
        client_id="inflight-heal",
        clean_session=clean_session,
        ticks=ticks,
    )
    client.connect()
    drive(client, ticks, count=3)
    assert client.state == ProtocolState.CONNECTED
    client.publish("t", b"p", qos=1)
    drive(client, ticks, count=1)
    assert len(client._in_flight) == 1  # noqa: SLF001
    return client


class TestInFlightAcrossSelfHeal:
    def test_clean_session_true_resets_inflight_on_self_heal(self) -> None:
        ticks = FakeTicks()
        sock_one = FakeSocket()
        sock_two = FakeSocket()
        client = _connected_with_one_inflight(True, sock_one, sock_two, ticks)
        assert client._next_packet_id == 2  # noqa: SLF001 - advanced past the publish

        # Force a self-heal.  clean_session=True drops the in-flight table
        # and rewinds the packet-id counter as part of _attempt_self_heal.
        client.state = ProtocolState.FAILED
        sock_two.enqueue_recv(canned_connack_bytes(return_code=0))
        drive(client, ticks, count=4)
        assert client.state == ProtocolState.CONNECTED
        assert client._in_flight == {}  # noqa: SLF001 - reset, not leaked
        assert client._next_packet_id == 1  # noqa: SLF001 - counter rewound

    def test_clean_session_false_preserves_inflight_and_redelivers_dup(self) -> None:
        ticks = FakeTicks()
        sock_one = FakeSocket()
        sock_two = FakeSocket()
        client = _connected_with_one_inflight(False, sock_one, sock_two, ticks)
        packet_id = next(iter(client._in_flight))  # noqa: SLF001

        # Force a self-heal.  clean_session=False keeps the outstanding
        # publish so a session-resuming broker gets it redelivered.  The
        # reconnect CONNACK confirms the resume (session-present=1).
        client.state = ProtocolState.FAILED
        sock_two.enqueue_recv(
            canned_connack_bytes(return_code=0, session_present=True),
        )
        drive(client, ticks, count=4)
        assert client.state == ProtocolState.CONNECTED
        assert packet_id in client._in_flight  # noqa: SLF001 - survived the reconnect

        # Once the ack deadline expires on the recovered connection, the
        # preserved entry redelivers with DUP=1 on the NEW socket.
        sock_two.sent = bytearray()
        ticks.advance(_PAST_ACK_TIMEOUT_MS)
        drive(client, ticks, count=1)
        redelivered = bytes(sock_two.sent)
        assert redelivered, "expected a DUP redelivery on the recovered socket"
        assert redelivered[0] & 0x08  # DUP bit set (MQTT 3.1.1 4.3.2)
        assert redelivered == client._in_flight[packet_id].dup_packet_bytes  # noqa: SLF001
