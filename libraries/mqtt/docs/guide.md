# User Guide

## Overview

`chumicro-mqtt` is an MQTT 3.1.1 client for CircuitPython, MicroPython, and CPython.  MQTT is a publish/subscribe protocol.  Every device connects to a *broker*, publishes messages to named *topics*, and subscribes to the topics it wants to hear.  The broker passes each message on, so devices never talk to each other directly.

`MQTTClient` never makes the program wait on the network.  On every pass, the main loop asks `mqtt.check(now_ms)` whether the client has work to do.  `mqtt.handle(now_ms)` then does one small step of it: dial the broker, send a queued message, read what has arrived, keep the connection alive, or reconnect after a drop.  Then `handle()` returns, so an LED keeps blinking and a button keeps answering while a message is on its way.

The client supports QoS 0 and QoS 1, retained messages, a last will, wildcard subscriptions, and TLS.  QoS 2 raises `UnsupportedQoSError`.

## Getting started

This program joins wifi, publishes a reading every five seconds, and prints every message sent to `demo/cmd`:

```python
from chumicro_mqtt import MQTTClient
from chumicro_timing import Rate, ticks_ms
from chumicro_wifi import WifiConfig, WifiService

wifi = WifiService(WifiConfig(ssid="your-wifi-ssid", password="your-wifi-password"))
while not wifi.connected:  # join wifi before dialing the broker
    now_ms = ticks_ms()
    if wifi.check(now_ms):
        wifi.handle(now_ms)

# CircuitPython needs radio=, and MicroPython ignores it.
mqtt = MQTTClient.from_config(
    {"mqtt.broker.host": "192.168.1.20", "mqtt.broker.port": 1883},
    radio=wifi.adapter.radio,
)


def on_message(topic, payload):
    print(topic, payload)


mqtt.on_message = on_message
mqtt.subscribe("demo/cmd")
mqtt.connect()

publish_timer = Rate(5000, ticks_ms())

while True:
    now_ms = ticks_ms()
    if wifi.check(now_ms):  # rejoin wifi after a drop
        wifi.handle(now_ms)
    if mqtt.check(now_ms):
        mqtt.handle(now_ms)
    if publish_timer.due(now_ms):
        mqtt.publish("demo/temperature", "21.5", qos=1)
```

- `WifiService` joins the network and rejoins after a drop.  The [`chumicro-wifi` guide](https://chumicro.com/ChuMicro/wifi/stable/guide/) covers it.
- `MQTTClient.from_config(...)` reads the broker address and builds a client that dials the broker without stopping the loop, and dials again after a drop.  The client id comes from the board's chip id ([Client ids](#client-ids)).
- `on_message(topic, payload)` runs for every message that arrives on a subscribed topic.  `payload` is `bytes`.
- `subscribe()` can come before `connect()`.  The client remembers the topic, asks the broker for it as soon as the broker accepts the board, and asks again after every reconnect.
- `connect()` starts dialing and returns at once.  The `handle()` calls in the loop carry the connection through.
- `publish()` works at any moment.  Before the broker has answered, the message waits in a queue and goes out on connect ([Publishing before connected](#publishing-before-connected)).
- `Rate(5000, ticks_ms())` is a `chumicro-timing` timer whose `due(now_ms)` turns `True` once every 5000 ms.

[`examples/telemetry.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt/examples/telemetry.py) is the full version of this program, with a broker on a laptop and a printed line for every reconnect.

Create the client near the top of the program.  The first use of `MQTTClient` loads the client code into RAM.  That load fits best while the heap is still nearly empty.

### With a runner

A [`chumicro-runner`](https://chumicro.com/ChuMicro/runner/stable/guide/) `Runner` makes the `check()` and `handle()` calls itself.  Its `wait()` rests the CPU until the broker sends something or a timer is due.  This loop replaces the final `while True:` loop above:

```python
from chumicro_runner import Runner


def publish_reading(now_ms):
    mqtt.publish("demo/temperature", "21.5", qos=1)


runner = Runner()
runner.add(wifi)                                      # rejoins wifi after a drop
runner.add(mqtt)                                      # calls check() and handle()
runner.add_periodic(publish_reading, period_ms=5000)  # every five seconds

while True:
    now_ms = runner.tick()   # every added job takes one small step
    runner.wait(now_ms)      # then the CPU rests until broker traffic or the next timer
```

## Client ids

Every MQTT connection carries a client id.  A broker treats the client id as the identity of the session.  A device with a meaningful name passes its own, as `client_id=` or as `mqtt.client_id` in the config:

```python
mqtt = MQTTClient.from_config(
    {"mqtt.broker.host": "192.168.1.20", "mqtt.broker.port": 1883},
    client_id="greenhouse-sensor-1",
)
```

Without one, `MQTTClient.from_config` calls `default_client_id()`, which builds an id from the board's hardware UID:

```python
from chumicro_mqtt import default_client_id

default_client_id()               # "chumicro-e8db84a1b2c3"
default_client_id("greenhouse")   # "greenhouse-e8db84a1b2c3"
```

The id differs between boards and stays the same across reboots, so a persistent session resumes after a power cycle.  The UID comes from `microcontroller.cpu.uid` on CircuitPython, `machine.unique_id()` on MicroPython, and the host's MAC address through `uuid.getnode()` on CPython.

When none of those lookups works, the function returns the fixed string `<prefix>-mqtt`.  Two boards with that same id connect as the same client.  A broker answers a duplicate client id by disconnecting the earlier session, so the two boards keep knocking each other off the broker while each one looks healthy on its own.  To check, print `default_client_id()` on both boards.  A result of `chumicro-mqtt` means the lookup failed.  Each board then needs its own `client_id`.

## Publishing

`publish(topic, payload)` sends `payload` to `topic`.  The payload is `bytes`, or a `str` the client encodes as UTF-8.  The `qos` argument picks the quality of service.  QoS 0 sends the message once and moves on.  QoS 1 keeps the message until the broker confirms it with a PUBACK packet, and resends it when the confirmation is late.  `retain=True` asks the broker to keep the message and hand it to every later subscriber of the topic, which suits a status such as "online".

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

`on_publish(topic, payload)` receives the topic and payload that went out.  For QoS 1 it runs when the broker's PUBACK arrives.  For QoS 0 it runs once the bytes are sent.  A QoS 1 message the client had to resend still runs `on_publish` once.  A function assigned to `mqtt.on_publish` runs for every published message.

### Publishing before connected

Connecting takes several passes of the loop, so `publish()` can run while the client is still coming up or reconnecting after a drop.  The `when_disconnected=` constructor argument decides what happens then:

| `when_disconnected` | Before CONNECTED |
|---|---|
| `"queue"` (default) | Hold the message in a pre-connect queue of `pre_connect_queue_size` messages.  The queue goes out, oldest first, as soon as the broker accepts the board, ahead of anything `on_connect` publishes.  A full queue raises `MQTTBackpressureError`. |
| `"raise"` | Raise `MQTTError` at once. |

A queued message keeps its `qos` and `retain`.  Its `on_publish` runs once it is sent.  `subscribe()` and `unsubscribe()` skip this queue.  The client keeps a list of wanted topics and sends it on every connect ([Subscribing and routing](#subscribing-and-routing)).

## Subscribing and routing

`subscribe(topic)` asks the broker for every message on `topic`.  `on_message(topic, payload)` runs for each one that arrives.  A topic filter can hold wildcards: `+` matches one level and `#` matches every level below it.

```python
mqtt.on_message = lambda topic, payload: print(topic, "=>", payload)
mqtt.subscribe("commands/+")             # commands/set, commands/reset, ...
mqtt.subscribe("status/#", qos=1)        # status/door, status/door/battery, ...
```

`subscribe()` works in every state: before `connect()`, inside `on_connect`, or while connected.  The client adds the topic to its list of wanted topics and sends the request at once when connected, or else as soon as the broker accepts the board.  After a reconnect it sends the whole list again, so messages keep arriving with no extra code.  The optional `on_subscribe(topic, granted_qos)` callback runs once, when the broker first grants the topic.  `unsubscribe(topic)` removes a topic from the list and tells the broker when connected.

`topic_matches(topic, pattern)` applies the same wildcard rules, so `on_message` can branch on the topic:

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

A client receives through `on_message` or through `next_message()`, one or the other.

### Receive stream (`next_message`)

`next_message()` reads messages in a plain loop inside a [generator task](https://chumicro.com/ChuMicro/runner/stable/guide/#generator-tasks).  `message = yield from mqtt.next_message()` pauses the task until a message arrives, while the rest of the board keeps running:

```python
from chumicro_mqtt import MQTTClient
from chumicro_runner import Runner
from chumicro_wifi import WifiConfig, WifiService

runner = Runner()
wifi = WifiService(WifiConfig(ssid="your-wifi-ssid", password="your-wifi-password"))
runner.add(wifi)
while not wifi.connected:  # join wifi before dialing the broker
    now_ms = runner.tick()
    runner.wait(now_ms)

mqtt = MQTTClient.from_config(
    {"mqtt.broker.host": "192.168.1.20", "mqtt.broker.port": 1883},
    radio=wifi.adapter.radio,
)
mqtt.subscribe("commands/+")
mqtt.connect()


def print_commands():
    while True:
        message = yield from mqtt.next_message()   # wait for the next message
        if message is None:
            return                                 # the client stopped for good
        print(message.topic, message.payload)


runner.add(mqtt)                         # the client's network work
runner.add_generator(print_commands())   # the receiving loop above

while True:
    now_ms = runner.tick()   # each added job takes one small step
    runner.wait(now_ms)      # then the CPU rests until a message or timer is due
```

`next_message()` returns an `InboundPublish` with `topic` and `payload`.  The first call turns `on_message` off and delivers messages to a queue the generator reads.  The queue holds 16 messages.  When the generator falls behind, the client drops the oldest message, so the heap stays the same size.  `next_message()` returns `None` once the client has stopped for good: after `disconnect()`, after the broker refuses the board outright, as for bad credentials, or after a drop on a client with no way to reconnect.  `examples/receive_stream.py` is the full program.

`on_connect`, `on_disconnect`, and `on_oversized` keep running with either way of receiving.  `on_disconnect()` runs when a working connection ends, through `disconnect()` or a dropped link.  By then `mqtt.last_error` says why.  Failed attempts to reconnect run no callback, so one outage runs `on_disconnect()` once.

## Last will

A last will is a message the board leaves with the broker when it connects.  When the board later drops off without a clean `disconnect()`, through a power cut, a wifi loss, or a crash, the broker publishes the will on the board's behalf.  Paired with a retained `online` published from `on_connect`, the will tells anything watching whether the board is there:

```python
STATUS_TOPIC = "devices/sensor-1/status"

mqtt.set_will(STATUS_TOPIC, b"offline", qos=1, retain=True)


def on_connect():
    mqtt.publish(STATUS_TOPIC, b"online", qos=1, retain=True)


mqtt.on_connect = on_connect
mqtt.connect()
```

A clean `disconnect()` cancels the will.  The broker keeps the will it received for the current connection, so `set_will()` takes effect on the next connect, reconnects included.  `set_will(None)` turns the will off.  A client built with `MQTTClient(...)` also takes the will as `will_topic=`, `will_message=`, `will_qos=`, and `will_retain=` arguments.

## TLS connections

With an `ssl_context=` passed to `from_config`, the client dials the broker over TLS:

```python
from chumicro_sockets import ssl_context_with_ca

with open("/ca.pem", "rb") as handle:
    ca_pem = handle.read()
ssl_context = ssl_context_with_ca(ca_pem)         # checks the broker's certificate
mqtt = MQTTClient.from_config(
    {"mqtt.broker.host": "broker.example.com", "mqtt.broker.port": 8883},
    ssl_context=ssl_context,
    radio=wifi.adapter.radio,
)
```

The `chumicro-sockets` guide's [TLS](https://chumicro.com/ChuMicro/sockets/stable/guide/#tls) section covers certificates on each runtime.  Two steps of a connection attempt stop the whole loop while they run, because each runs inside one `handle()` call:

* **The TLS handshake.**  A sensor read, a watchdog feed, or a blinking LED waits until it finishes.  Against `test.mosquitto.org:8883` on a good wifi link it took 2 to 3 ms on a Lolin S2 and 10 to 11 ms on a Pi Pico W, both on CircuitPython.  On a slow link, or against an unreachable broker, it can take seconds.  Connect before starting anything timing-critical, or allow for the pause.
* **The DNS lookup.**  Turning `broker.example.com` into an address waits on the board's resolver, which can hang until its own timeout when DNS is slow or down.  An IP address in `mqtt.broker.host` skips the lookup.

The `chumicro-sockets` [Platform notes](https://chumicro.com/ChuMicro/sockets/stable/guide/#platform-notes) list which connect steps wait on each runtime.

## Reconnecting after a drop

A client built with `from_config()` reconnects by itself.  When the broker goes away or the wifi drops, the client notices, because the socket closes or an expected reply misses its deadline.  It runs `on_disconnect()` and starts dialing again from inside `handle()`.  The first attempt goes out at once.  After that, the wait between attempts doubles from 1 second up to once a minute, so a long outage neither floods the broker nor drains a battery.  A successful connect resets the wait, runs `on_connect()` again, re-sends the subscriptions, and sends what `publish()` queued in the meantime.

The client stops retrying when the broker refuses it for a reason that retrying cannot fix.  The broker's reply to a connect, CONNACK, then carries return code 1, 2, 4, or 5: unacceptable protocol version, identifier rejected, bad username or password, or not authorized.  `mqtt.last_error` holds an `MQTTConnectError` naming the code.  The next `connect()` call tries again.  Return code 3, server unavailable, keeps retrying.  A subscription the broker refuses is dropped from the list of wanted topics, so a reconnect skips it.

To reconnect, the client needs a way to open a fresh connection.  `from_config()` gives it a *transport factory*: a function that returns a new connector for the broker each time it is called.  To build one by hand, pass `transport_factory=` to `MQTTClient(...)`:

```python
from chumicro_sockets import connector

def make_connector():
    return connector("broker.example.com", 1883, radio=wifi.adapter.radio)

mqtt = MQTTClient(transport_factory=make_connector, client_id="my-thing")
mqtt.connect()
```

A client built on a bare socket has no way to reconnect.  When that socket dies, the client stops in the `FAILED` state.  Only a new client connects again.

Each connection attempt moves one step per `handle()` call.  The DNS lookup and the TLS handshake are the exceptions.  Each of those runs to completion inside one call ([TLS connections](#tls-connections)).

### Telling the client when wifi drops or returns

`connect()` is safe to call in any state:

- **Disconnected**: starts connecting.
- **`FAILED`**: reconnects at once, skipping whatever is left of the wait between attempts.
- **Connected or connecting**: does nothing, so a second dial never races the first.

`hold()` pauses automatic reconnects until the next `connect()`.  A held client stays `FAILED` and keeps `last_error`.  `publish()` still queues while the client is held.  A runner's `wait()` stops waking up for retries that cannot succeed.

`MQTTClient` never watches the wifi.  A program that does can tell the client.  `hold()` stops the client dialing through a dead radio.  On ESP32 boards those dials can get in the way of the radio rejoining the network.  `connect()` dials at once when the link is back, instead of waiting out the backoff.  With `chumicro-wifi`, each direction takes one line:

```python
from chumicro_wifi import WifiState

def on_wifi_state(old, new):
    if new == WifiState.CONNECTED:
        mqtt.connect()    # link is back: reconnect now (also clears the hold)
    else:
        mqtt.hold()       # link is down: stop dialing a dead radio

# WifiService reports a lost link as RECONNECTING, then FAILED once its
# retries run out, so every state other than CONNECTED means the link is down.
wifi.on_state_change(on_wifi_state)
```

The client reconnects on its own without these calls.  `hold()` and `connect()` make it react sooner when the program knows more than the client's timer does.

### Which messages survive a drop

The client takes a moment to notice a dead link, because a missing reply has to time out first.  What happens to a message depends on whether `publish()` ran before or after the client noticed:

- **Before**, while `mqtt.state` still reads `CONNECTED`: the message goes out on the dead connection and never gets its PUBACK.  With the default `clean_session=True`, the reconnect starts a fresh session on both ends and the message is lost.  With `clean_session=False` and a broker that keeps sessions, the client resends it instead.
- **After**, once the state is `FAILED` or the client is reconnecting: the message waits in the pre-connect queue and goes out, oldest first, as soon as the broker accepts the board again.

An outage can lose the last message or two published before the client noticed.  Everything published after that arrives.  A loop free of long blocking calls lets the client notice sooner and loses less.

## Bring your own transport

`MQTTClient` works with a socket from any library.  The client calls these four methods on it:

| Method | Contract |
|---|---|
| `recv_into(buffer, nbytes) -> int` | Reads up to `nbytes` into `buffer` (a `memoryview`).  Raises `OSError(EAGAIN \| EWOULDBLOCK)` when no data is waiting, returns 0 when the peer closed, and otherwise returns the number of bytes written. |
| `send(payload) -> int` | Sends `payload`, a `bytes` or, when resuming a partial send, a `memoryview` slice of one.  Raises `OSError(EAGAIN \| EWOULDBLOCK)` when the send buffer is full, and otherwise returns the number of bytes sent, which may be fewer than all of them. |
| `close() -> None` | Releases the connection. |
| `setblocking(flag) -> None` | Optional.  The client calls it when the socket has it. |

The socket a `chumicro_sockets.connector` leaves on `.socket` once its state is `"ready"` works.  So does a stdlib `socket.socket` after `setblocking(False)`, a wrapper around another library's socket, or a hand-written fake:

```python
# A stdlib socket on CPython, for a test or a desktop script.
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(("broker.example.com", 1883))
sock.setblocking(False)
mqtt = MQTTClient(sock, client_id="desktop-demo")
```

A ready-made socket suits a desktop script or a test that already owns the connect.  `sock.connect()` blocks while it runs, and a client built on that socket cannot reconnect.  A board program that must keep its loop moving uses the `transport_factory` form from [Reconnecting after a drop](#reconnecting-after-a-drop).

The client checks no types: any object with these four methods works.  An object that lacks one fails at the first call to it.

A program that supplies its own transport can keep `chumicro_sockets` off the board with one line in `code.py` or `app.py`:

```python
__chumicro_skip_factories__ = ("sockets_factory",)
```

[Slimming your deploy](https://chumicro.com/ChuMicro/guides/contributing/slimming-your-deploy/) explains the line.  On a board without `chumicro_sockets.sockets_factory`, `MQTTClient.from_config(...)` raises `RuntimeError` asking for `transport_factory=` or `socket=`.

With its own transport, its own clock passed as `ticks=`, and `check()` and `handle()` called from a plain loop, the client needs no other ChuMicro library.  Host tests drive it the same way with no board attached.

## Tuning

Each `handle()` call makes one `recv_into` and sends one queued packet, so every call does a small, fixed amount of socket work.  A call that received QoS 1 messages also sends their PUBACK replies, all in one extra send outside that one-packet limit.  The replies therefore keep pace with the incoming messages.  When the socket cannot take that send, the client stops reading until it goes out.  The unread bytes then slow the broker through TCP flow control.

These constructor arguments set the limits:

| Argument | Default | What it bounds |
|---|---|---|
| `rx_buffer_size` | `256` bytes | The receive buffer, allocated once.  A message that fits is delivered whole.  [Large incoming messages](#large-incoming-messages) covers the rest. |
| `recv_budget_per_tick` | `1024` bytes | The most one `recv_into` reads.  Each read also stops at the free space in the receive buffer, so the budget matters only when `rx_buffer_size` is larger.  Then it spreads a multi-KB incoming message over several calls, and caps how many packets and PUBACKs one call handles. |
| `max_tx_queue_size` | `20` packets | Outgoing packets waiting to be sent, sized for a sensor that publishes every few seconds and keeps its queue near empty.  Each slot holds about 8 bytes on a board.  [Sending in bursts](#sending-in-bursts) covers a full queue. |
| `pre_connect_queue_size` | `8` messages | Messages `publish()` holds before the broker accepts the board ([Publishing before connected](#publishing-before-connected)). |
| `send_timeout_seconds` | `ack_timeout_seconds`, 5 s | The longest the socket may refuse writes while a packet waits.  Past it, the client moves to `FAILED` and reconnects.  Every successful send restarts the timer, so only a stalled socket trips it, such as a connection a router dropped without telling either end. |

`from_config()` passes each of these through to the constructor:

```python
mqtt = MQTTClient.from_config(
    {"mqtt.broker.host": "192.168.1.20", "mqtt.broker.port": 1883},
    radio=wifi.adapter.radio,
    rx_buffer_size=4096,         # deliver messages up to 4 KB whole
    recv_budget_per_tick=4096,   # read up to 4 KB per handle() call
    max_tx_queue_size=100,       # a bursty publisher
    send_timeout_seconds=10.0,   # wait longer on a slow uplink
)
```

## Large incoming messages

The client reads every incoming PUBLISH packet into its receive buffer of `rx_buffer_size` bytes.  A packet that fits arrives in `on_message` whole, with no memory allocated per message.  A larger packet is *oversized*.  The client reads its bytes through the same buffer and throws them away, so a 1 MB message costs a 256 KB board no more memory than a small one.  The `when_oversized=` constructor argument then decides what else happens:

```python
from chumicro_mqtt import WhenOversized

mqtt = MQTTClient.from_config(
    {"mqtt.broker.host": "192.168.1.20", "mqtt.broker.port": 1883},
    rx_buffer_size=4096,                             # deliver up to 4 KB whole
    when_oversized=WhenOversized.DROP_WITH_EVENT,    # the default
)
```

| `WhenOversized` | What happens |
|---|---|
| `DROP_SILENT` | Drop the message and stay connected. |
| `DROP_WITH_EVENT` (default) | Drop the message, call `on_oversized(reported_length, topic)`, and stay connected.  `topic` is `None` when the topic itself was too long to fit the buffer. |
| `DISCONNECT` | Treat the message as a protocol error.  The client moves to `FAILED` with an `MQTTProtocolError` in `last_error`, which suits a setup where an oversized message means a misconfiguration.  A client with a transport factory then reconnects. |

Both drop policies still send the PUBACK for a QoS 1 message, so the broker stops resending it.  To receive a larger message whole, raise `rx_buffer_size` to cover it.

### What fits in 256 bytes

The buffer holds the whole packet: 1 byte of packet type, 1 or 2 bytes of length, 2 bytes of topic length, the topic, 2 bytes of packet id for QoS 1, and the payload.

| Message | Packet size | Fits |
|---|---|---|
| Plain sensor reading: `home/livingroom/temp` `21.3` | ~30 B | 256 B default |
| Small JSON sensor: `home/livingroom/sensor` `{"t":21.3,"h":45}` | ~45 B | 256 B default |
| Device status: `livingRoom/mainLightSwitch/online` `false` | ~45 B | 256 B default |
| Multi-field JSON: `home/livingroom/env` `{"temp":21.3,"hum":45,"pressure":1013,"co2":412}` | ~75 B | 256 B default |
| Verbose JSON sensor, ~150 B payload on a 20 B topic | ~175 B | 256 B default |
| Home Assistant discovery, `homeassistant/.../config` with ~300 B of JSON | ~350 B | `rx_buffer_size=512` |
| AWS IoT Core shadow `update/accepted`, ~250 to 600 B of JSON | ~300 to 700 B | `rx_buffer_size=1024` |

Sensor readings, JSON payloads up to about 200 bytes on a topic up to about 40 bytes, and status messages fit the 256-byte default.  The client allocates the buffer once, at construction, so a larger `rx_buffer_size` costs its size once and nothing per message.

## Sending in bursts

When `max_tx_queue_size` packets already wait, `publish()`, `subscribe()`, and `unsubscribe()` raise `MQTTBackpressureError`:

```python
from chumicro_mqtt import MQTTBackpressureError

try:
    mqtt.publish("burst/data", payload, qos=1)
except MQTTBackpressureError:
    # The queue is full.  Let handle() send some of it, then try again
    # on a later pass of the loop.
    pass
```

The queue keeps 64 extra slots above `max_tx_queue_size` for the client's own packets: resends, PUBACKs, and keepalive pings.  The client's own traffic therefore always fits.

## Connection state

`mqtt.state` holds one of five `ProtocolState` values.  `mqtt.last_error` holds the most recent failure.  `publish()` and `subscribe()` work in every state, so code rarely checks the state before a call.  The state suits a status display:

```python
from chumicro_mqtt import ProtocolState

if mqtt.state == ProtocolState.FAILED:
    print("MQTT is down:", mqtt.last_error)
```

| State | Meaning |
|---|---|
| `DISCONNECTED` | Before the first `connect()`, or after `disconnect()`. |
| `AWAITING_TRANSPORT` | Opening the network connection: DNS, TCP, and TLS.  A client built on a ready socket skips this state. |
| `CONNECTING` | Connection open, waiting for the broker to accept the board. |
| `CONNECTED` | The broker accepted the board. |
| `FAILED` | The connection dropped or was refused.  With a transport factory the client keeps retrying, unless the refusal was final ([Reconnecting after a drop](#reconnecting-after-a-drop)). |

`disconnect()` sends the DISCONNECT packet and closes the socket in one call, so the client goes straight to `DISCONNECTED`.

`MQTTConnectError`, `MQTTProtocolError`, `MQTTBackpressureError`, and `UnsupportedQoSError` all subclass `MQTTError`, so one `except MQTTError:` catches any of them.

## Memory notes

The client allocates its receive buffer once, at `rx_buffer_size` bytes, and parses every message that fits in place.  The outgoing queue and the pre-connect queue hold at most the counts set in [Tuning](#tuning).  The client also keeps one entry per QoS 1 message still waiting for its PUBACK.  That table has no cap.  On a board short of memory, set `rx_buffer_size` to the largest message the broker sends, and let anything larger take the oversized path.

## Platform notes

| Runtime | TCP | TLS |
|---|---|---|
| CPython | ✅ | ✅ |
| MicroPython | ✅ | ✅ |
| CircuitPython | ✅, with `radio=` | ✅, with `radio=` |

MicroPython sockets start out blocking.  A blocking `recv` against a silent broker on a Pi Pico W stalls the loop indefinitely.  `MQTTClient` switches every socket it receives to non-blocking mode.  A socket passed in by hand should also get `sock.setblocking(False)` where it is made, so the requirement shows at that line.

## Examples

Each example's docstring explains how to run a Mosquitto broker on a laptop and watch the traffic.

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
