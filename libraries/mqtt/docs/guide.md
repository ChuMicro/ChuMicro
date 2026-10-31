# User Guide

## Overview

`chumicro-mqtt` is an MQTT 3.1.1 client for CircuitPython, MicroPython, and CPython.  MQTT is a publish/subscribe protocol: every device connects to a *broker*, publishes messages to named *topics*, and subscribes to the topics it wants to hear.  Devices never talk to each other directly.

`MQTTClient` never makes your program wait on the network.  Your main loop asks `mqtt.check(now_ms)` whether the client has work to do, and `mqtt.handle(now_ms)` does one small step of it: dial the broker, send a queued message, read what has arrived, keep the connection alive, or reconnect after a drop.  Then it returns, so an LED keeps blinking and a button keeps answering while a message is on its way.  No threads, no `async`.

The client supports QoS 0 and QoS 1, retained messages, a last will, wildcard subscriptions, and TLS.  QoS 2 raises `UnsupportedQoSError`.

## Getting started

This program publishes a reading every five seconds and prints every message sent to `demo/cmd`.  It is the shape of `examples/telemetry.py`, which adds wifi setup, a broker on your laptop, and visible reconnects.

```python
import wifi  # CircuitPython joins wifi from settings.toml at startup

from chumicro_mqtt import MQTTClient
from chumicro_timing import Rate, ticks_ms

mqtt = MQTTClient.from_config(
    {"mqtt.broker.host": "192.168.1.20", "mqtt.broker.port": 1883},
    radio=wifi.radio,
)


def on_message(topic, payload):
    print(topic, payload)


mqtt.on_message = on_message
mqtt.subscribe("demo/cmd")
mqtt.connect()

publish_timer = Rate(5000, ticks_ms())

while True:
    now_ms = ticks_ms()
    if mqtt.check(now_ms):
        mqtt.handle(now_ms)
    if publish_timer.due(now_ms):
        mqtt.publish("demo/temperature", "21.5", qos=1)
```

What each piece does:

- `MQTTClient.from_config(...)` reads the broker address and builds a client that dials the broker without stopping your loop, and dials again after a drop.  On CircuitPython it needs `radio=wifi.radio`; on MicroPython (connect `network.WLAN` first) and CPython, leave `radio` out.  The client id comes from the board's chip id (see [Client ids](#client-ids)).
- `on_message(topic, payload)` runs for every message that arrives on a subscribed topic.  `payload` is `bytes`.
- `subscribe()` can come before `connect()`.  The client remembers the topic, asks the broker for it as soon as the broker accepts the board, and asks again after every reconnect.
- `connect()` starts dialing and returns at once.  The `handle()` calls in the loop carry the connection through.
- `publish()` works at any moment.  Before the broker has answered, the message waits in a queue and goes out on connect (see [Publishing before connected](#publishing-before-connected)).
- `Rate(5000, ticks_ms())` is a `chumicro-timing` timer whose `due(now_ms)` turns `True` once every 5000 ms.

Create the client near the top of your program.  The first use of `MQTTClient` loads the client code into RAM, and that load fits best while the heap is still empty.

### With a runner

[`chumicro-runner`](https://chumicro.com/ChuMicro/runner/stable/) turns the same loop for you, runs several services side by side, and lets the CPU rest until the broker sends something or a timer is due:

```python
from chumicro_runner import Runner


def publish_reading(now_ms):
    mqtt.publish("demo/temperature", "21.5", qos=1)


runner = Runner()
runner.add(mqtt)                                      # calls check() and handle() for you
runner.add_periodic(publish_reading, period_ms=5000)  # every five seconds

while True:
    now_ms = runner.tick()   # every added task takes one small step
    runner.wait(now_ms)      # then the CPU rests until broker traffic or the next timer
```

`runner.wait()` is the line that lets the CPU rest.  A loop that calls `runner.tick()` without it spins at full speed.

## Client ids

Every MQTT connection carries a client id, and brokers treat it as the
identity of the session.  Pass your own when you have a meaningful name
for the device, as `client_id=` or as `mqtt.client_id` in the config:

```python
mqtt = MQTTClient.from_config(
    {"mqtt.broker.host": "192.168.1.20", "mqtt.broker.port": 1883},
    client_id="greenhouse-sensor-1",
)
```

When you don't, `default_client_id()` builds one from the board's
hardware UID, which is what `MQTTClient.from_config` uses:

```python
from chumicro_mqtt import default_client_id

default_client_id()               # "chumicro-e8db84a1b2c3"
default_client_id("greenhouse")   # "greenhouse-e8db84a1b2c3"
```

The id is unique across devices and stable across reboots, so a
persistent session resumes after a power cycle instead of colliding with
its own previous connection.  The UID comes from
`microcontroller.cpu.uid` on CircuitPython, `machine.unique_id()` on
MicroPython, and the host MAC via `uuid.getnode()` on CPython.

When none of those lookups works, the function returns the fixed string
`<prefix>-mqtt`.  Two boards that both fall back to it connect as the
same client, and an MQTT broker resolves a duplicate client id by
disconnecting the earlier session.  The symptom is a pair of devices that
keep kicking each other off the broker while each one looks healthy on
its own.  If you see that, print `default_client_id()` on both boards.
Getting `chumicro-mqtt` back means the UID lookup failed and you should
pass an explicit `client_id` per device.

## Publishing

`publish(topic, payload)` sends `payload` (`bytes`, or a `str` the client encodes as UTF-8) to `topic`.  The `qos` argument picks the quality of service.  QoS 0 sends the message once and moves on.  QoS 1 keeps the message until the broker confirms it with a PUBACK packet, and resends it when the confirmation is late.  `retain=True` asks the broker to keep the message and hand it to anyone who subscribes to the topic later, which suits a status such as "online".

```python
# QoS 0: send once, no confirmation
mqtt.publish("sensors/temp", b"21.5", qos=0)

# QoS 1: the broker confirms, and acked() runs when it does
def acked(topic, payload):
    print("broker has it:", topic, payload)

mqtt.publish("sensors/temp", b"21.5", qos=1, on_publish=acked)

# Retained: a later subscriber gets this value straight away
mqtt.publish("status/online", b"true", retain=True)
```

`on_publish(topic, payload)` receives the topic and payload you published.  For QoS 1 it runs when the broker's PUBACK arrives; for QoS 0 it runs once the bytes are sent.  A QoS 1 message the client had to resend still runs `on_publish` once.  Assign a function to `mqtt.on_publish` to hear about every message you publish.

### Publishing before connected

Connecting takes several passes of the loop, so `publish()` can run while the client is still coming up or reconnecting after a drop.  The `when_disconnected=` constructor argument decides what happens then:

| `when_disconnected` | Before CONNECTED |
|---|---|
| `"queue"` (default) | Hold the message in a pre-connect queue of `pre_connect_queue_size` messages (default 8) and send the queue, oldest first, as soon as the broker accepts the board, ahead of anything `on_connect` publishes.  A full queue raises `MQTTBackpressureError`. |
| `"raise"` | Raise `MQTTError` at once. |

A queued message keeps its `qos` and `retain`, and its `on_publish` runs once it is finally sent.  `subscribe()` and `unsubscribe()` skip this queue: the client keeps a list of wanted topics and sends it on every connect (see [Subscribing and routing](#subscribing-and-routing)).

## Subscribing and routing

`subscribe(topic)` asks the broker for every message on `topic`, and `on_message(topic, payload)` runs for each one that arrives.  A topic filter can hold wildcards: `+` matches one level and `#` matches every level below it.

```python
mqtt.on_message = lambda topic, payload: print(topic, "=>", payload)
mqtt.subscribe("commands/+")             # commands/set, commands/reset, ...
mqtt.subscribe("status/#", qos=1)        # status/door, status/door/battery, ...
```

Call `subscribe()` whenever you like: before `connect()`, inside `on_connect`, or while connected.  The client adds the topic to its list of wanted topics and sends the request at once when connected, otherwise as soon as the broker accepts the board.  After a reconnect it sends the whole list again, so messages keep arriving without any code from you.  The optional `on_subscribe(topic, granted_qos)` callback runs once, when the broker first grants the topic.  `unsubscribe(topic)` removes a topic from the list and tells the broker when connected.

To handle several topics differently, branch inside `on_message` with `topic_matches(topic, pattern)`, which applies the same wildcard rules:

```python
from chumicro_mqtt import topic_matches

def route(topic, payload):
    if topic_matches(topic, "commands/set"):
        apply_setting(payload)
    elif topic_matches(topic, "commands/reset"):
        reset_now()

mqtt.on_message = route
mqtt.subscribe("commands/+")             # one subscription covers both
```

`on_message` and `next_message()` (below) are the two ways to receive.  A client uses one or the other.

### Receive stream (`next_message`)

`next_message()` lets a generator task read messages in a plain loop instead of a callback.  A generator is a function with `yield` in it, and `chumicro-runner` runs it a step at a time alongside everything else.  `message = yield from mqtt.next_message()` pauses the generator until a message arrives, without pausing the board:

```python
from chumicro_mqtt import MQTTClient
from chumicro_runner import Runner

mqtt = MQTTClient.from_config(
    {"mqtt.broker.host": "192.168.1.20", "mqtt.broker.port": 1883},
)  # add radio=wifi.radio on CircuitPython
mqtt.subscribe("commands/+")
mqtt.connect()


def print_commands():
    while True:
        message = yield from mqtt.next_message()   # wait for the next message
        if message is None:
            return                                 # the client stopped for good
        print(message.topic, message.payload)


runner = Runner()
runner.add(mqtt)                         # the client's network work
runner.add_generator(print_commands())   # the receiving loop above

while True:
    now_ms = runner.tick()   # each added task takes one small step
    runner.wait(now_ms)      # then the CPU rests until a message or timer is due
```

The first `next_message()` call turns `on_message` off and delivers messages to a queue the generator reads instead.  The queue holds 16 messages; when the generator falls behind, the oldest message is dropped rather than the heap growing.  `next_message()` returns `None` only once the client has stopped for good: after `disconnect()`, after the broker refuses the board outright (bad credentials, for example), or after a drop on a client that has no way to reconnect.  `examples/receive_stream.py` is the full program.

`on_connect`, `on_disconnect`, and `on_oversized` keep firing either way.  `on_disconnect()` runs when a working connection ends, through `disconnect()` or a dropped link, and by then `mqtt.last_error` says why.  Failed attempts to reconnect stay quiet, so one outage fires it once.

## Last will

A last will is a message the board leaves with the broker when it connects.  If the board later drops off without a clean `disconnect()` (power cut, wifi loss, crash), the broker publishes the will on its behalf.  Paired with a retained `online` published from `on_connect`, it tells anything watching whether the board is there:

```python
STATUS_TOPIC = "devices/sensor-1/status"

mqtt.set_will(STATUS_TOPIC, b"offline", qos=1, retain=True)


def on_connect():
    mqtt.publish(STATUS_TOPIC, b"online", qos=1, retain=True)


mqtt.on_connect = on_connect
mqtt.connect()
```

A clean `disconnect()` cancels the will.  `set_will()` takes effect on the next connect, reconnects included, because the broker keeps the will it received for the current connection.  `set_will(None)` turns the will off.  A client built with `MQTTClient(...)` can also take the will as `will_topic=`, `will_message=`, `will_qos=`, and `will_retain=` arguments.

## TLS connections

Pass an `ssl_context=` to `from_config` and the client dials the broker over TLS:

```python
from chumicro_sockets import ssl_context_with_ca

with open("/ca.pem", "rb") as handle:
    ca_pem = handle.read()
ssl_context = ssl_context_with_ca(ca_pem)         # checks the broker's certificate
mqtt = MQTTClient.from_config(
    {"mqtt.broker.host": "broker.example.com", "mqtt.broker.port": 8883},
    ssl_context=ssl_context,
    radio=wifi.radio,                              # CircuitPython only
)
```

What to expect on a board:

* On MicroPython for Pi Pico W, `chumicro-sockets` converts the PEM certificate to DER for you, because that firmware cannot parse PEM.
* **The TLS handshake stops your whole loop while it runs.**  It happens inside one `handle()` call, so a sensor read, a watchdog feed, or a blinking LED waits until it finishes.  Against `test.mosquitto.org:8883` on a good wifi link it took 2 to 3 ms on a Lolin S2 and 10 to 11 ms on a Pi Pico W, both on CircuitPython; on a slow link or against an unreachable broker it can take seconds.  Connect before you start anything timing-critical, or allow for the pause.
* **The DNS lookup stops your loop too.**  Turning `broker.example.com` into an address waits on the board's resolver, which can hang until its own timeout when DNS is slow or down.  Put the broker's IP address in `mqtt.broker.host` if that pause is unacceptable.

## Reconnecting after a drop

A client built with `from_config()` reconnects by itself.  When the broker goes away or the wifi drops, the client notices (the socket closes, or an expected reply misses its deadline), runs `on_disconnect()`, and starts dialing again from inside `handle()`.  The first attempt goes out at once.  After that, the wait between attempts doubles from 1 second up to once a minute, so a long outage neither floods the broker nor drains a battery.  A successful connect resets the wait, runs `on_connect()` again, re-sends the subscriptions, and sends what `publish()` queued in the meantime.

The client stops retrying when the broker refuses it for a reason that retrying cannot fix: the broker's reply to a connect (CONNACK) carries return code 1, 2, 4, or 5 (unacceptable protocol version, identifier rejected, bad username or password, not authorized).  `mqtt.last_error` says which, and the next `connect()` call tries again.  Return code 3 (server unavailable) keeps retrying.  A subscription the broker refuses is dropped from the list of wanted topics, so a reconnect does not ask for it again.

To reconnect, the client needs a way to open a fresh connection.  `from_config()` gives it a *transport factory*: a function that returns a new connector for the broker each time it is called.  To build one yourself, pass `transport_factory=` to `MQTTClient(...)`:

```python
from chumicro_sockets import connector

def make_connector():
    return connector("broker.example.com", 1883, radio=wifi.radio)

mqtt = MQTTClient(transport_factory=make_connector, client_id="my-thing")
mqtt.connect()
```

A client built on a bare socket has no way to reconnect.  When that socket dies, the client stops in the `FAILED` state until you build a new one.

Each connection attempt moves one step per `handle()` call, except the DNS lookup and the TLS handshake, which each run to completion inside one call (see [TLS connections](#tls-connections)).

### Telling the client when wifi drops or returns

`connect()` is safe to call in any state:

- **Disconnected**: starts connecting.
- **`FAILED`**: reconnects at once, skipping whatever is left of the wait between attempts.
- **Connected or connecting**: does nothing, so a second dial never races the first.

`hold()` does the opposite: it pauses automatic reconnects until the next `connect()`.  While held, the client stays `FAILED` and keeps `last_error`, `publish()` still queues, and a runner's `wait()` stops waking up for retries that cannot succeed.

`MQTTClient` never watches the wifi itself, but your program can.  When it knows the link is down, `hold()` stops the client dialing through a dead radio (on ESP32 boards those dials can get in the way of the radio rejoining the network).  When the link is back, `connect()` dials at once instead of waiting out the backoff.  With `chumicro-wifi`, that is one line each way:

```python
from chumicro_wifi import WifiState

def on_wifi_state(old, new):
    if new == WifiState.CONNECTED:
        mqtt.connect()    # link is back: reconnect now (also clears the hold)
    else:
        mqtt.hold()       # link is down: stop dialing a dead radio

# WifiService reports link loss as RECONNECTING (then FAILED once retries
# are exhausted), so "any state but CONNECTED" is the down signal.

wifi.on_state_change(on_wifi_state)
```

Leaving this out is fine: the client still reconnects on its own.  `hold()` and `connect()` only make it react sooner when your program knows more than its timer does.

### Which messages survive a drop

The client takes a moment to notice a dead link, because a missing reply has to time out first.  What happens to a message depends on whether `publish()` ran before or after the client noticed:

- **Before**, while `mqtt.state` still reads `CONNECTED`: the message goes out on the dead connection and never gets its PUBACK.  With the default `clean_session=True`, the reconnect starts a fresh session on both ends and the message is lost.  Set `clean_session=False`, with a broker that keeps sessions, to have the client resend it instead.
- **After**, once the state is `FAILED` or the client is reconnecting: the message waits in the pre-connect queue and goes out, oldest first, as soon as the broker accepts the board again.

So an outage can lose the last message or two published before the client noticed, while everything after it arrives.  Keeping long blocking calls out of your loop shortens that window, because the client notices sooner.

## Bring your own transport

`MQTTClient` does not care which library produces its socket.  Any object exposing the four-method contract works:

| Method | Contract |
|---|---|
| `recv_into(buffer, nbytes) -> int` | Reads up to `nbytes` into `buffer` (a `memoryview`).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` on no data, returns 0 on peer-close, otherwise returns bytes written. |
| `send(payload) -> int` | Sends `payload` (a `bytes` or, on a partial-send resume, a `memoryview` slice of one).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` when the send buffer is full, otherwise returns bytes sent (may be partial). |
| `close() -> None` | Releases the connection. |
| `setblocking(flag) -> None` | Best-effort.  Absence is tolerated. |

The socket a `chumicro_sockets.connector` leaves on `.socket` at `ready` is one valid producer.  Stdlib `socket.socket` after `setblocking(False)` is another.  An upstream-library wrapper or a hand-rolled fake works the same way:

```python
# Example: stdlib socket on CPython for a test or desktop demo.
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(("broker.example.com", 1883))
sock.setblocking(False)
mqtt = MQTTClient(sock, client_id="desktop-demo")
```

A pre-built socket suits a desktop script or a test that already owns the connect.  It blocks while `sock.connect()` runs and cannot reconnect, so a board program that must keep its loop moving uses the `transport_factory` form from [Reconnecting after a drop](#reconnecting-after-a-drop).

The library has no `isinstance` checks against `chumicro_sockets` types; the contract is the four methods above.  Runtime errors surface at first call, not at construction time, so a misshaped object fails on the first `recv_into` / `send` rather than silently misbehaving.

If you supply your own transport and never want `chumicro_sockets` to land on the device, add a module-level constant to your entrypoint and the chumicro-workspace deployer will filter the default factory out of the import graph:

```python
# code.py / app.py
__chumicro_skip_factories__ = ("sockets_factory",)
```

The constant accepts a family form (the bare stem, matches every `chumicro_*.sockets_factory`) or an exact dotted path (`chumicro_sockets.sockets_factory`).  An unmatched entry fails the deploy with a typo message rather than silently shipping the default.  Calling `MQTTClient.from_config(...)` when `chumicro_sockets.sockets_factory` is missing (skipped at deploy time, or not installed by `circup` / `mip`) raises `RuntimeError` naming the bypass kwarg, so the failure mode is loud rather than mysterious.

With your own transport, your own clock passed as `ticks=`, and `check()` / `handle()` called from a plain loop, the client needs no other ChuMicro library.  Host tests drive it the same way with no board attached.

## Tuning responsiveness against throughput

Each `handle()` call does exactly one `recv_into` and one packet `send`, so it returns after a small, fixed amount of socket work.  (A call that received QoS 1 messages makes one extra send: that call's PUBACKs coalesce into a single batch flushed ahead of the packet budget without consuming it, so the ack rate always keeps up with the inbound rate.  If the socket can't take the batch, the client stops reading until it lands; the unread bytes throttle the broker through the TCP window.)  Three constructor knobs let you tune the trade-off:

| Knob | Default | What it bounds |
|---|---|---|
| `recv_budget_per_tick` | `1024` (bytes) | Cap on the single per-tick `recv_into` call.  It binds only when `rx_buffer_size` exceeds it: each recv is already limited to the RX buffer's free space, so at the default 256-byte `rx_buffer_size` the budget never engages.  With a large `rx_buffer_size`, it bounds tick latency on a multi-KB inbound PUBLISH (the payload arrives across several ticks instead of monopolizing one), how many packets one tick can dispatch, and the size of the per-tick PUBACK batch. |
| `max_tx_queue_size` | `20` packets | Hard cap on pending outbound packets.  Sized for a sensor that publishes every few seconds, whose queue stays near zero.  Appending past the cap raises `MQTTBackpressureError`; protocol-internal traffic (PUBACK responses, retransmits, PINGREQ) bypasses the cap so QoS-1 / keepalive contracts hold.  Failed QoS-1 publishes roll back the `packet_id` allocation cleanly so the id pool isn't leaked on backpressure.  Raise for bursty publishers; each slot pins ~8 bytes long-lived on MP / CP. |
| `send_timeout_seconds` | inherits `ack_timeout_seconds` (5 s) | Maximum time the socket can stay non-writable with a packet queued before the client moves to `FAILED` and starts reconnecting.  Re-arms on every successful send: a steady drip never trips it, only a stalled socket does.  Catches NAT-style silent-drops on the outbound path that would otherwise let the queue grow until `MQTTBackpressureError`. |

```python
mqtt = MQTTClient(
    sock,
    client_id="my-thing",
    recv_budget_per_tick=4096,             # faster big-blob ingestion per syscall
    max_tx_queue_size=100,                 # bursty publisher
    send_timeout_seconds=10.0,             # longer outbound-stall tolerance
)
```

## Two-tier inbound size model

`chumicro-mqtt` distinguishes two tiers for inbound PUBLISH handling so a normal sensor reading is delivered intact while a hostile 1 MB blob stays heap-bounded on a 256 KB-RAM board:

| Tier | Condition | What happens |
|---|---|---|
| **Steady** | `total_length ≤ rx_buffer_size` (default 256 B) | Parsed inline from the pre-allocated RX buffer; no per-message allocation.  `on_message` fires with the full payload. |
| **Oversized** | `total_length > rx_buffer_size` | `WhenOversized` policy applies (see below).  Payload drains via rolling discard through the RX buffer, with no payload-sized heap allocation, so the heap cost is constant regardless of the inbound size. |

To receive a larger PUBLISH intact, size `rx_buffer_size` up to cover it (a few hundred bytes for sensor readings, a few KB for JSON config blobs).  Anything larger than the steady buffer is oversized and its payload is dropped: the anti-OOM guarantee.

## Oversized-message policy

`rx_buffer_size` is the steady/oversized boundary (default 256 B).  An inbound PUBLISH whose total wire size exceeds it triggers `when_oversized`:

```python
from chumicro_mqtt import MQTTClient, WhenOversized

mqtt = MQTTClient(
    sock,
    client_id="my-thing",
    rx_buffer_size=4096,                             # deliver up to 4 KB intact
    when_oversized=WhenOversized.DROP_WITH_EVENT,   # default
)
```

Three policies:

| `WhenOversized` | Behavior |
|---|---|
| `DROP_SILENT` | Drain via rolling discard, no event, stay connected. |
| `DROP_WITH_EVENT` (default) | Drain via rolling discard, fire `on_oversized(reported_length, topic)` for telemetry, stay connected.  `topic` is `None` when the topic itself was too long to parse from the RX buffer. |
| `DISCONNECT` | Raise `MQTTProtocolError`, transition to `FAILED`, appropriate when oversized inputs indicate a misconfiguration.  A client with a transport factory then reconnects. |

No payload bytes survive the oversized tier: the bytes drain through the RX buffer without any payload-sized allocation.  Diagnostic information (`reported_length` + `topic`) is enough for application-side reaction; if you need the actual bytes, raise `rx_buffer_size` so the message parses inline in the steady tier instead.

## Backpressure

When `max_tx_queue_size` is reached, user-initiated publish/subscribe calls raise `MQTTBackpressureError`:

```python
from chumicro_mqtt import MQTTBackpressureError

try:
    mqtt.publish("burst/data", payload, qos=1)
except MQTTBackpressureError:
    # The queue is full.  Let handle() send some of it, then try again
    # on a later pass of the loop.
    pass
```

The queue keeps 64 extra slots above `max_tx_queue_size` for the client's own packets (resends, PUBACKs, keepalive pings), so those never hit the cap.

## Connection state

`mqtt.state` holds one of five `ProtocolState` values, and `mqtt.last_error` holds the most recent failure.  You rarely need to check the state before calling anything, because `publish()` and `subscribe()` work in every state.  It is useful for showing status:

```python
from chumicro_mqtt import ProtocolState

if mqtt.state == ProtocolState.FAILED:
    print("MQTT is down:", mqtt.last_error)
```

| State | Meaning |
|---|---|
| `DISCONNECTED` | Before the first `connect()`, or after `disconnect()`. |
| `AWAITING_TRANSPORT` | Opening the network connection (DNS, TCP, TLS).  A client built on a ready socket skips this state. |
| `CONNECTING` | Connection open, waiting for the broker to accept the board. |
| `CONNECTED` | The broker accepted the board. |
| `FAILED` | The connection dropped or was refused.  With a transport factory the client keeps retrying unless the refusal was final (see [Reconnecting after a drop](#reconnecting-after-a-drop)). |

`disconnect()` sends the goodbye packet and closes the socket in one call, so there is no "disconnecting" state.

## Memory notes

The client actively manages its memory footprint with four caps tunable at construction time:

| Cap | Default | What it bounds |
|---|---|---|
| `recv_budget_per_tick` | `1024` bytes | Per-tick read ceiling.  See [Tuning](#tuning-responsiveness-against-throughput). |
| `rx_buffer_size` | `256` bytes | Pre-allocated steady-state RX buffer, and the steady/oversized boundary.  Inbound PUBLISHes at or below this size parse inline and deliver intact with no further allocation; above it, the [`WhenOversized` policy](#oversized-message-policy) applies and the payload drains without a payload-sized allocation. |
| `pre_connect_queue_size` | `8` packets | Bound on the pre-connect publish queue (the `when_disconnected="queue"` buffer).  See [Publishing before connected](#publishing-before-connected). |
| `max_tx_queue_size` | `20` packets | Outbound packet queue cap.  See [Backpressure](#backpressure). |

The QoS-1 in-flight table (keyed by `packet_id`, one entry per outstanding QoS-1 PUBLISH waiting for PUBACK) grows with your usage and has no hard cap.  On memory-tight boards, keep `rx_buffer_size` at your actual largest expected broker payload; anything bigger routes through the oversized tier where it can't blow the heap.

### What fits in the 256 B steady-state buffer

The decoder sees the whole MQTT packet, not just the payload: `1` (fixed byte) `+ 1–2` (varlen) `+ 2` (topic-length field) `+ len(topic)` `+ 0/2` (packet_id when QoS 1) `+ len(payload)`.  At a glance:

| Use case | Wire size | Tier |
|---|---|---|
| Plain sensor reading: `home/livingroom/temp` `21.3` | ~30 B | steady |
| Small JSON sensor: `home/livingroom/sensor` `{"t":21.3,"h":45}` | ~45 B | steady |
| Device-prefixed status: `livingRoom/mainLightSwitch/online` `false` | ~45 B | steady |
| Multi-field JSON: `home/livingroom/env` `{"temp":21.3,"hum":45,"pressure":1013,"co2":412}` | ~75 B | steady |
| Verbose JSON sensor (~150 B payload, 20 B topic) | ~175 B | steady (default rx) |
| HomeAssistant discovery (`homeassistant/.../config` + ~300 B JSON) | ~350 B | steady at `rx_buffer_size=512` |
| AWS IoT Core shadow `update/accepted` (~250–600 B JSON) | ~300–700 B | steady at `rx_buffer_size=1024` |

So **plain sensor data, small-to-medium JSON readings (payload ≤ ~200 B on a ≤ 40 B topic), and device-prefixed status messages all parse inline at the 256 B default with zero per-message allocation.**  Structured-config workloads (HomeAssistant discovery descriptors, AWS IoT shadow documents, MQTT-SN gateway state) deliver intact once `rx_buffer_size` is sized to cover them: the buffer is allocated once at construction, not per message.  If your typical PUBLISH is consistently above ~250 B, bump `rx_buffer_size` (e.g. `512` or `1024`) so it stays in the steady tier; anything above the buffer routes through the oversized tier and its payload is dropped.

## Platform notes

| Runtime | TCP | TLS | Notes |
|---|---|---|---|
| CPython | ✅ | ✅ | Reference runtime; works against any broker. |
| MicroPython | ✅ | ✅ | mbedTLS PEM→DER conversion on rp2 (handled by `chumicro-sockets`). |
| CircuitPython | ✅ (requires `radio=wifi.radio`) | ✅ | TLS handshake runs inside one `handle()` call, measured under 15 ms on both Lolin S2 and Pi Pico W against `test.mosquitto.org:8883` over a good wifi link. |

MicroPython sockets start out blocking, and a blocking `recv` against a silent broker on a Pi Pico W stalls your loop indefinitely.  `MQTTClient` switches every socket it receives to non-blocking mode.  When you pass your own socket, call `sock.setblocking(False)` yourself as well, so the requirement shows where the socket is made.

## Examples

Each example's docstring explains how to run a Mosquitto broker on your laptop and watch the traffic.

| Example | What it shows |
|---|---|
| [`examples/telemetry.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt/examples/telemetry.py) | Start here.  Publishes a reading every five seconds at QoS 1, prints each broker confirmation, and prints any command sent to `chumicro-demo/cmd`.  Stop the broker and it holds readings, then reconnects and sends them.  CircuitPython and MicroPython. |
| [`examples/receive_stream.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt/examples/receive_stream.py) | Receives with `next_message()` in a generator task run by `chumicro-runner`, printing each command as it arrives.  CircuitPython and MicroPython. |
| [`examples/bench.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt/examples/bench.py) | A one-shot test run against a real broker: small and oversized incoming messages, an oversized topic, a QoS 1 round trip, a burst, and keepalive, then a pass/fail table with heap use and loop latency per scenario.  The laptop-side [`examples/bench_host.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt/examples/bench_host.py) (needs `pip install paho-mqtt`) collects the verdict and can send a 64 KB message to test the oversized path. |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt) · \
[PyPI](https://pypi.org/project/chumicro-mqtt/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
