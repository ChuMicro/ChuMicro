# Testing Helpers

`chumicro_websockets.testing` holds in-memory stand-ins for the sockets under a WebSocket.  `FakeConnection` replaces one TCP connection, and `FakeListener` replaces the listening socket a `WebSocketServer` accepts connections on.  A test drives a real `WebSocketClient` or `WebSocketServer` over them, with no network and no waiting.  `pip install chumicro-websockets pytest` installs everything the tests on this page import, `chumicro-sockets` and `chumicro-timing` included.  Project deploys and the board bundles leave the module out.

## The smallest test

Save this as `test_ws_handshake.py` and run `pytest test_ws_handshake.py`:

```python
from chumicro_sockets.testing import FakeSocketConnector
from chumicro_timing.testing import FakeTicks
from chumicro_websockets import WebSocketClient
from chumicro_websockets.testing import FakeConnection


def test_client_sends_the_upgrade_request():
    socket = FakeConnection()
    clock = FakeTicks()
    client = WebSocketClient(
        transport_factory=lambda host, port, use_tls: FakeSocketConnector(
            actions=["dns_ok", "tcp_ok"], socket=socket,
        ),
        ticks=clock,
    )

    client.connect("ws://example.com/")
    for _ in range(3):
        client.handle(clock.ticks_ms())

    assert socket.peek_outbound().startswith(b"GET / HTTP/1.1\r\n")
```

The client opens its connection through `transport_factory`.  `FakeSocketConnector` from `chumicro_sockets.testing` finishes the connect in two ticks and hands over the `FakeConnection`.  The third tick writes the upgrade request.  `FakeTicks` from `chumicro_timing.testing` keeps the clock under the test's control.

## `FakeConnection`

| Call or attribute | What it does |
|---|---|
| `feed_inbound(data)` | Queues bytes from the far end for `recv_into()`. |
| `read_outbound()` | Returns the bytes the code under test sent and empties the buffer. |
| `peek_outbound()` | Returns the bytes sent so far and leaves them in place. |
| `close_inbound()` | Plays the far end hanging up: once the inbound bytes run out, `recv_into()` returns `0` in place of raising `EAGAIN`. |
| `raise_on_send`, `raise_on_recv` | An exception to raise from the next `send()` or `recv_into()`, once. |
| `send_chunk_cap` | The most bytes one `send()` takes, for a test of partial writes.  `None` takes everything. |
| `closed` | `True` after `close()`. |

`raise_on_send` breaks the connection mid-handshake:

```python
from chumicro_sockets.testing import FakeSocketConnector
from chumicro_timing.testing import FakeTicks
from chumicro_websockets import WebSocketClient, WebSocketHandshakeError, WebSocketState
from chumicro_websockets.testing import FakeConnection


def test_a_send_error_closes_the_client():
    socket = FakeConnection()
    socket.raise_on_send = OSError(104, "connection reset")
    clock = FakeTicks()
    client = WebSocketClient(
        transport_factory=lambda host, port, use_tls: FakeSocketConnector(
            actions=["dns_ok", "tcp_ok"], socket=socket,
        ),
        ticks=clock,
    )

    client.connect("ws://example.com/")
    for _ in range(3):
        client.handle(clock.ticks_ms())

    assert client.state == WebSocketState.CLOSED
    assert isinstance(client.last_error, WebSocketHandshakeError)
```

`send_chunk_cap` makes the client finish a long write over several ticks:

```python
from chumicro_sockets.testing import FakeSocketConnector
from chumicro_timing.testing import FakeTicks
from chumicro_websockets import WebSocketClient
from chumicro_websockets.testing import FakeConnection


def test_a_capped_socket_still_carries_the_whole_request():
    socket = FakeConnection()
    socket.send_chunk_cap = 16
    clock = FakeTicks()
    client = WebSocketClient(
        transport_factory=lambda host, port, use_tls: FakeSocketConnector(
            actions=["dns_ok", "tcp_ok"], socket=socket,
        ),
        ticks=clock,
    )

    client.connect("ws://example.com/")
    client.handle(clock.ticks_ms())
    client.handle(clock.ticks_ms())
    client.handle(clock.ticks_ms())
    assert len(socket.peek_outbound()) == 16

    for _ in range(20):
        client.handle(clock.ticks_ms())
    assert socket.peek_outbound().endswith(b"\r\n\r\n")
```

`FakeTicks.advance()` reaches a handshake timeout, an automatic ping, or a missing pong without waiting for it:

```python
from chumicro_sockets.testing import FakeSocketConnector
from chumicro_timing.testing import FakeTicks
from chumicro_websockets import WebSocketClient, WebSocketState, WebSocketTimeoutError
from chumicro_websockets.testing import FakeConnection


def test_a_silent_server_times_out_the_handshake():
    clock = FakeTicks()
    client = WebSocketClient(
        transport_factory=lambda host, port, use_tls: FakeSocketConnector(
            actions=["dns_ok", "tcp_ok"], socket=FakeConnection(),
        ),
        handshake_timeout_ms=1000,
        ticks=clock,
    )

    client.connect("ws://example.com/")
    clock.advance(2000)
    client.handle(clock.ticks_ms())

    assert client.state == WebSocketState.CLOSED
    assert isinstance(client.last_error, WebSocketTimeoutError)
```

## `FakeListener`

`FakeListener()` stands in for the listening socket a `WebSocketServer` takes as `listener=`.

| Call or attribute | What it does |
|---|---|
| `queue_accept(peer)` | Queues a `FakeConnection` for the next `accept()`. |
| `accept()` | Returns the next queued connection with the address `("127.0.0.1", 12345)`.  With none queued it raises `OSError(EAGAIN)`. |
| `closed` | `True` after `close()`. |

Two `FakeConnection` objects and a small byte pump connect a real client to a real server in one process.  Each pass ticks both sides, then moves what each wrote into the other's inbound queue:

```python
from chumicro_sockets.testing import FakeSocketConnector
from chumicro_timing.testing import FakeTicks
from chumicro_websockets import WebSocketClient, WebSocketServer, WebSocketState
from chumicro_websockets.testing import FakeConnection, FakeListener


def pump(client_socket, server_socket):
    server_socket.feed_inbound(client_socket.read_outbound())
    client_socket.feed_inbound(server_socket.read_outbound())


def test_the_server_receives_the_client_text():
    clock = FakeTicks()
    client_socket = FakeConnection()
    server_socket = FakeConnection()
    listener = FakeListener()
    listener.queue_accept(server_socket)
    received = []

    def on_connection(connection):
        connection.on_text = received.append

    server = WebSocketServer(listener=listener, on_connection=on_connection, ticks=clock)
    client = WebSocketClient(
        transport_factory=lambda host, port, use_tls: FakeSocketConnector(
            actions=["dns_ok", "tcp_ok"], socket=client_socket,
        ),
        ticks=clock,
    )

    client.connect("ws://example.com/")
    for _ in range(50):
        client.handle(clock.ticks_ms())
        server.handle(clock.ticks_ms())
        pump(client_socket, server_socket)
        if client.state == WebSocketState.OPEN:
            break
    assert server.connection_count == 1

    client.send_text("hello server")
    for _ in range(50):
        client.handle(clock.ticks_ms())
        server.handle(clock.ticks_ms())
        pump(client_socket, server_socket)
        if received:
            break
    assert received == ["hello server"]
```

The library's own `tests/test_integration.py` drives binary messages, ping and pong, and the close handshake through the same pump.

## API reference

::: chumicro_websockets.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets) · \
[PyPI](https://pypi.org/project/chumicro-websockets/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
