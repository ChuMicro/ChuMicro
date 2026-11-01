---
title: "CircuitPython and MicroPython questions: blocking, WiFi, MQTT, and storage"
---

# Questions people ask

## Why does my board freeze while it talks to the network?

Most Python libraries for boards stop the whole program while they
wait.  A request to a slow server holds the processor until the
server answers.  A WiFi retry against an unplugged router holds it
until the retry gives up.  Every other job on the board waits too:
the status LED, the button, the sensor read.

A ChuMicro library does a small piece of its job on each pass of your
loop, then hands control straight back.  The LED keeps blinking and
the button keeps answering while the network is slow.  Your code sets
how long to wait and what happens when the time runs out.

A few connection steps still wait.
[Does anything ever block?](#does-anything-ever-block) lists them.

## Where did time.sleep() go?

ChuMicro programs check the clock instead of sleeping.
`time.sleep(1)` stops the whole board for a second.  A sleeping
program reads no buttons and answers no network.  `Rate.due(now)`
from [chumicro-timing](https://chumicro.com/ChuMicro/timing/stable/)
returns `True` once per period.  The loop runs everything else in
between.

The loop is still a `while True:` at the bottom of your program.  Once
it runs several jobs, a `Runner` from
[chumicro-runner](https://chumicro.com/ChuMicro/runner/stable/) keeps
their schedule.  `runner.wait()` sleeps only until the next job is
due.

[Coming from Arduino](coming-from-arduino.md) walks through blink,
buttons, timers, and WiFi side by side with Arduino and Adafruit Learn
code.

## How do I use MQTT on CircuitPython without freezing everything else?

MQTT is the publish-and-subscribe protocol most home-automation setups
speak.  Add an `MQTTClient` from
[chumicro-mqtt](https://chumicro.com/ChuMicro/mqtt/stable/) to a runner
beside the rest of your program.

The client sends, receives, and keeps the connection alive a little at
a time on each pass.  An LED keeps blinking while the client waits for
the broker.

```python
import board
import digitalio
from chumicro_config import load_runtime_config
from chumicro_mqtt import MQTTClient
from chumicro_runner import Runner
from chumicro_wifi import WifiService

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

config = load_runtime_config()   # wifi and broker settings from secrets.toml
wifi = WifiService.from_config(config)
mqtt = MQTTClient.from_config(config, radio=wifi.adapter.radio)
mqtt.connect()                   # returns at once, before the broker answers


def blink(now_ms):
    led.value = not led.value


def publish_reading(now_ms):
    mqtt.publish("home/porch/temperature", b"21.5")


runner = Runner()
runner.add(wifi)
runner.add(mqtt)
runner.add_periodic(blink, period_ms=500)
runner.add_periodic(publish_reading, period_ms=10_000)

while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

[`radio=`](glossary.md#radio) hands the client the WiFi radio that
CircuitPython builds its sockets from.  A reading published before the
broker answers waits in a queue of up to eight messages.  It goes out once the client connects.  The client
reconnects on its own after a drop.  It also supports QoS 0 and 1,
last will, retained messages, and TLS.
[Wiring WiFi credentials](wiring-wifi-credentials.md#adding-an-mqtt-broker)
shows the `secrets.toml` entries for the broker.

## Does this use async and await?

No.  ChuMicro libraries are plain objects that your `while True:` loop
calls.  No library uses `async def`, `await`, or the `asyncio` module.
A program built on `asyncio` can still drive them: one of its tasks
calls a library's `check(now_ms)` and `handle(now_ms)`.

The libraries avoid `async` to save memory on CircuitPython.
CircuitPython compiles every `await` into a method call that builds a
new generator object each time it runs.  On a 256 KB board, those
objects churn the heap.  MicroPython compiles the same `await` to a
single bytecode.  For a task that reads best as steps in order, the
libraries use generators with `yield from`, which compiles to one
bytecode on both runtimes.

## How do I keep WiFi connected on a Pico W or an ESP32?

Add a `WifiService` from
[chumicro-wifi](https://chumicro.com/ChuMicro/wifi/stable/) to your
runner.  The service joins your network and rejoins on its own after a
drop.  After a failed join, it waits 1 second before the next try.
Each further failure doubles the wait, up to a minute.

On every change of state, the service calls your callback with the old
and the new state: `disconnected`, `connecting`, `connected`,
`reconnecting`, or `failed`.  It reaches `failed` only after a retry
limit you set with `reconnect_max`.

[CircuitPython auto-connect](wiring-wifi-credentials.md#circuitpython-auto-connect)
explains why `CIRCUITPY_WIFI_SSID` stays out of `settings.toml`.
[Coming from Arduino](coming-from-arduino.md#wifi-that-comes-back-wifiservice)
has a complete program that blinks an LED through a router outage.

## Does anything ever block?

Yes.  A few network calls in the board's firmware come only in a form
that waits.  On CircuitPython, `wifi.radio.connect()` waits until it
joins or times out.  Each WiFi join attempt holds your loop for up to
`connect_timeout_ms`, 15 seconds by default.  On ESP32 and Pico W,
MicroPython joins in the background while your loop keeps running.

Opening a connection to a server also waits in pieces.  The server
name lookup waits in one call on both runtimes.  The TLS handshake,
the setup behind `https://`, waits in another.  On CircuitPython, the
plain TCP connect also waits in one call.  Your loop runs between
those pieces.  Once the connection is open, sending, receiving,
keepalives, and timeouts run a step at a time on both runtimes.

## Can I run the same code on CircuitPython and MicroPython?

The library code, yes.  Every ChuMicro library runs on CircuitPython,
MicroPython, and the Python on your laptop.  Your pin setup changes,
because each runtime names pins its own way.  CircuitPython uses
`board` and `digitalio`.  MicroPython uses `machine.Pin`.  The rest of
the program stays the same.

[Coming from Arduino](coming-from-arduino.md#on-micropython) shows
the MicroPython pin lines for an LED and a button.

## Why does my button miss presses while the board is doing other work?

Reading a pin returns its level at that moment.  A tap that starts and
ends between two reads leaves no trace.

[chumicro-buttons](https://chumicro.com/ChuMicro/buttons/stable/)
watches the pin in the background.  On CircuitPython, the firmware's
`keypad` module does the watching.  On MicroPython, a pin interrupt
does.  Each press waits for your next `check()`, stamped with the time
it happened.  A long hold reads as long even when the loop was slow to
look.  Debouncing, long presses, auto-repeat, and click counting are
built in.

[chumicro-knobs](https://chumicro.com/ChuMicro/knobs/stable/) counts a
rotary encoder's steps the same way, so a fast spin arrives whole.

## How do I store a value that survives a reboot?

Use [chumicro-kvstore](https://chumicro.com/ChuMicro/kvstore/stable/).
A `KVStore` reads and writes like a dictionary.  It keeps values in
the storage the board has: CircuitPython's non-volatile memory
(`microcontroller.nvm`), ESP32's NVS key-value area on MicroPython, a
file on other MicroPython boards, and plain memory on your laptop.

`commit_if_changed()` writes to flash only when a value changed, so it
is safe to call on every pass of your loop.

## How much space do these take on a board?

Each library takes between about 1 KB and 31 KB of flash, compiled to
MicroPython bytecode.  CI holds every library under a ceiling: at most
2,595 bytes for `chumicro-timing`, 7,339 for `chumicro-wifi`, and
30,892 for `chumicro-websockets`, the largest.  A board with 2 MB of
flash has roughly 800 KB left for your files once the firmware is on
it.

A project that needs a timer installs only `chumicro-timing`.

## How do I install one library on a board?

Use circup on CircuitPython, mip on MicroPython, and pip on your
laptop, each with the library's name.  circup needs the ChuMicro
bundle registered once before it finds ChuMicro libraries.

[Installing libraries](install.md#quick-install-stable-channel) has the
command for each runtime.

## Can I test my project without hardware?

Yes.  Every library runs on the Python on your laptop.  The libraries'
`testing` modules ship stand-ins for the parts that need a board: a
fake clock you move forward by hand, a fake socket, a fake WiFi radio,
and a fake button the test presses.

A test moves the fake clock forward instead of sleeping, so a test of
a 30-second timeout finishes in milliseconds.

```python
from chumicro_timing import Deadline
from chumicro_timing.testing import FakeTicks


def test_light_turns_off_after_five_seconds():
    clock = FakeTicks()
    timer = Deadline(5000, clock.ticks_ms())
    clock.advance(4999)
    assert not timer.expired(clock.ticks_ms())
    clock.advance(1)
    assert timer.expired(clock.ticks_ms())
```

Install the library and pytest with
`pip install chumicro-timing pytest`, then run the test with `pytest`.

<!-- faq-schema: generated by scripts/faq_schema.py -->
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "url": "https://chumicro.com/ChuMicro/guides/faq/",
  "mainEntity": [
    {
      "@type": "Question",
      "name": "Why does my board freeze while it talks to the network?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Most Python libraries for boards stop the whole program while they wait. A request to a slow server holds the processor until the server answers. A WiFi retry against an unplugged router holds it until the retry gives up. Every other job on the board waits too: the status LED, the button, the sensor read. A ChuMicro library does a small piece of its job on each pass of your loop, then hands control straight back. The LED keeps blinking and the button keeps answering while the network is slow. Your code sets how long to wait and what happens when the time runs out."
      }
    },
    {
      "@type": "Question",
      "name": "Where did time.sleep() go?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "ChuMicro programs check the clock instead of sleeping. time.sleep(1) stops the whole board for a second. A sleeping program reads no buttons and answers no network. Rate.due(now) from chumicro-timing returns True once per period. The loop runs everything else in between. The loop is still a while True: at the bottom of your program. Once it runs several jobs, a Runner from chumicro-runner keeps their schedule. runner.wait() sleeps only until the next job is due."
      }
    },
    {
      "@type": "Question",
      "name": "How do I use MQTT on CircuitPython without freezing everything else?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "MQTT is the publish-and-subscribe protocol most home-automation setups speak. Add an MQTTClient from chumicro-mqtt to a runner beside the rest of your program. The client sends, receives, and keeps the connection alive a little at a time on each pass. An LED keeps blinking while the client waits for the broker."
      }
    },
    {
      "@type": "Question",
      "name": "Does this use async and await?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "No. ChuMicro libraries are plain objects that your while True: loop calls. No library uses async def, await, or the asyncio module. A program built on asyncio can still drive them: one of its tasks calls a library's check(now_ms) and handle(now_ms). The libraries avoid async to save memory on CircuitPython. CircuitPython compiles every await into a method call that builds a new generator object each time it runs. On a 256 KB board, those objects churn the heap. MicroPython compiles the same await to a single bytecode. For a task that reads best as steps in order, the libraries use generators with yield from, which compiles to one bytecode on both runtimes."
      }
    },
    {
      "@type": "Question",
      "name": "How do I keep WiFi connected on a Pico W or an ESP32?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Add a WifiService from chumicro-wifi to your runner. The service joins your network and rejoins on its own after a drop. After a failed join, it waits 1 second before the next try. Each further failure doubles the wait, up to a minute. On every change of state, the service calls your callback with the old and the new state: disconnected, connecting, connected, reconnecting, or failed. It reaches failed only after a retry limit you set with reconnect_max."
      }
    },
    {
      "@type": "Question",
      "name": "Does anything ever block?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Yes. A few network calls in the board's firmware come only in a form that waits. On CircuitPython, wifi.radio.connect() waits until it joins or times out. Each WiFi join attempt holds your loop for up to connect_timeout_ms, 15 seconds by default. On ESP32 and Pico W, MicroPython joins in the background while your loop keeps running. Opening a connection to a server also waits in pieces. The server name lookup waits in one call on both runtimes. The TLS handshake, the setup behind https://, waits in another. On CircuitPython, the plain TCP connect also waits in one call. Your loop runs between those pieces. Once the connection is open, sending, receiving, keepalives, and timeouts run a step at a time on both runtimes."
      }
    },
    {
      "@type": "Question",
      "name": "Can I run the same code on CircuitPython and MicroPython?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "The library code, yes. Every ChuMicro library runs on CircuitPython, MicroPython, and the Python on your laptop. Your pin setup changes, because each runtime names pins its own way. CircuitPython uses board and digitalio. MicroPython uses machine.Pin. The rest of the program stays the same. Coming from Arduino shows the MicroPython pin lines for an LED and a button."
      }
    },
    {
      "@type": "Question",
      "name": "Why does my button miss presses while the board is doing other work?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Reading a pin returns its level at that moment. A tap that starts and ends between two reads leaves no trace. chumicro-buttons watches the pin in the background. On CircuitPython, the firmware's keypad module does the watching. On MicroPython, a pin interrupt does. Each press waits for your next check(), stamped with the time it happened. A long hold reads as long even when the loop was slow to look. Debouncing, long presses, auto-repeat, and click counting are built in."
      }
    },
    {
      "@type": "Question",
      "name": "How do I store a value that survives a reboot?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Use chumicro-kvstore. A KVStore reads and writes like a dictionary. It keeps values in the storage the board has: CircuitPython's non-volatile memory (microcontroller.nvm), ESP32's NVS key-value area on MicroPython, a file on other MicroPython boards, and plain memory on your laptop. commit_if_changed() writes to flash only when a value changed, so it is safe to call on every pass of your loop."
      }
    },
    {
      "@type": "Question",
      "name": "How much space do these take on a board?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Each library takes between about 1 KB and 31 KB of flash, compiled to MicroPython bytecode. CI holds every library under a ceiling: at most 2,595 bytes for chumicro-timing, 7,339 for chumicro-wifi, and 30,892 for chumicro-websockets, the largest. A board with 2 MB of flash has roughly 800 KB left for your files once the firmware is on it. A project that needs a timer installs only chumicro-timing."
      }
    },
    {
      "@type": "Question",
      "name": "How do I install one library on a board?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Use circup on CircuitPython, mip on MicroPython, and pip on your laptop, each with the library's name. circup needs the ChuMicro bundle registered once before it finds ChuMicro libraries. Installing libraries has the command for each runtime."
      }
    },
    {
      "@type": "Question",
      "name": "Can I test my project without hardware?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Yes. Every library runs on the Python on your laptop. The libraries' testing modules ship stand-ins for the parts that need a board: a fake clock you move forward by hand, a fake socket, a fake WiFi radio, and a fake button the test presses. A test moves the fake clock forward instead of sleeping, so a test of a 30-second timeout finishes in milliseconds."
      }
    }
  ]
}
</script>
<!-- /faq-schema -->
