# Known board quirks

This page collects the hardware and firmware quirks that make one board fail where another, running the same code, succeeds.  When a board behaves oddly, find its row here before you suspect your own code.  Most entries link to the page with the full fix.

| Board | Quirk | What to do |
|---|---|---|
| Raspberry Pi Pico W (RP2040) | HTTPS and `wss://` need flash deploy mode | Deploy those workloads in flash mode.  See [TLS and HTTPS failures](tls-https-failures.md). |
| Raspberry Pi Pico W (RP2040) | Silent wifi drop, `last_error` stays `None` | Check `wifi.state` and `wifi.connected`, not `last_error`.  See [WiFi won't connect](wifi-wont-connect.md). |
| Raspberry Pi Pico W (RP2040) | CYW43 idle power-save causes 30 to 100 ms tick stalls | Keep the `power_save = false` default; do not set `power_save = true`. |
| Raspberry Pi Pico W (RP2040) | CircuitPython wifi fails `Unknown failure 1` in some demos | Known rp2 CircuitPython radio-state quirk; retry, or run the board on MicroPython. |
| Raspberry Pi Pico W (RP2040) | CircuitPython TLS server bricks the CYW43 chip | Do not serve HTTPS or `wss://` from a Pico W on CircuitPython; use an ESP32 board or MicroPython.  See [TLS and HTTPS failures](tls-https-failures.md). |
| Raspberry Pi Pico W (RP2040) | No NVS on MicroPython | Use `chumicro-kvstore`, which falls back to a LittleFS file (`/_chu_kv.msgpack`).  See [Persisting data](persisting-data.md). |
| Raspberry Pi Pico W (RP2040) | Onboard LED sits on the wifi coprocessor and can't PWM | Drive it as a plain on/off pin, not with PWM. |
| Raspberry Pi Pico W (RP2040) | Slower USB mass-storage controller | More prone to a read-only CIRCUITPY after a mid-write teardown; reset and replug before you redeploy. |
| Lolin S2 Mini (ESP32-S2) | `machine.bootloader()` leaves the chip half-running, no ROM bootloader appears | Enter the bootloader by hand: hold BOOT (GPIO0), tap RESET, release BOOT. |
| Lolin S2 Mini (ESP32-S2) | CircuitPython raw-paste (Ctrl-E) hangs on CP 10.1.4 | Upgrade firmware past 10.1.4. |
| Lolin S2 Mini (ESP32-S2) | Very slow CircuitPython flash writes, 30 to 60 s per example | Not a hang; wait it out. |
| Lolin S2 Mini (ESP32-S2) | TCP stack coalesces fragments differently | Size websocket and HTTP frame buffers with headroom. |
| Lolin S2 Mini (ESP32-S2) | USB-CDC serial can drop mid-telemetry | Reset and replug; keep runs short. |
| Lolin S2 Mini (ESP32-S2) | Ships with a corrupted FAT, or demotes CIRCUITPY to read-only on a flaky cable | Swap to a known-good cable; `reset-board` to rebuild the filesystem. |
| ESP32-S3 (incl. UM FeatherS3 P4) | Unstable wifi at full transmit power on pre-2024 P4 and P7 revisions | Set `wifi.tx_power_dbm = 15`.  See [WiFi won't connect](wifi-wont-connect.md). |
| ESP32-S3 (incl. UM FeatherS3 P4) | Half-open station slow-fails with `Unknown failure 205` | Upgrade `chumicro-wifi` to 0.7.1 or later (it calls `stop_station()` before each attempt) and retry. |
| ESP32-S3 (incl. UM FeatherS3 P4) | Individual RF-dud units (all-zeros-prefix MAC is the tell) | Reseat or replace the board, or add an external antenna. |
| ESP32-S3 (incl. UM FeatherS3 P4) | Enough free heap for HTTPS in RAM mode (over 200 KB after wifi) | No flash-mode requirement for HTTPS on this board, unlike the Pico W. |
| Classic ESP32 (TinyPICO, no native USB) | CircuitPython 10.2.0 corrupts the running program non-deterministically (`'Runner' object has no attribute 'tick'`, NUL bytes in attribute names) | Keep classic ESP32 on MicroPython; it is off the CircuitPython matrix until re-tested at CP 10.3.0. |
| SAMD21, nRF52, SAMD51-CP (below the 256 KB floor) | No `collections.deque`, so ChuMicro libraries won't import | Use a supported chip (ESP32, RP2040, RP2350, STM32).  See [Running out of memory](out-of-memory.md). |
| SAMD21, nRF52, SAMD51-CP (below the 256 KB floor) | SAMD21 NVM is only 256 B | Expect `KVStoreFull` quickly; keep persisted state tiny or use a larger-NVM board.  See [Persisting data](persisting-data.md). |

These below-floor boards are unsupported, not buggy.  The quirks above are hardware and firmware facts, not defects in your code or in the libraries.
