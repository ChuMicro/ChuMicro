"""mqtt client: the full QoS-1 ack-timeout retry chain (negative-suite A3).

Fake-driven unit layer under the A3 hardware bake (broker drops a single
PUBACK).  The bake proved the eat-acks / publishes-through split on real
hardware; these tests pin the *client* half so a future change can't
silently regress it:

  PUBACK withheld -> ack deadline expires -> DUP=1 retransmit bytes on
  the wire (byte-identical to the original save bit 3) -> retry-limit
  exhaustion -> FAILED with a meaningful ``last_error`` and a drained
  in-flight table (no leak).

Plus the recovery branch the bake's ``drop-puback off`` models: a PUBACK
that finally arrives after a DUP retransmit clears the in-flight entry
and fires the delivery callback exactly once.

Own file per the suite-split convention (``test_client_publish_subscribe``
and ``test_client_error_paths`` are at their heap budget; each pins one
link of this chain in isolation — the DUP bit, the retry-limit fault —
but not the end-to-end sequence with byte-level and leak assertions).
"""

from chumicro_mqtt import ProtocolState
from chumicro_mqtt.testing import (
    canned_connack_bytes,
    canned_puback_bytes,
    drive,
    new_client,
)
from chumicro_sockets.testing import FakeSocket
from chumicro_timing.testing import FakeTicks

# ack_timeout defaults to 5 s in new_client; one jump clears any deadline.
_PAST_ACK_TIMEOUT_MS = 10_000


def _connected_client(sock, ticks, **overrides):
    client = new_client(sock, ticks, **overrides)
    sock.enqueue_recv(canned_connack_bytes(return_code=0))
    client.connect()
    drive(client, ticks, count=2)
    assert client.state == ProtocolState.CONNECTED
    return client


class TestQos1RetryChain:
    def test_withheld_puback_dups_then_exhausts_retry_limit(self) -> None:
        # publish_retry_max=2: two DUP retransmits, then the third
        # ack-timeout with retry_count==max faults the client.
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks, publish_retry_max=2)

        client.publish("temp", b"42", qos=1)
        drive(client, ticks, count=1)  # original PUBLISH on the wire
        packet_id = next(iter(client._in_flight))  # noqa: SLF001
        assert client._in_flight[packet_id].retry_count == 0  # noqa: SLF001

        # No PUBACK ever comes.  Each ack-timeout arms one DUP retransmit
        # until the retry budget is spent.
        for expected_retry in (1, 2):
            sock.sent = bytearray()  # isolate this expiry's wire bytes
            ticks.advance(_PAST_ACK_TIMEOUT_MS)
            drive(client, ticks, count=1)
            retransmit = bytes(sock.sent)
            assert retransmit, "expected a DUP retransmit on this expiry"
            assert retransmit[0] & 0x08  # DUP bit (MQTT 3.1.1 4.3.2)
            assert client.state == ProtocolState.CONNECTED
            assert client._in_flight[packet_id].retry_count == expected_retry  # noqa: SLF001

        # Third expiry: retry_count(2) >= publish_retry_max(2) -> FAILED,
        # the in-flight entry is dropped (no forever-leak), and the error
        # names the packet and the limit it blew.
        ticks.advance(_PAST_ACK_TIMEOUT_MS)
        drive(client, ticks, count=1)
        assert client.state == ProtocolState.FAILED
        assert client._in_flight == {}  # noqa: SLF001 - drained, not leaked
        message = str(client.last_error)
        assert "exceeded retry limit" in message
        assert str(packet_id) in message

    def test_dup_retransmit_is_byte_identical_except_the_dup_bit(self) -> None:
        # The retransmit must carry the same packet_id, topic, and payload
        # as the original — only bit 3 of byte 0 differs — so the broker
        # deduplicates it against the original QoS-1 delivery.
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks, publish_retry_max=3)

        client.publish("sensors/temp", b"payload-bytes", qos=1)
        drive(client, ticks, count=1)
        packet_id = next(iter(client._in_flight))  # noqa: SLF001
        original = client._in_flight[packet_id].packet_bytes  # noqa: SLF001

        sock.sent = bytearray()
        ticks.advance(_PAST_ACK_TIMEOUT_MS)
        drive(client, ticks, count=1)
        retransmit = bytes(sock.sent)

        expected = bytearray(original)
        expected[0] |= 0x08  # set DUP, leave every other byte untouched
        assert retransmit == bytes(expected)

    def test_eventual_puback_after_dup_clears_inflight_and_fires_callback(self) -> None:
        # The A3 recovery branch (the bake's ``drop-puback off``): a PUBACK
        # that lands after a retransmit still matches the surviving
        # in-flight entry by packet_id, clears it, and fires the delivery
        # callback exactly once — the client recovers without faulting.
        sock = FakeSocket()
        ticks = FakeTicks()
        client = _connected_client(sock, ticks, publish_retry_max=3)

        delivered = []
        client.publish(
            "temp", b"42", qos=1,
            on_publish=lambda topic, payload: delivered.append((topic, payload)),
        )
        drive(client, ticks, count=1)
        packet_id = next(iter(client._in_flight))  # noqa: SLF001

        ticks.advance(_PAST_ACK_TIMEOUT_MS)
        drive(client, ticks, count=1)  # DUP retransmit goes out
        assert client._in_flight[packet_id].retry_count == 1  # noqa: SLF001
        assert delivered == []  # not delivered until the ack lands

        sock.enqueue_recv(canned_puback_bytes(packet_id))
        drive(client, ticks, count=1)
        assert client._in_flight == {}  # noqa: SLF001 - cleared by the ack
        assert delivered == [("temp", b"42")]  # fired exactly once
        assert client.state == ProtocolState.CONNECTED
        assert client.last_error is None
