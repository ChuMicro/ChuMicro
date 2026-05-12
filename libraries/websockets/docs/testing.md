# Testing Helpers

`chumicro_websockets.testing` ships two in-memory fakes so libraries that depend on `chumicro-websockets` (and the library's own test suite) can drive `WebSocketClient` and `WebSocketServer` end-to-end without real sockets.

For the ticks domain, use `chumicro_timing.testing.FakeTicks` — pass it through the client's / server's `ticks=` kwarg.

## Usage

### `FakeConnection`

Bidirectional in-memory pipe satisfying the `TCPClientSocket` shape:

```python
from chumicro_timing.testing import FakeTicks
from chumicro_websockets import WebSocketClient
from chumicro_websockets.testing import FakeConnection

def test_client_handshake():
    socket = FakeConnection()
    clock = FakeTicks()
    client = WebSocketClient(
        connection_factory=lambda *_args, **_kwargs: socket,
        ticks=clock,
    )
    client.connect("ws://example.com/")
    client.handle(clock.ticks_ms())
    # Inspect what the client wrote.
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

Stand-in for `chumicro_sockets.tcp_listening_socket`:

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
from chumicro_timing.testing import FakeTicks
from chumicro_websockets import WebSocketClient
from chumicro_websockets.testing import FakeConnection

clock = FakeTicks()
client = WebSocketClient(
    connection_factory=lambda *_args, **_kwargs: FakeConnection(),
    handshake_timeout_ms=1000,
    ticks=clock,
)
client.connect("ws://example.com/")
clock.advance(2000)  # past the handshake deadline
client.handle(clock.ticks_ms())
# Client now CLOSED with WebSocketTimeoutError.
```

## Usage from other libraries

Libraries that depend on `chumicro-websockets` can import the fakes directly:

```python
from chumicro_timing.testing import FakeTicks
from chumicro_websockets.testing import FakeConnection, FakeListener
```

Project convention: libraries that expose injectable services ship their own test fakes alongside the production code.

For end-to-end client ↔ server loopback, see `tests/test_integration.py` in this library — it pumps bytes between paired `FakeConnection` objects to drive both runners through their full lifecycle in-process.

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
