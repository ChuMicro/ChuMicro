"""mqtt client: publish fate across a wifi-level outage (B2, unit half).

The 2026-07-05 wifi-recovery bake (workstream B2) left an open
observation: across a router-reboot outage, some publishes were
*dropped* at reconnect while others *flushed* in a burst right after
CONNACK.  The instrumented follow-up run resolved it — the fate of a
publish is decided by the client state it was issued in, not by whether
the outage was wifi-level or mqtt-level:

  * Issued while ``CONNECTED`` (the client hasn't detected the dropped
    link yet): the QoS-1 publish opens an ``_in_flight`` entry sent on
    the doomed socket.  It is never acked, and a ``clean_session=True``
    self-heal *resets* the in-flight table (``_attempt_self_heal``), so
    the publish is dropped — standard clean-session semantics, not a
    pre-connect-queue loss.
  * Issued while ``FAILED`` / ``AWAITING_TRANSPORT`` (the client has
    detected the drop): the publish buffers in the bounded pre-connect
    queue and *flushes* on the reconnect CONNACK
    (``_drain_pre_connect_queue``).

On the bake the two categories were split by the starvation anomaly:
a substrate-blocked tick loop kept the client from ticking, so it stayed
CONNECTED far past the physical link drop and more publishes piled into
``_in_flight`` (dropped) instead of the pre-connect queue (flushed).
This file pins the fork itself at the fake-driven layer so the "dropped
vs flushed" contract the bake proved can't silently regress.  Own file
per the suite-split convention; the mirror-image clean_session=False
preserve path lives in ``test_client_inflight_selfheal``.
"""

from chumicro_mqtt import MQTTClient, ProtocolState
from chumicro_mqtt.testing import canned_connack_bytes, drive
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector
from chumicro_timing.testing import FakeTicks


def _factory(*socks):
    iterator = iter(socks)

    def factory():
        return FakeSocketConnector(
            actions=["dns_ok", "tcp_ok"], socket=next(iterator),
        )

    return factory


def _connect_to(sock_one, *rest, ticks, clean_session=True):
    """Factory-backed client driven to CONNECTED on *sock_one*.

    *rest* are the sockets successive self-heal attempts pick up.
    """
    sock_one.enqueue_recv(canned_connack_bytes(return_code=0))
    client = MQTTClient(
        transport_factory=_factory(sock_one, *rest),
        client_id="b2-outage",
        clean_session=clean_session,
        ticks=ticks,
    )
    client.connect()
    drive(client, ticks, count=3)
    assert client.state == ProtocolState.CONNECTED
    return client


class TestPublishFateAcrossWifiOutage:
    def test_inflight_publish_is_dropped_on_clean_session_self_heal(self) -> None:
        """A publish that raced the drop (issued while CONNECTED) is lost.

        It opens an in-flight entry on the doomed socket; the
        clean_session=True self-heal resets the in-flight table, so the
        publish never reaches the recovered socket.  This is the
        "n=587-589 dropped" half of B2.
        """
        ticks = FakeTicks()
        sock_one, sock_two = FakeSocket(), FakeSocket()
        client = _connect_to(sock_one, sock_two, ticks=ticks)

        # Issued while still CONNECTED (link physically down, undetected):
        # opens an in-flight entry, sent on the doomed socket.
        client.publish("raced", b"in-flight", qos=1)
        drive(client, ticks, count=1)
        assert len(client._in_flight) == 1  # noqa: SLF001
        assert b"raced" in bytes(sock_one.sent)

        # The client detects the dead link and self-heals.
        client.state = ProtocolState.FAILED
        sock_two.enqueue_recv(canned_connack_bytes(return_code=0))
        drive(client, ticks, count=4)
        assert client.state == ProtocolState.CONNECTED

        # Dropped: the in-flight table was reset and the payload never
        # reached the recovered socket.
        assert client._in_flight == {}  # noqa: SLF001
        assert b"raced" not in bytes(sock_two.sent)

    def test_failed_state_publish_flushes_on_reconnect(self) -> None:
        """A publish issued after the drop is detected flushes on CONNACK.

        Once the client is FAILED, publish() buffers into the pre-connect
        queue, which drains on the reconnect CONNACK.  This is the
        "n=590+ flushed in a burst" half of B2.
        """
        ticks = FakeTicks()
        sock_one, sock_two = FakeSocket(), FakeSocket()
        client = _connect_to(sock_one, sock_two, ticks=ticks)

        # Detected drop: subsequent publishes buffer in the pre-connect queue.
        client.state = ProtocolState.FAILED
        client.publish("buffered", b"queued", qos=1)
        assert len(client._pre_connect_queue) == 1  # noqa: SLF001

        sock_two.enqueue_recv(canned_connack_bytes(return_code=0))
        drive(client, ticks, count=4)
        assert client.state == ProtocolState.CONNECTED

        # Flushed: the queue drained and the payload reached the wire.
        assert len(client._pre_connect_queue) == 0  # noqa: SLF001
        assert b"buffered" in bytes(sock_two.sent)

    def test_one_outage_drops_the_raced_publish_but_flushes_the_queued_one(self) -> None:
        """The whole B2 fork in one flow: raced publish dropped, queued one flushed.

        Same outage, same reconnect, opposite fates — decided purely by
        the state each publish was issued in.
        """
        ticks = FakeTicks()
        sock_one, sock_two = FakeSocket(), FakeSocket()
        client = _connect_to(sock_one, sock_two, ticks=ticks)

        # Raced the drop -> in-flight on the doomed socket.
        client.publish("raced", b"lost", qos=1)
        drive(client, ticks, count=1)
        # Drop detected -> next publish buffers in the pre-connect queue.
        client.state = ProtocolState.FAILED
        client.publish("buffered", b"kept", qos=1)

        sock_two.enqueue_recv(canned_connack_bytes(return_code=0))
        drive(client, ticks, count=4)
        assert client.state == ProtocolState.CONNECTED

        recovered = bytes(sock_two.sent)
        assert b"raced" not in recovered   # in-flight publish dropped
        assert b"buffered" in recovered    # pre-connect publish flushed

    def test_connect_from_failed_reconnects_now_with_same_queue_fate(self) -> None:
        """connect() on a FAILED (self-healing) client is "self-heal now".

        The flagship "call mqtt.connect() on wifi CONNECTED" wiring hits
        this on every recovery: the client is FAILED (not DISCONNECTED)
        mid-self-heal.  It no longer raises — connect() is an intent, so
        it triggers the SAME reconnect the timer would, immediately.  And
        the queue fate is byte-identical to a timer-fired self-heal
        (compare the timer path in
        ``test_one_outage_drops_the_raced_publish_but_flushes_the_queued_one``):
        the publish that raced the drop is dropped by the clean_session
        in-flight reset, while the one buffered after the drop flushes on
        the reconnect CONNACK.  Full timer-vs-connect equivalence is
        pinned in ``test_client_connect_intent``.
        """
        ticks = FakeTicks()
        sock_one, sock_two = FakeSocket(), FakeSocket()
        client = _connect_to(sock_one, sock_two, ticks=ticks)

        # Raced the drop -> in-flight on the doomed socket.
        client.publish("raced", b"lost", qos=1)
        drive(client, ticks, count=1)
        assert len(client._in_flight) == 1  # noqa: SLF001

        # Drop detected -> FAILED; next publish buffers in the queue.
        client.state = ProtocolState.FAILED
        client.publish("buffered", b"kept", qos=1)
        assert len(client._pre_connect_queue) == 1  # noqa: SLF001

        # The app knows wifi is back and says so: connect() dials now
        # (no raise, no waiting out backoff).
        sock_two.enqueue_recv(canned_connack_bytes(return_code=0))
        client.connect()
        drive(client, ticks, count=4)
        assert client.state == ProtocolState.CONNECTED

        recovered = bytes(sock_two.sent)
        assert b"raced" not in recovered            # raced in-flight dropped
        assert len(client._pre_connect_queue) == 0  # noqa: SLF001 - queue flushed
        assert b"buffered" in recovered
