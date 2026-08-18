# Running out of memory

This page is for when a deploy or an import dies with a memory error on a small board.  The heap is the board's free RAM (a Pi Pico W has about 264 KB total and frees roughly 126 KB to 150 KB after boot; an ESP32-S2 frees about 80 KB).  When something that runs fine on a laptop runs out of memory on the board, it is usually one of these three.

## mqtt, requests, http-server, or websockets silently runs out of memory while importing

In RAM deploy mode the whole library bootstrap sits on the heap, and the multi-KB parsers and buffers in these libraries do not fit alongside it (a Pico W frees about 150 KB, an ESP32-S2 about 80 KB).  The same libraries run fine frozen in flash.  From the outside it reads like a bug in the library.

**Fix.** These libraries declare `requires_flash = true`, so the deploy pre-flight auto-switches RAM to flash and prints why, and flash is the default deploy mode.  If you pinned RAM mode, drop the pin or force flash:

```
chumicro-workspace deploy <project> --deploy-mode flash
```

(background: [Decision 0047](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0047-deploy-mode-flash-default.md))

## A first `import chumicro_mqtt` partway through a run raises `MemoryError`

`mqtt/client.py` alone sets an on-device import floor of about 95 KB, roughly half a Pico W's heap; importing all fourteen libraries at once costs about 142 KB, 72% of a Pico W.  On-device compilation of the largest file dominates, and there is no compacting garbage collector, so objects allocated mid-run scatter and a large contiguous import can no longer find room.

**Fix.** Instantiate your clients during startup, while the heap is still clean and unfragmented, rather than on the first message partway through the run.

## `ImportError` for `collections.deque` when importing a ChuMicro library

ChuMicro libraries need `collections.deque` (a double-ended queue).  It is gated behind `CIRCUITPY_FULL_BUILD` on CircuitPython and `ROM_LEVEL >= EXTRA_FEATURES` on MicroPython, and it is disabled on SAMD21, most nRF52 builds, and SAMD51 CircuitPython.

**Fix.** Use a full-build CircuitPython or an EXTRA_FEATURES-or-higher MicroPython on a supported chip (ESP32, RP2040, RP2350, STM32).  Boards under 256 KB of RAM are unsupported, not a bug.
