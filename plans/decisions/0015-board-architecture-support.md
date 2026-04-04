# Decision 0015 — Board architecture support tiers

Status: `accepted`
Date: `2026-04-03`

## Context

Chumicro libraries depend on `collections.deque` (via `EventQueueSink` in the runner pattern) and other features that are not available on all CircuitPython and MicroPython board architectures.  `deque` is gated by compile-time flags that vary by port and chip family.

A source-level audit of the pinned CircuitPython 10.1.4 and MicroPython v1.26.0 trees (`.tools/`) was performed to determine which architectures include `deque`.

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
- ESP32 family (ESP32, ESP32-S2, ESP32-S3, ESP32-C3, ESP32-C6) — primary target
- RP2040, RP2350 (Raspberry Pi Pico / Pico 2)
- STM32
- Broadcom (Raspberry Pi SBCs, CircuitPython only)
- NXP i.MX RT (CircuitPython), Renesas RA (MicroPython)

**Unsupported architectures** (deque missing on one or both runtimes):
- SAMD21 (Trinket M0, Feather M0, Gemma M0, etc.) — too constrained
- nRF52 (most builds) — CircuitPython `FULL_BUILD = 0`, MicroPython ROM level varies
- SAMD51 on CircuitPython — port-level `deque` explicitly disabled despite `SAMD51` being capable on MicroPython

## Decision

1. **Chumicro libraries require `collections.deque`** and therefore require a full-build CircuitPython or `EXTRA_FEATURES`+ MicroPython port.
2. The primary target remains the **ESP32-S2/S3 family** (as already stated in AGENTS.md).
3. **RP2040/RP2350 and STM32** are secondarily supported.
4. **SAMD21 and non-full-build nRF52 boards are explicitly unsupported.**  Libraries should document this.
5. If a future library needs to run on constrained boards without `deque`, it must provide a fallback implementation or be documented as requiring a full-build target.
6. The `[tool.chumicro].platforms` key (Decision 0011) identifies runtime support (`cpython`/`micropython`/`circuitpython`), not hardware architecture.  Architecture constraints are documented per-library in the README and guide.

## Consequences

- Library READMEs and guides should state the minimum board requirements (full-build CircuitPython or `EXTRA_FEATURES` MicroPython).
- The cross-runtime compatibility runners already test against the unix port (which has `deque`), so they remain valid.
- Future board transport tooling and `devices.yml` entries should target supported architectures.
- If users report issues on SAMD21 or small nRF boards, the answer is "unsupported" rather than "bug".

