# Decision 0015 — Board architecture support tiers

Status: `accepted`
Date: `2026-04-03` (revised `2026-04-04`)

## Context

Chumicro libraries may depend on `collections.deque` and other features that are not available on all CircuitPython and MicroPython board architectures.  `deque` is gated by compile-time flags that vary by port and chip family.

A source-level audit of the pinned CircuitPython 10.1.4 and MicroPython v1.26.0 trees (`.tools/`) was performed to determine which architectures include `deque`.

Beyond compile-time feature availability, boards also vary widely in RAM and flash.  Libraries that use networking, TLS, displays, or larger buffers need meaningful memory headroom.  A hardware resource baseline was established to complement the feature-flag analysis.

## Findings

### CircuitPython

`collections.deque` is gated by `CIRCUITPY_FULL_BUILD` (defined in `py/circuitpy_mpconfig.h`).  The global default is `CIRCUITPY_FULL_BUILD ?= 1` (`py/circuitpy_mpconfig.mk`), so most ports include it.  Exceptions:

| Port | `CIRCUITPY_FULL_BUILD` | `deque` available | Notes |
|---|---|---|---|
| **espressif** (ESP32-S2, S3, C3, etc.) | `?= 1` | ✅ | Primary Chumicro target |
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
| **esp32** (ESP32, S2, S3, C3, C6) | `EXTRA_FEATURES` | ✅ | Primary Chumicro target |
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

A board is supported only if it provides at least **512 KB of MCU RAM** and at least **4 MB of flash**.  Boards with less than 512 KB of MCU RAM are unsupported unless the specific board or module includes meaningful PSRAM and still provides at least 4 MB of flash.  Boards with 8 MB or more of flash, and boards with PSRAM, are preferred.

### Feature requirements

Chumicro libraries require `collections.deque` and therefore require a full-build CircuitPython or `EXTRA_FEATURES`+ MicroPython port.

### Support tiers

**Tier 1 — Recommended:**
- ESP32 (original, 520 KB SRAM)
- ESP32-S3
- ESP32-C6 (512 KB HP SRAM + 16 KB LP SRAM)
- RP2350
- Any MCU with ≥512 KB RAM and ≥4 MB flash; 8 MB+ flash and PSRAM strongly preferred

**Tier 2 — Allowed by exception:**
- ESP32-S2 boards *with PSRAM* (base MCU is 320 KB)
- ESP32-C3 boards *with PSRAM* (base MCU is 400 KB)

**Unsupported:**
- SAMD21 (up to 32 KB SRAM)
- SAMD51 (192–256 KB SRAM; CircuitPython also disables `deque` for this port)
- RP2040 (264 KB SRAM)
- nRF52840 (256 KB RAM), nRF52833 (128 KB RAM)
- ESP32-S2 without PSRAM, ESP32-C3 without PSRAM
- ESP8266 / ESP8285
- STM32F4/F7 parts below 512 KB RAM (F401 96 KB, F405/F407 192 KB, F411 128 KB, F412 256 KB, F745/F746 ~320 KB)

### Additional rules

1. The `[tool.chumicro].platforms` key (Decision 0011) identifies runtime support (`cpython`/`micropython`/`circuitpython`), not hardware architecture.  Architecture constraints are documented per-library in the README and guide.
2. If a future library needs to run on constrained boards below the baseline, it must document the lower requirements explicitly and provide fallback implementations where needed.

## Consequences

- Library READMEs and guides should state the minimum board requirements (512 KB RAM, 4 MB flash, full-build CircuitPython or `EXTRA_FEATURES` MicroPython).
- The cross-runtime compatibility runners test against the unix port, which exceeds all hardware baselines.
- Future board transport tooling and `devices.yml` entries should target Tier 1 or Tier 2 boards.
- If users report issues on unsupported boards, the answer is "unsupported" rather than "bug".

