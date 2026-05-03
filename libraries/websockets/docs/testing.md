# Testing Helpers

`chumicro_websockets.testing` ships three in-memory fakes so libraries that depend on `chumicro-websockets` (and the library's own test suite) can drive `WebSocketClient` and `WebSocketServer` end-to-end without real sockets.

## Usage

### `FakeConnection`

Bidirectional in-memory pipe satisfying the `TCPClientSocket` shape:

```python
from chumicro_websockets import WebSocketClient
from chumicro_websockets.testing import FakeConnection, TickClock

def test_client_handshake():
    socket = FakeConnection()
    clock = TickClock()
    client = WebSocketClient(
        connection_factory=lambda *_args, **_kwargs: socket,
        ticks_ms_func=clock.now,
        ticks_add_func=clock.add,
        ticks_diff_func=clock.diff,
    )
    client.connect("ws://example.com/")
    client.handle(clock.now())
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
from chumicro_websockets import WebSocketServer
from chumicro_websockets.testing import FakeConnection, FakeListener, TickClock

def test_server_accepts():
    listener = FakeListener()
    peer = FakeConnection()
    listener.queue_accept(peer)
    clock = TickClock()
    server = WebSocketServer(
        listener=listener,
        on_connection=lambda conn: None,
        ticks_ms_func=clock.now,
        ticks_add_func=clock.add,
        ticks_diff_func=clock.diff,
    )
    server.handle(clock.now())  # accepts the queued peer
    assert server.connection_count == 1
```

### `TickClock`

Manually-advanced fake for the `chumicro_timing` `ticks_ms` / `ticks_add` / `ticks_diff` trio.  Wire the three methods through the client's / server's `ticks_*_func` constructor parameters; `clock.advance(ms)` jumps the simulated clock forward to drive timeouts, auto-ping cadences, and pong-overdue watchdogs:

```python
clock = TickClock()
client = WebSocketClient(
    connection_factory=...,
    handshake_timeout_ms=1000,
    ticks_ms_func=clock.now,
    ticks_add_func=clock.add,
    ticks_diff_func=clock.diff,
)
client.connect("ws://example.com/")
clock.advance(2000)  # past the handshake deadline
client.handle(clock.now())
# Client now CLOSED with WebSocketTimeoutError.
```

## Usage from other libraries

Libraries that depend on `chumicro-websockets` can import the fakes directly:

```python
from chumicro_websockets.testing import FakeConnection, FakeListener, TickClock
```

This follows the project convention from [Decision 0010](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0010-library-testability.md): libraries that expose injectable services ship their own test fakes.

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
