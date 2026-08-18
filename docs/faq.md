---
title: "CircuitPython and MicroPython questions: blocking, WiFi, MQTT, and storage"
---

# Questions people ask

Short answers, each one true of the code as it ships today.  Every
answer links to the library that does the work.

## Why does my board freeze while it talks to the network?

Because most Python libraries for boards wait with the whole program
stopped.  A request to a slow server, or a WiFi retry against a router
that is unplugged, holds the processor until it finishes, and every
other job on the board waits with it: the status LED, the button, the
sensor read.

ChuMicro libraries work in small steps instead.  Each pass through
your loop, every library does a little and hands control back, so a
dead network costs you the network and nothing else.  The LED keeps
blinking, the button keeps answering, and you decide how long to wait
and what happens when the waiting is over.

## How do I use MQTT on CircuitPython without freezing everything else?

Call `handle()` once per pass through your loop.  MQTT is the small
publish-and-subscribe protocol most home-automation setups speak, and
[chumicro-mqtt](https://chumicro.com/ChuMicro/mqtt/stable/) runs
each step of it (connect, subscribe, publish, the acknowledgements
that follow) as a piece of work that finishes in one tick.

```python
from chumicro_timing import ticks_ms
from chumicro_mqtt import MQTTClient

client = MQTTClient(socket_factory, config)
client.connect()                   # returns right away; no I/O here yet

while True:
    now = ticks_ms()
    client.handle(now)             # one step of protocol work
    led.value = not led.value      # your program keeps running
```

QoS 0 and 1, last will, retained messages, and TLS all work this way.

## Does this use async and await?

No, and your own program still can.  The libraries make progress
through `check` and `handle` calls that return immediately, so many of
them share one loop without a scheduler.

That is a rule about what is inside the libraries.  Your application
can be an asyncio program, a thread, or a plain `while True:` loop.
You tick the client from wherever your loop lives.

The reason is measured rather than stylistic.  CircuitPython compiles
every `await` into a method dispatch that allocates a fresh generator
each time it resumes, and its asyncio port has carried a broken socket
layer since 2021.  MicroPython compiles the same `await` to a single
bytecode.  Building on `async` means paying heap churn on one runtime
or quietly supporting only the other, so the libraries use generators,
which are one bytecode on both.

## How do I keep WiFi connected on a Pico W or an ESP32?

Hand the radio to
[chumicro-wifi](https://chumicro.com/ChuMicro/wifi/stable/) and
read its state.  It connects, retries with backoff, reconnects after a
drop, and reports every transition (`disconnected`, `connecting`,
`connected`, `reconnecting`, `failed`) so your app can react to a
change rather than poll for one.

It owns the radio outright, which matters: firmware-level auto-connect
settings compete with a supervisor and produce reconnect storms.  One
component does the reconnecting.

## Does anything ever block?

One thing does, and it is worth knowing before you pick a runtime.
CircuitPython's firmware exposes only a blocking `wifi.radio.connect()`,
with no non-blocking variant, so while the WiFi service is connecting
or reconnecting on a CircuitPython board, that call holds the loop for
up to your connect timeout (15 seconds by default).  Once the link is
up, the loop runs at full speed again.

MicroPython's `wlan.connect()` associates in the background on both
ESP32 and Pi Pico W, so the same code never stalls there.  If a
never-stalling connect matters to your project, choose MicroPython on
those boards.

Everything after association, on both runtimes, runs a step at a time.

## Can I run the same code on CircuitPython and MicroPython?

Yes, and on the Python on your laptop.  Every library runs unmodified
on all three, so you can write and test a program at your desk and
deploy those same files to a Pico W running CircuitPython or an ESP32
running MicroPython.

Each library takes its I/O and its clock as arguments, which is what
makes this work.  A socket needs four methods (`recv_into`, `send`,
`close`, `setblocking`) and a clock needs three (`ticks_ms`,
`ticks_add`, `ticks_diff`).  Anything with those methods is accepted,
including a fake you write for a test.

## How do I store a value that survives a reboot?

Use [chumicro-kvstore](https://chumicro.com/ChuMicro/kvstore/stable/),
which reads and writes like a dictionary and picks the right storage
for the board it finds itself on: NVM on CircuitPython, NVS on ESP32
MicroPython, LittleFS elsewhere, and memory on your laptop.

`commit_if_changed()` writes only when a value actually changed, which
keeps a counter you update every loop from wearing out the flash.

## How much space do these take on a board?

A few kilobytes each.  CI holds every library under a flash-size
ceiling, measured as MicroPython bytecode: 2,595 bytes for
`chumicro-timing`, 7,339 for `chumicro-wifi`, and 21,516 for
`chumicro-mqtt`, the largest of them.  Raising a ceiling takes a
measured justification in the commit that does it.

Install only what you use.  A project that needs a timer installs a
timer.

## How do I install one library on a board?

One command per runtime, with the library name in it:

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle && circup install chumicro_mqtt
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_mqtt
pip install chumicro-mqtt
```

The first line is CircuitPython through circup, the second MicroPython
through mip, the third the Python on your computer, which is how you
run tests without a board plugged in.

## Can I test my project without hardware?

Yes.  The libraries run on desktop Python, and each one ships fakes
for the parts that would otherwise need a board: a fake socket, a fake
clock, a fake WiFi radio, a recording transport.  Tests drive time
forward instead of sleeping, so a suite that covers a 30-second
timeout finishes in milliseconds.

When you do have a board, the same `pytest` runs on the silicon.

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
        "text": "Because most Python libraries for boards wait with the whole program stopped. A request to a slow server, or a WiFi retry against a router that is unplugged, holds the processor until it finishes, and every other job on the board waits with it: the status LED, the button, the sensor read. ChuMicro libraries work in small steps instead. Each pass through your loop, every library does a little and hands control back, so a dead network costs you the network and nothing else. The LED keeps blinking, the button keeps answering, and you decide how long to wait and what happens when the waiting is over."
      }
    },
    {
      "@type": "Question",
      "name": "How do I use MQTT on CircuitPython without freezing everything else?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Call handle() once per pass through your loop. MQTT is the small publish-and-subscribe protocol most home-automation setups speak, and chumicro-mqtt runs each step of it (connect, subscribe, publish, the acknowledgements that follow) as a piece of work that finishes in one tick."
      }
    },
    {
      "@type": "Question",
      "name": "Does this use async and await?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "No, and your own program still can. The libraries make progress through check and handle calls that return immediately, so many of them share one loop without a scheduler. That is a rule about what is inside the libraries. Your application can be an asyncio program, a thread, or a plain while True: loop. You tick the client from wherever your loop lives."
      }
    },
    {
      "@type": "Question",
      "name": "How do I keep WiFi connected on a Pico W or an ESP32?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Hand the radio to chumicro-wifi and read its state. It connects, retries with backoff, reconnects after a drop, and reports every transition (disconnected, connecting, connected, reconnecting, failed) so your app can react to a change rather than poll for one. It owns the radio outright, which matters: firmware-level auto-connect settings compete with a supervisor and produce reconnect storms. One component does the reconnecting."
      }
    },
    {
      "@type": "Question",
      "name": "Does anything ever block?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "One thing does, and it is worth knowing before you pick a runtime. CircuitPython's firmware exposes only a blocking wifi.radio.connect(), with no non-blocking variant, so while the WiFi service is connecting or reconnecting on a CircuitPython board, that call holds the loop for up to your connect timeout (15 seconds by default). Once the link is up, the loop runs at full speed again. MicroPython's wlan.connect() associates in the background on both ESP32 and Pi Pico W, so the same code never stalls there. If a never-stalling connect matters to your project, choose MicroPython on those boards."
      }
    },
    {
      "@type": "Question",
      "name": "Can I run the same code on CircuitPython and MicroPython?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Yes, and on the Python on your laptop. Every library runs unmodified on all three, so you can write and test a program at your desk and deploy those same files to a Pico W running CircuitPython or an ESP32 running MicroPython. Each library takes its I/O and its clock as arguments, which is what makes this work. A socket needs four methods (recv_into, send, close, setblocking) and a clock needs three (ticks_ms, ticks_add, ticks_diff). Anything with those methods is accepted, including a fake you write for a test."
      }
    },
    {
      "@type": "Question",
      "name": "How do I store a value that survives a reboot?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Use chumicro-kvstore, which reads and writes like a dictionary and picks the right storage for the board it finds itself on: NVM on CircuitPython, NVS on ESP32 MicroPython, LittleFS elsewhere, and memory on your laptop. commit_if_changed() writes only when a value actually changed, which keeps a counter you update every loop from wearing out the flash."
      }
    },
    {
      "@type": "Question",
      "name": "How much space do these take on a board?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "A few kilobytes each. CI holds every library under a flash-size ceiling, measured as MicroPython bytecode: 2,595 bytes for chumicro-timing, 7,339 for chumicro-wifi, and 21,516 for chumicro-mqtt, the largest of them. Raising a ceiling takes a measured justification in the commit that does it. Install only what you use. A project that needs a timer installs a timer."
      }
    },
    {
      "@type": "Question",
      "name": "How do I install one library on a board?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "One command per runtime, with the library name in it:"
      }
    },
    {
      "@type": "Question",
      "name": "Can I test my project without hardware?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Yes. The libraries run on desktop Python, and each one ships fakes for the parts that would otherwise need a board: a fake socket, a fake clock, a fake WiFi radio, a recording transport. Tests drive time forward instead of sleeping, so a suite that covers a 30-second timeout finishes in milliseconds. When you do have a board, the same pytest runs on the silicon."
      }
    }
  ]
}
</script>
<!-- /faq-schema -->
