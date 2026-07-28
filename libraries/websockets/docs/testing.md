# Testing Helpers

`chumicro_websockets.testing` ships two in-memory fakes so your tests can drive `WebSocketClient` and `WebSocketServer` end to end without real sockets. The fakes stay on the host: `chumicro-deploy` reads the test-support marker at the top of the module and leaves it out of every device bundle it builds.

For the ticks domain, use `chumicro_timing.testing.FakeTicks` and pass it through the client's or server's `ticks=` argument.

## Usage

### `FakeConnection`

Bidirectional in-memory pipe satisfying the `TCPClientSocket` shape:

```python
from chumicro_timing.testing import FakeTicks
from chumicro_sockets.testing import FakeSocketConnector
from chumicro_websockets import WebSocketClient
from chumicro_websockets.testing import FakeConnection

def test_client_handshake():
    socket = FakeConnection()
    clock = FakeTicks()
    client = WebSocketClient(
        transport_factory=lambda *_args, **_kwargs: FakeSocketConnector(
            actions=["dns_ok", "tcp_ok"], socket=socket,
        ),
        ticks=clock,
    )
    client.connect("ws://example.com/")
    # First two ticks drive the connector; third sends the upgrade request.
    client.handle(clock.ticks_ms())
    client.handle(clock.ticks_ms())
    client.handle(clock.ticks_ms())
    assert b"GET / HTTP/1.1\r\n" in socket.peek_outbound()
```

Inject errors via `raise_on_send` / `raise_on_recv`:

```python
socket = FakeConnection()
socket.raise_on_send = OSError(99, "send dead")
# Next client.handle() that calls send() raises this once, then resets.
```

Cap each `send()` call to simulate partial writes:

```python
socket = FakeConnection()
socket.send_chunk_cap = 16  # at most 16 bytes per send
```

Signal peer-EOF (recv returns 0 instead of EAGAIN):

```python
socket.close_inbound()
```

### `FakeListener`

Stand-in for `chumicro_sockets.listener`:

```python
from chumicro_timing.testing import FakeTicks
from chumicro_websockets import WebSocketServer
from chumicro_websockets.testing import FakeConnection, FakeListener

def test_server_accepts():
    listener = FakeListener()
    peer = FakeConnection()
    listener.queue_accept(peer)
    clock = FakeTicks()
    server = WebSocketServer(
        listener=listener,
        on_connection=lambda conn: None,
        ticks=clock,
    )
    server.handle(clock.ticks_ms())  # accepts the queued peer
    assert server.connection_count == 1
```

### Ticks domain

For ticks-domain fakes use `chumicro_timing.testing.FakeTicks`.  `clock.advance(ms)` jumps the simulated clock forward to drive timeouts, auto-ping cadences, and pong-overdue watchdogs:

```python
from chumicro_sockets.testing import FakeSocketConnector
from chumicro_timing.testing import FakeTicks
from chumicro_websockets import WebSocketClient
from chumicro_websockets.testing import FakeConnection

clock = FakeTicks()
client = WebSocketClient(
    transport_factory=lambda *_args, **_kwargs: FakeSocketConnector(
        actions=["dns_ok", "tcp_ok"], socket=FakeConnection(),
    ),
    handshake_timeout_ms=1000,
    ticks=clock,
)
client.connect("ws://example.com/")
clock.advance(2000)  # past the handshake deadline
client.handle(clock.ticks_ms())
# Client now CLOSED with WebSocketTimeoutError.
```

## Client and server loopback

Two `FakeConnection` objects and a byte pump give you a full client-to-server round trip in one process. Each pass hands both sides a tick, then moves whatever they wrote into the other's inbound queue:

```python
from chumicro_sockets.testing import FakeSocketConnector
from chumicro_timing.testing import FakeTicks
from chumicro_websockets import WebSocketClient, WebSocketServer, WebSocketState
from chumicro_websockets.testing import FakeConnection, FakeListener

def pump(client_socket, server_socket):
    server_socket.feed_inbound(client_socket.read_outbound())
    client_socket.feed_inbound(server_socket.read_outbound())

def test_handshake_loopback():
    clock = FakeTicks()
    client_socket = FakeConnection()
    server_socket = FakeConnection()
    listener = FakeListener()
    listener.queue_accept(server_socket)

    server = WebSocketServer(
        listener=listener,
        on_connection=lambda conn: None,
        ticks=clock,
    )
    client = WebSocketClient(
        transport_factory=lambda *_args, **_kwargs: FakeSocketConnector(
            actions=["dns_ok", "tcp_ok"], socket=client_socket,
        ),
        ticks=clock,
    )

    client.connect("ws://example.com/")
    for _tick in range(50):
        client.handle(clock.ticks_ms())
        server.handle(clock.ticks_ms())
        pump(client_socket, server_socket)
        if client.state == WebSocketState.OPEN:
            break

    assert client.state == WebSocketState.OPEN
    assert server.connection_count == 1
```

Keep pumping the same way past the handshake and the pair carries text, binary, ping/pong, and the close handshake, all without a real socket.

## Using these fakes in your own tests

Install `chumicro-websockets` and import the fakes straight into your test suite:

```python
from chumicro_timing.testing import FakeTicks
from chumicro_websockets.testing import FakeConnection, FakeListener
```

Project convention: libraries that expose injectable services ship their own test fakes alongside the production code.

## API Reference

::: chumicro_websockets.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets) · \
[PyPI](https://pypi.org/project/chumicro-websockets/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
