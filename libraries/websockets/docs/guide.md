# User Guide

## Overview

A WebSocket is a network connection that stays open, so either end can send a message whenever it likes.  Reach for one when a board should push readings to a browser dashboard or a laptop script, or take commands from one, without asking over and over with HTTP requests.

`chumicro-websockets` covers both ends.  `WebSocketClient` connects your board to a server at a `ws://` or `wss://` (TLS) URL.  `WebSocketServer` listens for clients and gives you one `Connection` object per client.  Neither one blocks: each does a small, bounded piece of network work every time your loop calls it, so an LED, a button, or a sensor in the same program keeps running while messages come and go.

The examples on this page use `chumicro-runner` to make those calls.  A `Runner` keeps a list of tasks.  `runner.tick()` gives each task one short turn, and `runner.wait(now_ms)` then idles the CPU until a socket has data or a timer is due.  Those two lines inside `while True:` are the main loop of a ChuMicro program.

## Getting started: a client

This client joins wifi, connects to a server, sends `hello` every five seconds, and prints every text message the server sends back:

```python
from chumicro_runner import Runner
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_websockets import WebSocketClient, WebSocketState
from chumicro_wifi import WifiConfig, WifiService

runner = Runner()

# Join wifi first.  WifiService also rejoins on its own after a drop.
wifi = WifiService(WifiConfig(ssid="home-wifi", password="s3cret"))
runner.add(wifi)
while not wifi.connected:
    now_ms = runner.tick()
    runner.wait(now_ms)

# radio= is the CircuitPython radio; MicroPython and CPython ignore it.
client = WebSocketClient(transport_factory=connector_factory(radio=wifi.adapter.radio))
client.on_text = lambda text: print("received:", text)
client.connect("ws://192.168.1.42:8765/")
runner.add(client)


def send_hello(now_ms):
    if client.state == WebSocketState.OPEN:
        client.send_text("hello")


runner.add_periodic(send_hello, period_ms=5000)

while True:
    now_ms = runner.tick()  # wifi, the client, and the timer each take a turn
    runner.wait(now_ms)     # then the CPU idles until a message arrives or the timer is due
```

- `connector_factory` tells the client how to open its network connection.  `connect()` returns straight away; the client opens the connection and completes the WebSocket handshake over its next few turns, and the `on_open` callback fires when it is ready.
- `on_text` runs once for each complete text message.  [Callbacks](#callbacks) lists the rest.
- `send_text()` and `send_binary()` queue a message, and the client writes it out on its next turns.  Both raise `WebSocketStateError` unless `client.state` is `WebSocketState.OPEN`, which is why `send_hello` checks first.
- `runner.add_periodic(send_hello, period_ms=5000)` calls `send_hello` every five seconds.

No server to try it against?  The [`client.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/client.py) example's docstring has a one-line echo server to run on your laptop.

### Reconnecting after a drop

A `WebSocketClient` connects once.  When the connection closes, `client.state` becomes `WebSocketState.CLOSED` and stays there, and calling `connect()` again raises `WebSocketStateError`.  To reconnect, make a new client.  `client.py` does that on the same five-second timer that sends messages:

```python
def start_client():
    client = WebSocketClient(transport_factory=connector_factory(radio=wifi.adapter.radio))
    client.on_text = lambda text: print("received:", text)
    client.on_close = lambda code, reason: print("closed:", code, reason)
    client.connect("ws://192.168.1.42:8765/")
    return client, runner.add(client)


client, client_task = start_client()


def send_or_reconnect(now_ms):
    global client, client_task
    if client.state == WebSocketState.OPEN:
        client.send_text("hello")
    elif client.state == WebSocketState.CLOSED:
        client_task.remove()                  # stop the runner calling the closed client
        client, client_task = start_client()


runner.add_periodic(send_or_reconnect, period_ms=5000)
```

`runner.add()` returns a task handle, and `remove()` on it takes the old client off the runner's list so closed clients do not pile up in memory.  `on_close` fires for a failed connection attempt too, with code `1011` and the error as the reason, so every retry shows up in the output.

## Getting started: a server

This server echoes every text message back to the client that sent it:

```python
from chumicro_runner import Runner
from chumicro_sockets.sockets_factory import listener_factory
from chumicro_websockets import WebSocketServer
from chumicro_wifi import WifiConfig, WifiService

runner = Runner()
wifi = WifiService(WifiConfig(ssid="home-wifi", password="s3cret"))
runner.add(wifi)
while not wifi.connected:
    now_ms = runner.tick()
    runner.wait(now_ms)
print(f"connect to ws://{wifi.ip}:8765/")


def on_connection(connection):
    # Runs once for each client that connects: send its text messages back.
    connection.on_text = lambda text: connection.send_text("echo: " + text)


server = WebSocketServer(
    listener_factory=listener_factory("0.0.0.0", 8765, radio=wifi.adapter.radio),
    on_connection=on_connection,
)
runner.add(server)

while True:
    now_ms = runner.tick()  # the server accepts clients and moves their messages
    runner.wait(now_ms)     # then the CPU idles until a client needs attention
```

- `listener_factory` describes the listening socket, and the server opens it on its first turn, so building the server touches no network.  To hand over a socket you already opened, pass it as `listener=` instead.  Pass one or the other, never both.
- `on_connection(connection)` runs once per client, when that client's opening handshake completes.  Set the client's callbacks there.  `connection.request_path` holds the path in the client's URL.
- `max_connections` (default 2) caps how many clients can be connected at once; the server stops accepting while it is full.  `accept_path="/ws"` turns away any other path with a 404.
- The server drives every `Connection` itself.  Add only the server to the runner.

To try it from a laptop, run `pip install websockets`, then `python -m websockets ws://<board-ip>:8765/` for an interactive client.  Type a line and the board sends it back.

### Sending to every client

`server.connections` is a tuple of the clients connected right now, so sending to all of them is a loop.  The [`server.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/server.py) example sends a count every five seconds:

```python
from chumicro_websockets import WebSocketState

count = 0


def send_count(now_ms):
    global count
    count += 1
    for connection in server.connections:
        if connection.state == WebSocketState.OPEN:  # a client still handshaking can't take messages
            connection.send_text(f"count {count}")


runner.add_periodic(send_count, period_ms=5000)
```

`server.connection_count` gives the number of clients without building the tuple.

## Reading messages with a generator

Callbacks hand you each message as it arrives.  `next_message()` lets you write the receiving side as a plain loop instead.  A generator is a function that pauses at each `yield` and picks up from that line on a later turn; `message = yield from client.next_message()` pauses until the next message arrives while the runner keeps everything else going.

Keep the client example's imports and its wifi setup, down to the `while not wifi.connected:` loop, then continue with:

```python
client = WebSocketClient(transport_factory=connector_factory(radio=wifi.adapter.radio))
client.connect("ws://192.168.1.42:8765/")


def print_messages():
    while True:
        message = yield from client.next_message()
        if message is None:  # the connection closed
            break
        print("received:", message.text if message.is_text else message.data)
    print("closed:", client.last_close_code, client.last_close_reason)


runner.add(client)                      # first the client, which reads the network
runner.add_generator(print_messages())  # then the generator, which prints what arrived

while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

- `next_message()` returns an `InboundMessage` with `is_text`, `text`, and `data`, or `None` once the connection has closed and every queued message has been read.
- Add the client and the generator in either order.  When the client reads a message after the generator has had its turn, the waiting `next_message()` tells `runner.wait()` it is due, so the loop comes straight back round and the generator prints it.
- The first `next_message()` call switches that client from callbacks to a queue, and `on_text` and `on_binary` stop firing.  Use one style or the other per client.  The queue holds `max_inbound_queue_size` messages (default 16) and drops the oldest when it is full.

The [`receive_stream.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/receive_stream.py) example starts a new client and a new generator each time the connection closes.

## Runner pattern

`WebSocketClient` and `WebSocketServer` are runner tasks: `runner.add()` accepts them because they have these methods.

- `check(now_ms)` returns `True` while there is work to do.
- `handle(now_ms)` does one bounded step of that work: at most `recv_budget_per_tick` bytes in and `send_budget_per_tick` bytes out.
- `io_socket`, `io_interest(now_ms)`, and `next_deadline(now_ms)` tell `runner.wait()` which socket to watch and when the next timeout or ping is due, so it can idle the CPU instead of spinning.

Without a runner, call `check` and `handle` from your own loop:

```python
from chumicro_timing import ticks_ms

while True:
    now_ms = ticks_ms()  # one timestamp per pass, shared by check and handle
    if client.check(now_ms):
        client.handle(now_ms)
```

This loop never idles.  It spins the CPU between messages where `runner.wait()` would sleep, which costs battery on a board but behaves the same otherwise.

## Callbacks

Every callback starts as a function that does nothing.  The client or connection calls yours from inside `handle()`, during `runner.tick()`, never from a thread or an interrupt.

### Client (`WebSocketClient`)

| Callback | Fired when |
|---|---|
| `on_open()` | The opening handshake completes and `state` is now `OPEN`. |
| `on_text(text: str)` | A complete text message has arrived and passed UTF-8 validation. |
| `on_binary(data: bytes)` | A complete binary message has arrived. |
| `on_ping(payload: bytes)` | The server sent a PING.  The client has already queued the PONG reply. |
| `on_pong(payload: bytes)` | The server answered one of the client's PINGs. |
| `on_close(code: int, reason: str)` | The connection reached `CLOSED`, after a clean close, a dropped link, or a failed connection attempt (code `1011`). |
| `on_oversized(reported_length: int)` | An incoming message was larger than `max_message_bytes` and was dropped.  Fires under the default `WhenOversized.DROP_WITH_EVENT` policy. |

### Server (`Connection`)

Set a connection's callbacks inside `on_connection(connection)`:

```python
def on_connection(connection):
    connection.on_text = ...
    connection.on_binary = ...
    connection.on_close = ...
    connection.on_oversized = ...
```

A `Connection` has the same callbacks as the client except `on_open`, because `on_connection` already marks the open.  A client the server turns away during the handshake (a wrong `accept_path`, a malformed request) never reaches `on_connection`, so no callback fires for it.

## Errors

Every exception the library defines is a `WebSocketError`.  Three are raised straight to your code:

- `WebSocketURLError` from `connect()`, for a URL that is not a valid `ws://` or `wss://` address.
- `WebSocketStateError` from a call made in the wrong state: sending before the connection is open, or calling `connect()` a second time.
- `WebSocketBackpressureError` from `send_text()` or `send_binary()` when the outgoing queue is full.

A connection that fails on the network side does not raise.  It closes, `on_close` fires, and the cause waits in `last_error` on the client or `Connection`:

- `WebSocketStateError` reading `connector failed: ...` when the TCP or TLS connection could not be opened.
- `WebSocketTimeoutError` for a handshake, close, or PONG that took too long.
- `WebSocketHandshakeError` when the server refused the upgrade.
- `WebSocketProtocolError` for a malformed frame, or a link that dropped without a CLOSE.

A clean close leaves `last_error` as `None`.  On the server, a failed `accept()` lands in `server.last_error`, and a listening socket that cannot be opened (for example, because another program holds the port) raises from the server's first `handle()`.

`close(code, reason)` takes one of the `CLOSE_*` constants (default `CLOSE_NORMAL`, 1000).  The `OPCODE_*` constants, `parse_ws_url`, `make_websocket_key`, and `derive_accept_key` are the RFC 6455 pieces the two classes are built from, exported for tests and custom tools.

## Bring your own transport

`WebSocketClient` and `WebSocketServer` work with sockets from any library.  The client's `transport_factory` is a callable `(host, port, use_tls) -> connector`, where a connector is an object that opens a connection over several turns.  The client calls its `tick(now_ms)`, waits for its `state` to reach `"ready"` (or `"failed"`, with the cause in `last_error`), then takes its `socket`.  The client also reads `io_socket` and `io_interest(now_ms)` while the connection opens and calls `cancel()` if it gives up.  `chumicro_sockets.connector` is one such connector.

The server's `listener` (or the socket its `listener_factory` returns) needs `accept()`, `close()`, and optionally `setblocking()`.

Once open, every socket must provide this TCP contract:

| Method | Contract |
|---|---|
| `recv_into(buffer, nbytes) -> int` | Reads up to `nbytes` into `buffer` (a `memoryview`).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` when no data is waiting, returns 0 when the peer closed, otherwise returns the bytes written. |
| `send(payload) -> int` | Sends `payload` (a `bytes`).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` when the send buffer is full, otherwise returns the bytes sent, which may be fewer than all of them. |
| `close() -> None` | Releases the connection. |
| `setblocking(flag) -> None` | Best-effort.  A socket without it still works. |

If you supply your own factory and want `chumicro_sockets` left off the board entirely, add a module-level constant to your entrypoint and the `chumicro-workspace` deployer leaves the default factory out of the deploy:

```python
# code.py / app.py
__chumicro_skip_factories__ = ("sockets_factory",)
```

`"sockets_factory"` matches every `chumicro_*.sockets_factory` module; `"chumicro_sockets.sockets_factory"` names one exactly.  An entry that matches nothing fails the deploy with a typo message.  `WebSocketClient.from_config(...)` and `WebSocketServer.from_config(...)` raise `RuntimeError` when `chumicro_sockets.sockets_factory` is missing from the board and you passed no transport of your own.

Nothing in the library requires the rest of ChuMicro beyond `chumicro-sockets` and `chumicro-timing`: pass your own transport, pass `ticks=` to use your own clock, and call `check` and `handle` from your own loop.

## Memory notes

The library is sized for boards with 256 KB of RAM and about 800 KB of usable flash.

- `max_message_bytes` (default 16 KB) caps the size of an incoming message.  Each frame takes one of three paths:
  - Up to 256 bytes: read into a buffer the parser reuses for every frame, then copied once into the `bytes` your callback receives.
  - Over 256 bytes and up to `max_message_bytes`: read into a `bytearray` allocated for that frame and freed after delivery.
  - Over `max_message_bytes`: counted off the socket and thrown away without allocating.  The `when_oversized` policy then decides what happens: `DROP_SILENT` and `DROP_WITH_EVENT` stay connected, and `DISCONNECT` closes with code 1009.
- `max_tx_queue_size` (default 8) caps queued outgoing messages.  One more `send_text()` raises `WebSocketBackpressureError`; let the loop run a few turns and send again.  The library's own frames (PONG replies and the close handshake) get 8 extra slots, so a CLOSE always fits.  Under a flood of PINGs, a PONG that would take the last slot is dropped rather than pushing out a queued message, which RFC 6455 §5.5.3 allows.
- `recv_budget_per_tick` and `send_budget_per_tick` (default 1024 bytes each) bound one turn's reading and writing.  Reads go through a 512-byte buffer that is reused every turn, and a 16 KB message takes about 16 turns to arrive, so one large message cannot hold up an LED or a button check.

## Per-tick knobs

| Knob | Default | Why |
|---|---|---|
| `recv_budget_per_tick` | `1024` | Bytes read per turn, so other tasks keep getting turns while a large message arrives. |
| `send_budget_per_tick` | `1024` | Bytes written per turn, for the same reason. |
| `max_message_bytes` | `16384` | Largest incoming message the board will keep. |
| `max_tx_queue_size` | `8` | Outgoing messages waiting to be written. |
| `max_inbound_queue_size` | `16` | Messages waiting for `next_message()`; the oldest is dropped when full. |
| `when_oversized` | `WhenOversized.DROP_WITH_EVENT` | Drop an oversized message, call `on_oversized(reported_length)`, and stay connected.  `DISCONNECT` closes with code 1009 instead. |
| `ping_interval_ms` | `None` (off) | Client only: send a PING this often to keep the connection alive and notice a dead one. |
| `pong_timeout_ms` | `30000` | Close the connection when a PING gets no PONG within 30 s. |
| `handshake_timeout_ms` | `10000` | Time allowed for opening the connection and completing the handshake. |
| `close_timeout_ms` | `5000` | Time to wait for the other end's CLOSE before dropping the connection anyway. |

## Testing

`chumicro_websockets.testing` ships `FakeConnection` and `FakeListener`, in-memory stand-ins for real sockets, so host tests can drive a client or a server end to end without a network.  [Testing Helpers](testing.md) walks through both, including a client-to-server round trip in one process.

## Platform notes

| Runtime | Client (`ws://` + `wss://`) | Server (`ws://`) | Server (`wss://`) |
|---|---|---|---|
| CPython | ✅ | ✅ | ✅ |
| MicroPython | ✅ | ✅ | ✅ |
| CircuitPython on ESP32 family (S2 / S3) | ✅ | ✅ | ✅ |
| CircuitPython on Pi Pico W (rp2) | ✅ | ✅ | ❌ (raises `UnsupportedSSLConfigError`) |

### TLS (`wss://`)

A `wss://` client connects through `chumicro_sockets.connector(tls=True)`, with the same constraints as any HTTPS client on a board:

- **Set the board's clock before connecting.**  TLS rejects every certificate as not yet valid while the real-time clock still holds its power-on default.  [`chumicro-ntp`](https://chumicro.com/ChuMicro/ntp/stable/) sets it.
- **The server's certificate is checked against the runtime's trust roots.**  To trust only your own CA, for a self-signed server on your network, build a context with `chumicro_sockets.ssl_context_with_ca(pem)` and pass it as `connector_factory(radio=..., ssl_context=context)`.
- **Pi Pico W needs flash deploy mode for `wss://`.**  RAM mode leaves less than 50 KB free, too little for the TLS handshake.

## Examples

Each example ends in a `while True:` loop that runs until you unplug the board, and its docstring says what to run on a laptop for the other end.

| Example | What it shows |
|---|---|
| [`client.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/client.py) | Sends `hello N` to an echo server every five seconds, prints each reply, and reconnects after the connection drops. |
| [`server.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/server.py) | Echoes every text message back to its sender and sends a count to every connected client every five seconds. |
| [`receive_stream.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/receive_stream.py) | Prints each message a server streams, read with a `next_message()` generator, and reconnects when the stream ends. |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets) · \
[PyPI](https://pypi.org/project/chumicro-websockets/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
