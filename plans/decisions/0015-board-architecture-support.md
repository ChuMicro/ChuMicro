# Decision 0015: Board architecture support tiers

Status: `accepted`
Date: `2026-04-03`
Summary: Hardware baseline is 256 KB MCU RAM + 2 MB physical / ~800 KB usable flash; libraries require `collections.deque` and therefore full-build CircuitPython or `EXTRA_FEATURES`+ MicroPython.
Related: Decision 0011 (platform targeting), Decision 0039 (firmware version floor)

## Context

ChuMicro libraries may depend on `collections.deque` and other features that are not available on all CircuitPython and MicroPython board architectures.  `deque` is gated by compile-time flags that vary by port and chip family.

A source-level audit of the pinned CircuitPython 10.1.4 and MicroPython v1.26.0 trees (`.tools/`) was performed to determine which architectures include `deque`.

Beyond compile-time feature availability, boards vary widely in RAM and flash.  Libraries that use networking, TLS, displays, or larger buffers need meaningful memory headroom.  The Pi Pico (RP2040, 264 KB SRAM) is the practical floor — even there, networking + TLS workloads are tight and cooperative-tick budgets matter.  Modern boards (ESP32-S3, RP2350, ESP32-C6) ship with 4–10× the headroom and are easier to write libraries for.  Setting the support floor anywhere below the Pi Pico would force every library author to design around 32–128 KB SAMD21-class boards that no longer represent where the project is headed.

## Findings

### CircuitPython

`collections.deque` is gated by `CIRCUITPY_FULL_BUILD` (defined in `py/circuitpy_mpconfig.h`).  The global default is `CIRCUITPY_FULL_BUILD ?= 1` (`py/circuitpy_mpconfig.mk`), so most ports include it.  Exceptions:

| Port | `CIRCUITPY_FULL_BUILD` | `deque` available | Notes |
|---|---|---|---|
| **espressif** (ESP32-S2, S3, C3, etc.) | `?= 1` | ✅ | Primary ChuMicro target |
| **raspberrypi** (RP2040, RP2350) | `?= 1` | ✅ | |
| **broadcom** (Raspberry Pi SBCs) | `= 1` | ✅ | |
| **stm** | inherits `1` | ✅ | |
| **mimxrt10xx** (NXP i.MX RT) | inherits `1` | ✅ | |
| **silabs** | inherits `1` | ✅ | |
| **cxd56** (Sony Spresense) | inherits `1` | ✅ | |
| **litex** | inherits `1` | ✅ | |
| **analog** | inherits `1` | ✅ | |
| **zephyr-cp** | inherits `1` | ✅ | |
| **atmel-samd** (SAMD21, SAMD51) | port explicitly sets `MICROPY_PY_COLLECTIONS_DEQUE (0)` | ❌ | Also many boards set `FULL_BUILD = 0` |
| **nordic** (nRF52) | `?= 0` | ❌ | A few individual boards override to `1` |
| **renode** (simulation) | `= 0` | ❌ | |

### MicroPython

`collections.deque` is gated by `MICROPY_CONFIG_ROM_LEVEL >= EXTRA_FEATURES` (level 30).

| Port | ROM level | `deque` available | Notes |
|---|---|---|---|
| **esp32** (ESP32, S2, S3, C3, C6) | `EXTRA_FEATURES` | ✅ | Primary ChuMicro target |
| **rp2** (RP2040, RP2350) | `EXTRA_FEATURES` | ✅ | |
| **stm32** | `EXTRA_FEATURES` | ✅ | |
| **esp8266** | `EXTRA_FEATURES` | ✅ | |
| **renesas-ra** | `EXTRA_FEATURES` | ✅ | |
| **alif** | `FULL_FEATURES` | ✅ | |
| **unix** (standard variant) | `EXTRA_FEATURES` | ✅ | Used for host compat testing |
| **windows** | explicitly `(1)` | ✅ | |
| **samd51** | `FULL_FEATURES` | ✅ | |
| **samd21** | `BASIC_FEATURES` | ❌ | |
| **nrf** (nRF52) | varies (`MINIMUM` to `EXTRA`) | ⚠️ mixed | Depends on chip; smaller nRF chips lack it |
| **minimal** | `MINIMUM` | ❌ | Reference only, not a real target |

### Summary

**Supported architectures** (deque available on both runtimes):
- ESP32 family (ESP32, ESP32-S2, ESP32-S3, ESP32-C3, ESP32-C6)
- RP2040, RP2350 (Raspberry Pi Pico / Pico 2)
- STM32
- Broadcom (Raspberry Pi SBCs, CircuitPython only)
- NXP i.MX RT (CircuitPython), Renesas RA (MicroPython)

**Unsupported architectures** (deque missing on one or both runtimes):
- SAMD21 (Trinket M0, Feather M0, Gemma M0, etc.) — too constrained
- nRF52 (most builds) — CircuitPython `FULL_BUILD = 0`, MicroPython ROM level varies
- SAMD51 on CircuitPython — port-level `deque` explicitly disabled despite `SAMD51` being capable on MicroPython

## Decision

### Hardware resource baseline

ChuMicro libraries are tested and supported on boards with at least **256 KB of MCU RAM** and at least **2 MB of physical flash (~800 KB usable after CircuitPython firmware on Pi Pico W; MicroPython leaves more headroom)**.  Libraries may still run on boards below this baseline, but those boards are not tested, and issues specific to them will not be investigated.

Boards with PSRAM are preferred — especially for networking, TLS, displays, and larger buffers.  Boards in the 256–512 KB range without PSRAM are supported but may be constrained for memory-intensive workloads like MQTT + TLS.

### Feature requirements

ChuMicro libraries require `collections.deque` and therefore require a full-build CircuitPython or `EXTRA_FEATURES`+ MicroPython port.

### Support tiers

**Tier 1 — Recommended (≥512 KB MCU RAM, or meaningful PSRAM):**
- ESP32 (original, 520 KB SRAM)
- ESP32-S3
- ESP32-C6 (512 KB HP SRAM + 16 KB LP SRAM)
- RP2350 (520 KB SRAM)
- ESP32-S2 with PSRAM (320 KB SRAM + 2 MB in-package PSRAM via FN4R2 or R2 chip variants)
- ESP32-C3 with PSRAM (400 KB SRAM + PSRAM)

**Tier 2 — Supported, constrained (256–512 KB MCU RAM, no PSRAM):**
- RP2040 (264 KB SRAM; no native PSRAM interface)
- ESP32-S2 without PSRAM (320 KB SRAM; bare ESP32-S2, FH2, FH4 chip variants)
- ESP32-C3 without PSRAM (400 KB SRAM)
- Networking and TLS workloads are tight on Tier 2 boards; libraries should document when a feature needs more headroom than Tier 2 provides.

**Unsupported (may work, but not tested or supported):**
- SAMD21 (up to 32 KB SRAM)
- SAMD51 (192–256 KB SRAM; CircuitPython also disables `deque` for this port)
- nRF52840 (256 KB RAM; CircuitPython `FULL_BUILD = 0`, no `deque`), nRF52833 (128 KB RAM)
- ESP8266 / ESP8285
- STM32F4/F7 parts below 256 KB RAM (F401 96 KB, F411 128 KB)

### Additional rules

1. The `[tool.chumicro].platforms` key (Decision 0011) identifies runtime support (`cpython`/`micropython`/`circuitpython`), not hardware architecture.  Architecture constraints are documented per-library in the README and guide.
2. If a future library needs to run on constrained boards below the baseline, it must document the lower requirements explicitly and provide fallback implementations where needed.

## Consequences

- Library READMEs and guides should state the minimum board requirements (256 KB RAM, 2 MB physical flash / ~800 KB usable, full-build CircuitPython or `EXTRA_FEATURES` MicroPython).  Libraries with heavier memory needs (networking, TLS) should note when Tier 1 boards are recommended.
- The cross-runtime compatibility runners test against the unix port, which exceeds all hardware baselines.
- Future board transport tooling and `devices.yml` entries should target Tier 1 or Tier 2 boards.
- If users report issues on unsupported boards, the answer is "not tested or supported on that hardware" — not necessarily a bug, and not something we will investigate.
