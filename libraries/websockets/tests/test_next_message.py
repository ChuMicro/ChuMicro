"""Receive-stream generator — next_message drains a bounded inbound queue.

Cross-runtime: runs on CPython (pytest), MicroPython and CircuitPython
(chumicro_test_harness).  Brings a WebSocketClient to OPEN over a
FakeConnection, feeds server->client frames, and drives next_message
the way the runner would: resume the generator, tick the session to
parse + enqueue, resume again.
"""

import struct

from chumicro_sockets.testing import FakeSocketConnector
from chumicro_timing.testing import FakeTicks
from chumicro_websockets import (
    CLOSE_NORMAL,
    OPCODE_BINARY,
    OPCODE_CLOSE,
    OPCODE_TEXT,
    WebSocketClient,
    WebSocketState,
    derive_accept_key,
)
from chumicro_websockets._session import _InboundWait
from chumicro_websockets._wire import HandshakeRequestParser, encode_frame
from chumicro_websockets.client import ConnectingPhase
from chumicro_websockets.testing import FakeConnection


def _make_open_client(clock, *, max_inbound_queue_size=16):
    """Build a WebSocketClient and drive it to OPEN over a FakeConnection."""
    socket = FakeConnection()

    def factory(host, port, use_tls):  # noqa: ARG001 - fake ignores args
        return FakeSocketConnector(actions=["dns_ok", "tcp_ok"], socket=socket)

    client = WebSocketClient(
        transport_factory=factory,
        ticks=clock,
        max_inbound_queue_size=max_inbound_queue_size,
    )
    client.connect("ws://example.com/")
    while client.state == WebSocketState.CONNECTING and client._connecting_phase in (
        ConnectingPhase.AWAITING_TRANSPORT,
        ConnectingPhase.SENDING_HANDSHAKE,
    ):
        client.handle(clock.ticks_ms())
    request_parser = HandshakeRequestParser()
    request_parser.feed(socket.read_outbound())
    accept_token = derive_accept_key(request_parser.client_key)
    socket.feed_inbound(
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
        b"Sec-WebSocket-Accept: " + accept_token.encode("ascii") + b"\r\n\r\n",
    )
    client.handle(clock.ticks_ms())
    assert client.state == WebSocketState.OPEN
    return client, socket


def _server_frame(opcode, payload):
    """Encode an unmasked server->client frame for inbound feeding."""
    return encode_frame(opcode, payload, fin=True, mask=None)


def _recv_one(client, socket, clock, *, max_steps=20):
    """Drive one next_message() to its return, ticking the session between yields."""
    gen = client.next_message()
    value = None
    for _ in range(max_steps):
        try:
            gen.send(value)
        except StopIteration as stop:
            return stop.value
        client.handle(clock.ticks_ms())
        value = clock.ticks_ms()
    raise AssertionError("next_message did not resolve within max_steps")


# -- happy path ------------------------------------------------------


def test_next_message_returns_text():
    clock = FakeTicks()
    client, socket = _make_open_client(clock)
    socket.feed_inbound(_server_frame(OPCODE_TEXT, b"hello"))
    message = _recv_one(client, socket, clock)
    assert message.is_text is True
    assert message.text == "hello"
    assert message.data is None
    assert "InboundMessage(text=" in repr(message)


def test_next_message_returns_binary():
    clock = FakeTicks()
    client, socket = _make_open_client(clock)
    socket.feed_inbound(_server_frame(OPCODE_BINARY, b"\x00\x01\x02"))
    message = _recv_one(client, socket, clock)
    assert message.is_text is False
    assert message.data == b"\x00\x01\x02"
    assert message.text is None
    assert "bytes" in repr(message)


# -- close returns None ----------------------------------------------


def test_next_message_returns_none_on_clean_close():
    clock = FakeTicks()
    client, socket = _make_open_client(clock)
    socket.feed_inbound(_server_frame(OPCODE_CLOSE, struct.pack("!H", CLOSE_NORMAL) + b"bye"))
    result = _recv_one(client, socket, clock)
    assert result is None
    assert client.state == WebSocketState.CLOSED
    assert client.last_close_code == CLOSE_NORMAL


def test_next_message_returns_none_on_error_close():
    clock = FakeTicks()
    client, socket = _make_open_client(clock)
    socket.close_inbound()  # peer EOF without a CLOSE frame
    result = _recv_one(client, socket, clock)
    assert result is None
    assert client.state == WebSocketState.CLOSED
    assert client.last_error is not None


def test_next_message_drains_queue_before_returning_none():
    # A message queued before the peer's CLOSE is delivered before None.
    clock = FakeTicks()
    client, socket = _make_open_client(clock)
    socket.feed_inbound(
        _server_frame(OPCODE_TEXT, b"first")
        + _server_frame(OPCODE_CLOSE, struct.pack("!H", CLOSE_NORMAL)),
    )
    first = _recv_one(client, socket, clock)
    assert first.text == "first"
    assert _recv_one(client, socket, clock) is None


# -- queue mode + bound ----------------------------------------------


def test_next_message_suppresses_on_text_callback():
    clock = FakeTicks()
    client, socket = _make_open_client(clock)
    fired = []
    client.on_text = lambda text: fired.append(text)
    primer = client.next_message()
    primer.send(None)  # first send flips data delivery to the queue
    socket.feed_inbound(_server_frame(OPCODE_TEXT, b"hello"))
    client.handle(clock.ticks_ms())
    assert fired == []
    assert client._inbound_queue[0].text == "hello"


def test_next_message_queue_drops_oldest_on_overflow():
    clock = FakeTicks()
    client, socket = _make_open_client(clock, max_inbound_queue_size=2)
    primer = client.next_message()
    primer.send(None)  # flip to queue mode before any message arrives
    socket.feed_inbound(
        _server_frame(OPCODE_TEXT, b"m0")
        + _server_frame(OPCODE_TEXT, b"m1")
        + _server_frame(OPCODE_TEXT, b"m2"),
    )
    for _ in range(10):
        client.handle(clock.ticks_ms())
    # Cap is 2, so the oldest (m0) was dropped; m1 and m2 remain in order.
    drained = []
    while client._inbound_queue:
        drained.append(client._inbound_queue.popleft().text)
    assert drained == ["m1", "m2"]


# -- wait shape ------------------------------------------------------


def test_inbound_wait_registers_no_socket():
    # The wait carries no io_socket: the session owns the socket poll
    # (registering it here too would collide with the session's
    # connect-phase write interest); the generator just re-checks the
    # queue each tick.
    wait = _InboundWait()
    assert wait.io_socket is None


def test_next_message_yields_the_no_register_wait():
    clock = FakeTicks()
    client, socket = _make_open_client(clock)
    gen = client.next_message()
    wait = gen.send(None)  # queue empty -> yields the resume-every-tick wait
    assert getattr(wait, "io_socket", None) is None
