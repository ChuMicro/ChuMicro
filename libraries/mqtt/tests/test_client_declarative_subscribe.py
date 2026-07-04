"""mqtt client: subscribe() as a declaration valid before connect.

``subscribe()`` records the topic in the desired subscription set in any
state; the first CONNACK's replay path puts it on the wire.  These tests
pin the declarative behavior: a pre-connect declaration reaches the wire
on the first connect and fires ``on_subscribe`` once, a self-heal replay
re-sends but stays callback-silent, the session-present gate applies to a
pre-connect declaration exactly as to a post-connect subscribe, and a
pre-connect unsubscribe retracts before any wire traffic.
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
    """Hand back successive scripted ``FakeSocketConnector``s (dns_ok, tcp_ok)."""
    iterator = iter(socks)

    def factory():
        return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=next(iterator))

    return factory


def test_pre_connect_declaration_sent_on_first_connack():
    # subscribe() before connect() puts nothing on the wire; the first
    # CONNACK's replay sends exactly one SUBSCRIBE and the SUBACK fires
    # the declared on_subscribe once.
    sock = FakeSocket()
    ticks = FakeTicks()
    sock.enqueue_recv(canned_connack_bytes(return_code=0))
    client = new_client(sock, ticks)

    granted = []
    client.subscribe(
        "commands/+", qos=1,
        on_subscribe=lambda topic, qos: granted.append((topic, qos)),
    )
    assert bytes(sock.sent) == b""  # declaration only — nothing on the wire

    client.connect()
    drive(client, ticks, count=1)  # CONNACK -> CONNECTED + replay enqueued
    assert client.state == ProtocolState.CONNECTED
    sock.sent = bytearray()  # drop the CONNECT bytes; watch the replay next
    drive(client, ticks, count=2)  # flush the replayed SUBSCRIBE
    wire = bytes(sock.sent)
    assert wire[0] == _SUBSCRIBE_CONTROL_BYTE[0]  # SUBSCRIBE at head
    assert wire.count(_SUBSCRIBE_CONTROL_BYTE) == 1  # exactly one, for one topic
    assert b"commands/+" in wire

    sock.enqueue_recv(canned_suback_bytes(packet_id=1, granted_qos=1))
    drive(client, ticks, count=1)
    assert granted == [("commands/+", [1])]  # on_subscribe fired once


def test_declaration_replay_on_self_heal_is_callback_silent():
    # A declared subscription fires on_subscribe once (on the first
    # CONNACK's replay); a later self-heal reconnect re-sends the
    # SUBSCRIBE but the one-shot is cleared, so the replay stays silent.
    ticks = FakeTicks()
    sock_one = FakeSocket()
    sock_two = FakeSocket()
    sock_one.enqueue_recv(canned_connack_bytes(return_code=0))
    sock_two.enqueue_recv(canned_connack_bytes(return_code=0))

    client = MQTTClient(
        transport_factory=_factory(sock_one, sock_two),
        client_id="declare-heal",
        ticks=ticks,
    )
    fires = []
    client.subscribe(
        "cmd/+", qos=1,
        on_subscribe=lambda topic, qos: fires.append((topic, qos)),
    )
    client.connect()
    drive(client, ticks, count=3)  # transport up -> CONNECTED -> replay sent
    assert client.state == ProtocolState.CONNECTED
    assert _SUBSCRIBE_CONTROL_BYTE in bytes(sock_one.sent)

    sock_one.enqueue_recv(canned_suback_bytes(packet_id=1, granted_qos=1))
    drive(client, ticks, count=1)
    assert fires == [("cmd/+", [1])]  # first SUBACK fires the one-shot

    # Force a self-heal reconnect onto sock_two (clean_session default
    # resets the packet-id pool, so the replay is packet_id 1 again).
    client.state = ProtocolState.FAILED
    drive(client, ticks, count=3)
    assert client.state == ProtocolState.CONNECTED
    assert _SUBSCRIBE_CONTROL_BYTE in bytes(sock_two.sent)  # replayed

    sock_two.enqueue_recv(canned_suback_bytes(packet_id=1, granted_qos=1))
    drive(client, ticks, count=1)
    assert fires == [("cmd/+", [1])]  # replay's SUBACK stayed silent


def test_session_present_skips_replay_for_pre_connect_declaration():
    # A pre-connect declaration participates in the session-present gate
    # exactly like a post-connect subscribe: when the reconnect CONNACK
    # claims session-present=1 the broker resumed our subscription, so
    # the replay is skipped.
    ticks = FakeTicks()
    sock_one = FakeSocket()
    sock_two = FakeSocket()
    sock_one.enqueue_recv(canned_connack_bytes(return_code=0))
    sock_two.enqueue_recv(
        canned_connack_bytes(return_code=0, session_present=True),
    )

    client = MQTTClient(
        transport_factory=_factory(sock_one, sock_two),
        client_id="declare-resume",
        clean_session=False,
        ticks=ticks,
    )
    client.subscribe("sensors/+", qos=1)  # pre-connect declaration
    client.connect()
    drive(client, ticks, count=3)
    assert client.state == ProtocolState.CONNECTED
    sock_one.enqueue_recv(canned_suback_bytes(packet_id=1, granted_qos=1))
    drive(client, ticks, count=1)

    client.state = ProtocolState.FAILED
    drive(client, ticks, count=3)
    assert client.state == ProtocolState.CONNECTED
    assert _SUBSCRIBE_CONTROL_BYTE not in bytes(sock_two.sent)  # replay skipped


def test_pre_connect_unsubscribe_retracts_before_wire():
    # Declare two topics, retract one before connect: only the surviving
    # declaration is replayed onto the wire on the first CONNACK.
    sock = FakeSocket()
    ticks = FakeTicks()
    sock.enqueue_recv(canned_connack_bytes(return_code=0))
    client = new_client(sock, ticks)

    client.subscribe("keep/+", qos=1)
    client.subscribe("drop/+", qos=1)
    client.unsubscribe("drop/+")  # retract before any wire traffic
    assert bytes(sock.sent) == b""

    client.connect()
    drive(client, ticks, count=1)
    assert client.state == ProtocolState.CONNECTED
    sock.sent = bytearray()
    drive(client, ticks, count=2)  # flush the replayed SUBSCRIBE(s)
    wire = bytes(sock.sent)
    assert wire.count(_SUBSCRIBE_CONTROL_BYTE) == 1  # only the survivor
    assert b"keep/+" in wire
    assert b"drop/+" not in wire
