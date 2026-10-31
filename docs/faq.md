---
title: "CircuitPython and MicroPython questions: blocking, WiFi, MQTT, and storage"
---

# Questions people ask

Short answers to what people ask first, each with a link to the library
that does the work.

## Why does my board freeze while it talks to the network?

Because most Python libraries for boards wait with the whole program
stopped.  A request to a slow server, or a WiFi retry against a router
that is unplugged, holds the processor until it finishes, and every
other job on the board waits with it: the status LED, the button, the
sensor read.

ChuMicro libraries work in small steps instead.  Each pass through
your loop, every library does a little and hands control back, so the
LED keeps blinking and the button keeps answering while the network
is slow, and you decide how long to wait and what happens when the
waiting is over.  A few connection steps still wait, and
[Does anything ever block?](#does-anything-ever-block) lists them.

## Where did time.sleep() go?

ChuMicro programs check the clock instead of sleeping.  A
`time.sleep(1)` stops the whole board for a second, so a sleeping
program reads no buttons and answers no network.  A `Rate` from
[chumicro-timing](https://chumicro.com/ChuMicro/timing/stable/)
answers `True` from `due(now)` once per period, and the loop runs
everything else in between.

The loop is still a `while True:` at the bottom of your program.  Once
it runs several jobs, a `Runner` from
[chumicro-runner](https://chumicro.com/ChuMicro/runner/stable/) keeps
the schedule, and its `wait()` sleeps only until the next job is due.
[Coming from Arduino](coming-from-arduino.md) walks through blink,
buttons, timers, and wifi side by side with the code you already know.

## How do I use MQTT on CircuitPython without freezing everything else?

Add the client from
[chumicro-mqtt](https://chumicro.com/ChuMicro/mqtt/stable/) to a runner
next to the rest of your program.  MQTT is the small
publish-and-subscribe protocol most home-automation setups speak, and
the client sends, receives, and keeps the connection alive a little at
a time on each pass, so an LED keeps blinking while the client waits
for the broker.

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
mqtt.connect()                   # returns at once; connecting happens in the loop


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

A reading published before the broker answers waits in a short queue
and goes out once the client connects, and the client reconnects on
its own after a drop.  QoS 0 and 1, last will, retained messages, and
TLS all work the same way.  [Wiring WiFi
credentials](wiring-wifi-credentials.md) shows the `secrets.toml`
entries for the broker.

## Does this use async and await?

No.  The libraries are plain objects your `while True:` loop calls, and
none of them uses `async def`, `await`, or the `asyncio` module.  If
your own program is built on `asyncio`, it can still drive them: call a
library's `check(now_ms)` and `handle(now_ms)` from one of your tasks.

The libraries avoid `async` to save memory.  CircuitPython compiles
every `await` into a method call that builds a new generator object
each time it runs, which churns the heap on a 256 KB board, while
MicroPython compiles the same `await` to a single bytecode.  Where a
task reads best as steps in order, the libraries use generators with
`yield from`, which compile to one bytecode on both.

## How do I keep WiFi connected on a Pico W or an ESP32?

Add a `WifiService` from
[chumicro-wifi](https://chumicro.com/ChuMicro/wifi/stable/) to your
runner.  It joins, retries a failed join after a pause that doubles
from 1 second up to a minute, rejoins on its own after a drop, and
calls you back on every change of state (`disconnected`, `connecting`,
`connected`, `reconnecting`, and `failed` if you set a retry limit).

On CircuitPython, keep `CIRCUITPY_WIFI_SSID` and
`CIRCUITPY_WIFI_PASSWORD` out of `settings.toml`.  Those keys turn on
the firmware's own auto-connect, which fights `WifiService` for the
radio.  [Coming from Arduino](coming-from-arduino.md) has a complete
program that blinks an LED through a router outage.

## Does anything ever block?

Yes, a few network calls that the board's firmware offers only in a
form that waits.  On CircuitPython, `wifi.radio.connect()` has no
non-blocking form, so each WiFi join attempt holds your loop for up to
the connect timeout, 15 seconds by default.
MicroPython joins in the background on ESP32 and Pi Pico W, and your
loop keeps running there.

Opening a connection to a server waits in pieces too.  Looking up the
server's name is one call on both runtimes, and the TLS handshake (the
setup behind `https://`) is another.  On CircuitPython the plain TCP
connect is a single call as well.  Your loop runs between those
pieces, and once the connection is open, sending, receiving,
keepalives, and timeouts all run a step at a time on both runtimes.

## Can I run the same code on CircuitPython and MicroPython?

The library code, yes.  Every ChuMicro library runs on CircuitPython,
MicroPython, and the Python on your laptop.  Your pin setup is the
part that changes, because each runtime names pins its own way:
CircuitPython uses `board` and `digitalio`, MicroPython uses
`machine.Pin`.  Those few lines differ and the rest of the program
stays the same.

On your laptop there are no pins or radio, so each library takes its
clock, its socket, its radio, or its button as an argument, and its
`testing` module ships a stand-in for each one.

## Why does my button miss presses while the board is doing other work?

Because reading a pin tells you its level at that moment and nothing
about what happened between reads.  A tap that starts and ends while
your loop is busy elsewhere leaves no trace.

[chumicro-buttons](https://chumicro.com/ChuMicro/buttons/stable/)
watches the pin in the background, through the `keypad` module on
CircuitPython and a pin interrupt on MicroPython.  The press waits for
your next `check()`, stamped with the time it really happened, so a
long hold reads as long even when the loop was slow to look.
Debouncing, long presses, auto-repeat, and click counting come with it.

Rotary encoders work the same way in
[chumicro-knobs](https://chumicro.com/ChuMicro/knobs/stable/): a fast
spin is counted outside your loop and arrives whole.

## How do I store a value that survives a reboot?

Use [chumicro-kvstore](https://chumicro.com/ChuMicro/kvstore/stable/),
which reads and writes like a dictionary and picks the storage the
board has: CircuitPython's non-volatile memory (`microcontroller.nvm`),
ESP32's NVS key-value area on MicroPython, a file on other
MicroPython boards, and plain memory on your laptop.

`commit_if_changed()` writes only when a value actually changed, so
you can call it on every pass of your loop and the flash is written
only when there is something new to save.

## How much space do these take on a board?

Between about 1 KB and 31 KB each, compiled to MicroPython bytecode.
CI holds every library under a ceiling: at most 2,595 bytes for
`chumicro-timing`, 7,339 for `chumicro-wifi`, and 30,892 for
`chumicro-websockets`, the largest.  A board with 2 MB of flash has
roughly 800 KB left for your files once the firmware is on it.

Install only what you use.  A project that needs a timer installs a
timer.

## How do I install one library on a board?

Use circup on CircuitPython, mip on MicroPython, and pip on your
laptop, each with the library's name.  Circup needs the ChuMicro bundle
added once before it can find ChuMicro libraries.

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle && circup install chumicro_mqtt
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_mqtt
pip install chumicro-mqtt
```

Those three lines install `chumicro-mqtt` on each runtime.  The pip
install on your laptop is how you run tests without a board plugged
in.  [Installing libraries](install.md) covers pre-compiled `.mpy`
packages and the experimental channel.

## Can I test my project without hardware?

Yes.  The libraries run on the Python on your laptop, and each one
ships stand-ins for the parts that would otherwise need a board: a
fake clock you move forward by hand, a fake socket, a fake WiFi radio,
a fake button you press from the test.  Tests move the clock instead
of sleeping, so a test that covers a 30-second timeout finishes in
milliseconds.

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

Run it with `pytest`.

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
        "text": "Because most Python libraries for boards wait with the whole program stopped. A request to a slow server, or a WiFi retry against a router that is unplugged, holds the processor until it finishes, and every other job on the board waits with it: the status LED, the button, the sensor read. ChuMicro libraries work in small steps instead. Each pass through your loop, every library does a little and hands control back, so the LED keeps blinking and the button keeps answering while the network is slow, and you decide how long to wait and what happens when the waiting is over. A few connection steps still wait, and Does anything ever block? lists them."
      }
    },
    {
      "@type": "Question",
      "name": "Where did time.sleep() go?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "ChuMicro programs check the clock instead of sleeping. A time.sleep(1) stops the whole board for a second, so a sleeping program reads no buttons and answers no network. A Rate from chumicro-timing answers True from due(now) once per period, and the loop runs everything else in between. The loop is still a while True: at the bottom of your program. Once it runs several jobs, a Runner from chumicro-runner keeps the schedule, and its wait() sleeps only until the next job is due. Coming from Arduino walks through blink, buttons, timers, and wifi side by side with the code you already know."
      }
    },
    {
      "@type": "Question",
      "name": "How do I use MQTT on CircuitPython without freezing everything else?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Add the client from chumicro-mqtt to a runner next to the rest of your program. MQTT is the small publish-and-subscribe protocol most home-automation setups speak, and the client sends, receives, and keeps the connection alive a little at a time on each pass, so an LED keeps blinking while the client waits for the broker."
      }
    },
    {
      "@type": "Question",
      "name": "Does this use async and await?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "No. The libraries are plain objects your while True: loop calls, and none of them uses async def, await, or the asyncio module. If your own program is built on asyncio, it can still drive them: call a library's check(now_ms) and handle(now_ms) from one of your tasks. The libraries avoid async to save memory. CircuitPython compiles every await into a method call that builds a new generator object each time it runs, which churns the heap on a 256 KB board, while MicroPython compiles the same await to a single bytecode. Where a task reads best as steps in order, the libraries use generators with yield from, which compile to one bytecode on both."
      }
    },
    {
      "@type": "Question",
      "name": "How do I keep WiFi connected on a Pico W or an ESP32?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Add a WifiService from chumicro-wifi to your runner. It joins, retries a failed join after a pause that doubles from 1 second up to a minute, rejoins on its own after a drop, and calls you back on every change of state (disconnected, connecting, connected, reconnecting, and failed if you set a retry limit). On CircuitPython, keep CIRCUITPY_WIFI_SSID and CIRCUITPY_WIFI_PASSWORD out of settings.toml. Those keys turn on the firmware's own auto-connect, which fights WifiService for the radio. Coming from Arduino has a complete program that blinks an LED through a router outage."
      }
    },
    {
      "@type": "Question",
      "name": "Does anything ever block?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Yes, a few network calls that the board's firmware offers only in a form that waits. On CircuitPython, wifi.radio.connect() has no non-blocking form, so each WiFi join attempt holds your loop for up to the connect timeout, 15 seconds by default. MicroPython joins in the background on ESP32 and Pi Pico W, and your loop keeps running there. Opening a connection to a server waits in pieces too. Looking up the server's name is one call on both runtimes, and the TLS handshake (the setup behind https://) is another. On CircuitPython the plain TCP connect is a single call as well. Your loop runs between those pieces, and once the connection is open, sending, receiving, keepalives, and timeouts all run a step at a time on both runtimes."
      }
    },
    {
      "@type": "Question",
      "name": "Can I run the same code on CircuitPython and MicroPython?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "The library code, yes. Every ChuMicro library runs on CircuitPython, MicroPython, and the Python on your laptop. Your pin setup is the part that changes, because each runtime names pins its own way: CircuitPython uses board and digitalio, MicroPython uses machine.Pin. Those few lines differ and the rest of the program stays the same. On your laptop there are no pins or radio, so each library takes its clock, its socket, its radio, or its button as an argument, and its testing module ships a stand-in for each one."
      }
    },
    {
      "@type": "Question",
      "name": "Why does my button miss presses while the board is doing other work?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Because reading a pin tells you its level at that moment and nothing about what happened between reads. A tap that starts and ends while your loop is busy elsewhere leaves no trace. chumicro-buttons watches the pin in the background, through the keypad module on CircuitPython and a pin interrupt on MicroPython. The press waits for your next check(), stamped with the time it really happened, so a long hold reads as long even when the loop was slow to look. Debouncing, long presses, auto-repeat, and click counting come with it."
      }
    },
    {
      "@type": "Question",
      "name": "How do I store a value that survives a reboot?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Use chumicro-kvstore, which reads and writes like a dictionary and picks the storage the board has: CircuitPython's non-volatile memory (microcontroller.nvm), ESP32's NVS key-value area on MicroPython, a file on other MicroPython boards, and plain memory on your laptop. commit_if_changed() writes only when a value actually changed, so you can call it on every pass of your loop and the flash is written only when there is something new to save."
      }
    },
    {
      "@type": "Question",
      "name": "How much space do these take on a board?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Between about 1 KB and 31 KB each, compiled to MicroPython bytecode. CI holds every library under a ceiling: at most 2,595 bytes for chumicro-timing, 7,339 for chumicro-wifi, and 30,892 for chumicro-websockets, the largest. A board with 2 MB of flash has roughly 800 KB left for your files once the firmware is on it. Install only what you use. A project that needs a timer installs a timer."
      }
    },
    {
      "@type": "Question",
      "name": "How do I install one library on a board?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Use circup on CircuitPython, mip on MicroPython, and pip on your laptop, each with the library's name. Circup needs the ChuMicro bundle added once before it can find ChuMicro libraries."
      }
    },
    {
      "@type": "Question",
      "name": "Can I test my project without hardware?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Yes. The libraries run on the Python on your laptop, and each one ships stand-ins for the parts that would otherwise need a board: a fake clock you move forward by hand, a fake socket, a fake WiFi radio, a fake button you press from the test. Tests move the clock instead of sleeping, so a test that covers a 30-second timeout finishes in milliseconds."
      }
    }
  ]
}
</script>
<!-- /faq-schema -->
