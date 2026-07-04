"""mqtt client: CONNACK session-present under clean_session=True (A7, client half).

Negative-suite A7 covers a stale ``client_id`` collision where a ghost
session's session-present flag could confuse resumption.  The
broker-eviction half is hardware-only, but the *client* half is
fake-expressible: what does the client do when a CONNACK carries
session-present=1 while the client asked for a clean session?

MQTT 3.1.1 [MQTT-3.2.2-1] forbids this — a broker accepting a
clean_session=1 CONNECT MUST set session-present=0.  A broker that sets
it anyway is misbehaving.  These tests PIN THE CURRENT (tolerant)
behavior: the client does not treat the spec-violating flag as terminal,
and — critically — it never lets that flag talk it out of re-subscribing.
With clean_session=True the client always replays its subscription set on
CONNACK regardless of session-present, so a lying broker cannot silently
kill the inbound stream (the A7 "subscriptions silently lost" failure).

NOTE (orchestrator): not a defect — the client's session-present handling
is gated on ``clean_session`` (``client._handle_connack``), so a bogus
flag is inert under a clean session.  Recorded here so a future refactor
that starts honoring session-present unconditionally trips this test.
"""

from chumicro_mqtt import MQTTClient, ProtocolState
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_suback_bytes,
    drive,
    new_client,
)
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_timing.testing import FakeTicks

_SUBSCRIBE_CONTROL_BYTE = b"\x82"  # first byte of a SUBSCRIBE packet


def _factory(*socks):
    iterator = iter(socks)

    def factory():
        return FakeSocketConnector(
            actions=["dns_ok", "tcp_ok"], socket=next(iterator),
        )

    return factory


class TestSessionPresentUnderCleanSession:
    def test_initial_connack_session_present_is_tolerated(self) -> None:
        # A clean-session connect that gets session-present=1 back (a
        # spec violation on the broker's part) still reaches CONNECTED
        # with no error — the client is robust to the misbehaving broker.
        sock = FakeSocket()
        ticks = FakeTicks()
        sock.enqueue_recv(
            canned_connack_bytes(return_code=0, session_present=True),
        )
        client = new_client(sock, ticks, clean_session=True)
        client.connect()
        drive(client, ticks, count=2)
        assert client.state == ProtocolState.CONNECTED
        assert client.last_error is None

    def test_reconnect_replays_subscriptions_despite_session_present(self) -> None:
        # The safety-critical pin: on a clean-session reconnect the client
        # re-issues SUBSCRIBE from its subscription set even when the
        # CONNACK claims session-present=1.  It must not trust that flag
        # to mean "your subscriptions survived" — under clean_session the
        # broker forgot them, so skipping replay would leave inbound dead.
        ticks = FakeTicks()
        sock_one = FakeSocket()
        sock_two = FakeSocket()
        sock_one.enqueue_recv(canned_connack_bytes(return_code=0))
        # The reconnect CONNACK lies: session-present=1 under clean session.
        sock_two.enqueue_recv(
            canned_connack_bytes(return_code=0, session_present=True),
        )

        client = MQTTClient(
            transport_factory=_factory(sock_one, sock_two),
            client_id="a7-clean",
            clean_session=True,
            ticks=ticks,
        )
        client.connect()
        drive(client, ticks, count=3)
        assert client.state == ProtocolState.CONNECTED

        client.subscribe("bake/+/cmd", qos=1)
        drive(client, ticks, count=1)
        sock_one.enqueue_recv(canned_suback_bytes(packet_id=1, granted_qos=1))
        drive(client, ticks, count=1)

        # Force a self-heal reconnect onto sock_two.
        client.state = ProtocolState.FAILED
        drive(client, ticks, count=3)
        assert client.state == ProtocolState.CONNECTED
        # SUBSCRIBE replayed despite the session-present=1 claim.
        assert _SUBSCRIBE_CONTROL_BYTE in bytes(sock_two.sent)
        assert b"bake/+/cmd" in bytes(sock_two.sent)
