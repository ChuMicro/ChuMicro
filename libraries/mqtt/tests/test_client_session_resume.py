"""mqtt client: CONNACK session-present honoring on self-heal reconnect.

With clean_session=False the broker may resume our prior session.  When
the reconnect CONNACK confirms it (session-present=1) the subscription
replay is skipped; when it does not (session-present=0) the replay
restores the inbound stream.
"""

from chumicro_mqtt import (
    MQTTClient,
    ProtocolState,
)
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_suback_bytes,
    drive,
)
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_timing.testing import FakeTicks


def _transport_factory(*socks):
    """Hand back successive scripted ``FakeSocketConnector``s (dns_ok, tcp_ok)."""
    iterator = iter(socks)

    def factory():
        return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=next(iterator))

    return factory


def _connected_subscribed(session_present):
    """Drive a clean_session=False client to CONNECTED with one subscription,
    then force a self-heal reconnect whose CONNACK carries *session_present*.

    Returns the recovery socket so the caller can assert on its wire bytes.
    """
    ticks = FakeTicks()
    sock_one = FakeSocket()
    sock_two = FakeSocket()
    sock_one.enqueue_recv(canned_connack_bytes(return_code=0))
    sock_two.enqueue_recv(
        canned_connack_bytes(return_code=0, session_present=session_present),
    )

    client = MQTTClient(
        transport_factory=_transport_factory(sock_one, sock_two),
        client_id="resume-test",
        clean_session=False,
        ticks=ticks,
    )
    client.connect()
    drive(client, ticks, count=3)
    client.subscribe("sensors/+", qos=1)
    drive(client, ticks, count=1)
    sock_one.enqueue_recv(canned_suback_bytes(packet_id=1, granted_qos=1))
    drive(client, ticks, count=1)

    client.state = ProtocolState.FAILED
    drive(client, ticks, count=3)
    assert client.state == ProtocolState.CONNECTED
    return sock_two


def test_session_present_skips_replay_when_not_clean():
    # session-present=1 means the broker resumed our subscriptions, so
    # the reconnect must NOT re-issue them.
    sock_two = _connected_subscribed(session_present=True)
    assert b"\x82" not in bytes(sock_two.sent)  # 0x82 = SUBSCRIBE control byte


def test_no_session_present_replays_when_not_clean():
    # session-present=0 means the broker did NOT keep our state, so the
    # replay must still restore the subscription — the honest counterpart.
    sock_two = _connected_subscribed(session_present=False)
    assert b"\x82" in bytes(sock_two.sent)
