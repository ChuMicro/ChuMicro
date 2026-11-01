# User Guide

## Overview

A WebSocket is a network connection that stays open, so either end can send a message at any moment.  A board uses one to push readings to a browser dashboard or a laptop script, or to take commands from one, with no repeated HTTP requests.

`chumicro-websockets` covers both ends.  `WebSocketClient` connects a board to a server at a `ws://` URL, or a `wss://` URL for TLS.  `WebSocketServer` listens for clients and hands over one `Connection` object per client.  Each call to either class does a small, bounded piece of network work and returns.  An LED, a button, or a sensor in the same program keeps running while messages come and go.

The examples on this page make those calls from a [`chumicro-runner`](https://chumicro.com/ChuMicro/runner/stable/guide/) loop.  On each pass, `runner.tick()` runs one step of every job.  `runner.wait(now_ms)` then sleeps until a socket has data or a timer is due.

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

# CircuitPython needs radio=, and MicroPython ignores it.
client = WebSocketClient(transport_factory=connector_factory(radio=wifi.adapter.radio))
client.on_text = lambda text: print("received:", text)
client.connect("ws://192.168.1.42:8765/")
runner.add(client)


def send_hello(now_ms):
    if client.state == WebSocketState.OPEN:
        client.send_text("hello")


runner.add_periodic(send_hello, period_ms=5000)

while True:
    now_ms = runner.tick()  # wifi, the client, and the timer each take a step
    runner.wait(now_ms)     # then the CPU idles until a message arrives or the timer is due
```

- `connector_factory` tells the client how to open its network connection.  `connect()` returns at once.  Over its next few steps the client opens the connection and completes the WebSocket handshake.  The `on_open` callback runs when the connection is ready.
- `on_text` runs once for each complete text message.  [Callbacks](#callbacks) lists the rest.
- `send_text()` and `send_binary()` queue a message.  The client writes it out over its next steps.  Both raise `WebSocketStateError` unless `client.state` is `WebSocketState.OPEN`, so `send_hello` checks the state first.
- `runner.add_periodic(send_hello, period_ms=5000)` calls `send_hello` every five seconds.

The [`client.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/client.py) example's docstring has a one-line echo server to run on a laptop.

### Reconnecting after a drop

A `WebSocketClient` connects once.  When the connection closes, `client.state` becomes `WebSocketState.CLOSED` and stays there.  A second `connect()` raises `WebSocketStateError`.  A new client makes the next connection.  `client.py` builds one on the same five-second timer that sends messages:

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

`runner.add()` returns a `TaskHandle`.  `remove()` on the handle takes the old client off the runner's list, so closed clients never pile up in memory.  `on_close` also runs for a failed connection attempt, with code `1011` and the error as the reason, so every retry shows in the output.

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

- `listener_factory` describes the listening socket.  The server opens it on its first step, so building the server touches no network.  A socket that is already open goes in as `listener=` instead.  The server takes one of the two, never both.
- `on_connection(connection)` runs once per client, when that client's opening handshake completes.  Set the client's callbacks there.  `connection.request_path` holds the path from the client's URL.
- `max_connections` (default 2) caps how many clients can be connected at once.  The server stops accepting while it is full.  `accept_path="/ws"` answers any other path with a 404.
- The server drives every `Connection` itself, so only the server goes on the runner.

To try it from a laptop, run `pip install websockets`, then `python -m websockets ws://<board-ip>:8765/` for an interactive client.  Type a line and the board sends it back.

### Sending to every client

`server.connections` is a tuple of the clients connected right now, so a loop sends to all of them.  The [`server.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/server.py) example sends a count every five seconds:

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

Callbacks receive each message as it arrives.  `next_message()` reads messages in a plain loop inside a [generator task](https://chumicro.com/ChuMicro/runner/stable/guide/#generator-tasks).  `message = yield from client.next_message()` pauses the task until the next message arrives, while the runner keeps everything else going.

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

- `next_message()` returns an `InboundMessage` with `is_text`, `text`, and `data`.  It returns `None` once the connection has closed and every queued message has been read.
- The client and the generator go on the runner in either order.  When the client reads a message after the generator's step, the waiting `next_message()` tells `runner.wait()` it is due.  The loop then comes straight back round, and the generator prints the message.
- The first `next_message()` call switches that client from callbacks to a queue.  `on_text` and `on_binary` stop running from then on.  Each client uses one style.  The queue holds `max_inbound_queue_size` messages and drops the oldest when it is full.

The [`receive_stream.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/websockets/examples/receive_stream.py) example starts a new client and a new generator each time the connection closes.

## Runner pattern

`WebSocketClient` and `WebSocketServer` are runner [services](https://chumicro.com/ChuMicro/runner/stable/guide/#services).  `check(now_ms)` returns `True` while there is work to do.  `handle(now_ms)` reads at most `recv_budget_per_tick` bytes and writes at most `send_budget_per_tick` bytes per call.  Both classes also report their socket and their next timeout or ping to `runner.wait()`, through the members [Network services](https://chumicro.com/ChuMicro/runner/stable/guide/#network-services) lists, so the CPU sleeps between messages.

A loop with no runner calls `check` and `handle` itself:

```python
from chumicro_timing import ticks_ms

while True:
    now_ms = ticks_ms()  # one timestamp per pass, shared by check and handle
    if client.check(now_ms):
        client.handle(now_ms)
```

This loop spins the CPU between messages, where `runner.wait()` would sleep.  The spinning costs battery on a board and changes nothing else.

## Callbacks

Every callback starts as a function that does nothing.  The client or connection calls yours from inside `handle()`, during `runner.tick()`, never from a thread or an interrupt.

### Client (`WebSocketClient`)

| Callback | Runs when |
|---|---|
| `on_open()` | The opening handshake completes and `state` is now `OPEN`. |
| `on_text(text: str)` | A complete text message has arrived and passed UTF-8 validation. |
| `on_binary(data: bytes)` | A complete binary message has arrived. |
| `on_ping(payload: bytes)` | The server sent a PING.  The client has already queued the PONG reply. |
| `on_pong(payload: bytes)` | The server answered one of the client's PINGs. |
| `on_close(code: int, reason: str)` | The connection reached `CLOSED`, after a clean close, a dropped link, or a failed connection attempt (code `1011`). |
| `on_oversized(reported_length: int)` | An incoming message was larger than `max_message_bytes` and was dropped.  Runs under the default `WhenOversized.DROP_WITH_EVENT` policy. |

### Server (`Connection`)

Set a connection's callbacks inside `on_connection(connection)`:

```python
def on_connection(connection):
    connection.on_text = ...
    connection.on_binary = ...
    connection.on_close = ...
    connection.on_oversized = ...
```

A `Connection` has the client's callbacks except `on_open`, because `on_connection` marks the open.  A client the server turns away during the handshake, for a wrong `accept_path` or a malformed request, never reaches `on_connection`, so no callback runs for it.

## Errors

Every exception the library defines subclasses `WebSocketError`.  These three are raised straight to the calling code:

- `WebSocketURLError` from `connect()`, for a URL that is not a valid `ws://` or `wss://` address.
- `WebSocketStateError` from a call made in the wrong state: a send before the connection is open, or a second `connect()`.
- `WebSocketBackpressureError` from `send_text()` or `send_binary()` when the outgoing queue is full.

A failure on the network side closes the connection and runs `on_close`.  The cause then waits in `last_error` on the client or `Connection`:

- `WebSocketStateError` reading `connector failed: ...` when the TCP or TLS connection could not be opened.
- `WebSocketTimeoutError` for a handshake, close, or PONG that took too long.
- `WebSocketHandshakeError` when the server refused the upgrade.
- `WebSocketProtocolError` for a malformed frame, or a link that dropped without a CLOSE.

A clean close leaves `last_error` as `None`.  On the server, a failed `accept()` lands in `server.last_error`.  A listening socket that cannot be opened, for example because another program holds the port, raises from the server's first `handle()`.

`close(code, reason)` takes one of the `CLOSE_*` constants.  The default is `CLOSE_NORMAL` (1000).  The `OPCODE_*` constants, `parse_ws_url`, `make_websocket_key`, and `derive_accept_key` are the RFC 6455 pieces the two classes are built from, exported for tests and custom tools.

## Bring your own transport

`WebSocketClient` and `WebSocketServer` work with sockets from any library.  The client's `transport_factory` is a callable `(host, port, use_tls) -> connector`.  A connector opens a connection over several steps: the client calls its `tick(now_ms)` until its `state` reaches `"ready"`, then takes its `socket`.  A `state` of `"failed"` ends the attempt, with the cause in the connector's `last_error`.  While the connection opens, the client also reads `io_socket` and `io_interest(now_ms)`.  It calls `cancel()` when it gives up.  `chumicro_sockets.connector` is one such connector.

The server's `listener`, or the socket its `listener_factory` returns, needs `accept()`, `close()`, and optionally `setblocking()`.

Once open, every socket must provide these methods:

| Method | Contract |
|---|---|
| `recv_into(buffer, nbytes) -> int` | Reads up to `nbytes` into `buffer` (a `memoryview`).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` when no data is waiting, returns 0 when the peer closed, and otherwise returns the number of bytes written. |
| `send(payload) -> int` | Sends `payload` (a `bytes`).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` when the send buffer is full, and otherwise returns the number of bytes sent, which may be fewer than all of them. |
| `close() -> None` | Releases the connection. |
| `setblocking(flag) -> None` | Optional.  The library calls it when the socket has it. |

A program that supplies its own transport can keep `chumicro_sockets` off the board with one line in `code.py` or `app.py`:

```python
__chumicro_skip_factories__ = ("sockets_factory",)
```

[Slimming your deploy](https://chumicro.com/ChuMicro/guides/contributing/slimming-your-deploy/) explains the line.  On a board without `chumicro_sockets.sockets_factory`, `WebSocketClient.from_config(...)` and `WebSocketServer.from_config(...)` raise `RuntimeError` unless a transport of your own was passed.

The library uses two other ChuMicro libraries: `chumicro-sockets` for its default transport and `chumicro-timing` for its default clock.  With your own transport, your own clock passed as `ticks=`, and `check` and `handle` called from your own loop, it runs with no other ChuMicro library.

## Memory notes

The library fits boards with 256 KB of RAM and about 800 KB of usable flash.

- `max_message_bytes` caps the size of an incoming message.  Each frame takes one of three paths:
  - Up to 256 bytes: read into a buffer the parser reuses for every frame, then copied once into the `bytes` the callback receives.
  - Over 256 bytes and up to `max_message_bytes`: read into a `bytearray` allocated for that frame and freed after delivery.
  - Over `max_message_bytes`: counted off the socket and thrown away with no allocation.  The `when_oversized` policy then decides what happens.  `DROP_SILENT` and `DROP_WITH_EVENT` stay connected.  `DISCONNECT` closes with code 1009.
- `max_tx_queue_size` caps queued outgoing messages.  One more `send_text()` raises `WebSocketBackpressureError`.  Let the loop run a few passes and send again.  The library's own frames, PONG replies and the close handshake, get 8 extra slots, so a CLOSE always fits.  Under a flood of PINGs, the library drops a PONG that would take the last slot and keeps the queued messages, as RFC 6455 §5.5.3 allows.
- `recv_budget_per_tick` and `send_budget_per_tick` bound one step's reading and writing.  Reads go through a buffer of at most 512 bytes that is reused every step.  A 16 KB message takes about 16 steps to arrive, so one large message never holds up an LED or a button check.

## Per-tick knobs

| Knob | Default | Why |
|---|---|---|
| `recv_budget_per_tick` | `1024` | Bytes read per step, so other jobs keep running while a large message arrives. |
| `send_budget_per_tick` | `1024` | Bytes written per step, for the same reason. |
| `max_message_bytes` | `16384` | Largest incoming message the board keeps. |
| `max_tx_queue_size` | `8` | Outgoing messages waiting to be written. |
| `max_inbound_queue_size` | `16` | Messages waiting for `next_message()`.  The oldest is dropped when the queue is full. |
| `when_oversized` | `WhenOversized.DROP_WITH_EVENT` | Drop an oversized message, call `on_oversized(reported_length)`, and stay connected.  `DISCONNECT` closes with code 1009. |
| `ping_interval_ms` | `None` (off) | Client only: send a PING this often to keep the connection alive and notice a dead one. |
| `pong_timeout_ms` | `30000` | Close the connection when a PING gets no PONG within 30 s. |
| `handshake_timeout_ms` | `10000` | Time allowed for opening the connection and completing the handshake. |
| `close_timeout_ms` | `5000` | Time to wait for the other end's CLOSE before dropping the connection. |

## Testing

`chumicro_websockets.testing` ships `FakeConnection` and `FakeListener`, in-memory stand-ins for real sockets, so host tests drive a client or a server end to end with no network.  [Testing Helpers](testing.md) walks through both, including a client-to-server round trip in one process.

## Platform notes

| Runtime | Client (`ws://` + `wss://`) | Server (`ws://`) | Server (`wss://`) |
|---|---|---|---|
| CPython | ✅ | ✅ | ✅ |
| MicroPython | ✅ | ✅ | ✅ |
| CircuitPython on ESP32 family (S2 / S3) | ✅ | ✅ | ✅ |
| CircuitPython on Pi Pico W (rp2) | ✅ | ✅ | ❌ (raises `UnsupportedSSLConfigError`) |

### TLS (`wss://`)

A `wss://` client connects through `chumicro_sockets.connector(tls=True)`.  The `chumicro-sockets` guide's [TLS](https://chumicro.com/ChuMicro/sockets/stable/guide/#tls) section and [Runtime and chip quirks](https://chumicro.com/ChuMicro/sockets/stable/guide/#runtime-and-chip-quirks) table cover certificate checks, the trusted roots on each runtime, and the board clock a certificate check needs.

To trust only your own CA, for a self-signed server on your network, build a context with `chumicro_sockets.ssl_context_with_ca(pem)` and pass it as `connector_factory(radio=..., ssl_context=context)`.

A `wss://` client on Pi Pico W needs flash deploy mode.  RAM mode leaves less than 50 KB free, too little for the TLS handshake.

## Examples

Each example ends in a `while True:` loop that runs until the board is unplugged.  Its docstring says what to run on a laptop for the other end.

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
