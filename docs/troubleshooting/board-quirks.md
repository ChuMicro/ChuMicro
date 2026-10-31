# Known board quirks

Sometimes one board fails where another, running the same code, works. Find your board in the table before you start debugging your own code: each row is something a real board did on the test bench, with what to do about it.

| Board | What you see | What to do |
|---|---|---|
| Raspberry Pi Pico W (RP2040) | HTTPS or `wss://` runs out of memory | Keep the default flash deploy mode; RAM mode leaves too little memory for the handshake. See [TLS and HTTPS failures](tls-https-failures.md). |
| Raspberry Pi Pico W (RP2040) | Wifi never joins or drops, and `wifi.last_error` stays `None` | Watch `wifi.state` and `wifi.connected` instead. See [WiFi won't connect](wifi-wont-connect.md). |
| Raspberry Pi Pico W (RP2040) | The loop stalls for 30 to 100 ms at a time | The radio's power-saving mode causes it. On MicroPython, `chumicro-wifi` turns power saving off unless you set `power_save = true`, so leave that key out. |
| Raspberry Pi Pico W (RP2040) | CircuitPython wifi fails with `Unknown failure 1` in some programs | A CircuitPython radio fault on this chip. Retry, or run the board on MicroPython. |
| Raspberry Pi Pico W (RP2040) | Serving HTTPS or `wss://` on CircuitPython raises `UnsupportedSSLConfigError`, or locks up the wifi chip | Serve TLS from an ESP32 board, or run MicroPython on the Pico W. See [TLS and HTTPS failures](tls-https-failures.md). |
| Raspberry Pi Pico W (RP2040) | No NVS storage on MicroPython | Nothing to do: `chumicro-kvstore` saves to a file, `/_chu_kv.msgpack`, instead. See [Persisting data](persisting-data.md). |
| Raspberry Pi Pico W (RP2040) | The onboard LED won't dim with PWM | That LED hangs off the wifi chip, not a normal pin. Switch it on and off; wire your own LED to a GP pin for dimming. |
| Raspberry Pi Pico W (RP2040) | `CIRCUITPY` turns read-only after a deploy was interrupted | Press RESET and replug before deploying again. See [CIRCUITPY on macOS](macos-circuitpy.md). |
| Lolin S2 Mini (ESP32-S2) | Flashing firmware on MicroPython: the board goes silent and no bootloader port appears | Enter the bootloader by hand: hold BOOT (labelled `0`), tap RESET, release BOOT. See [Getting firmware onto a new board](firmware-onto-a-new-board.md). |
| Lolin S2 Mini (ESP32-S2) | Deploys hang on CircuitPython 10.1.4 | Upgrade CircuitPython past 10.1.4. |
| Lolin S2 Mini (ESP32-S2) | Each CircuitPython deploy takes 30 to 60 seconds | The board writes flash slowly. Wait it out; it isn't hung. |
| Lolin S2 Mini (ESP32-S2) | Websocket or HTTP messages arrive split differently than on other boards | Give receive buffers some headroom over your largest message. |
| Lolin S2 Mini (ESP32-S2) | The USB serial connection drops in the middle of long output | Reset and replug, and keep tail sessions short. |
| Lolin S2 Mini (ESP32-S2) | `CIRCUITPY` arrives corrupted, or turns read-only on a flaky cable | Swap to a cable you trust, then rebuild the filesystem with `python3 run.py reset-board --device <id> --yes`. |
| ESP32-S3 from Unexpected Maker, P4 and P7 revisions made before 2024 (FeatherS3, TinyS3) | Every wifi join fails with status 202 or 205 at full transmit power | Set `tx_power_dbm = 15` under `[wifi]` in `secrets.toml`. See [WiFi won't connect](wifi-wont-connect.md). |
| ESP32-S3 | A failed join leaves the radio half-connected, and the next try fails slowly with `Unknown failure 205` | `chumicro-wifi` resets the radio before every join attempt to clear this. Code that calls `wifi.radio.connect()` itself should call `wifi.radio.stop_station()` first. |
| ESP32-S3 | Some individual boards have weak radios; a MAC address starting with zeros is the tell | Reseat or replace the board, or use one with an external antenna. |
| ESP32-S3 | More than 200 KB of memory free after wifi joins | Room enough for HTTPS even in RAM mode, unlike the Pico W. |
| Classic ESP32 (TinyPICO, no native USB) | CircuitPython 10.2.0 corrupts the running program at random (`'Runner' object has no attribute 'tick'`, garbage in attribute names) | Run classic ESP32 boards on MicroPython. |
| SAMD21, nRF52, and SAMD51 on CircuitPython | ChuMicro libraries fail to import, naming `deque` | CircuitPython builds for these chips leave out `deque`, and most of the chips have less than the 256 KB of RAM ChuMicro needs. Use an ESP32, RP2040, RP2350, or STM32 board. See [Running out of memory](out-of-memory.md). |
| SAMD21 | `KVStoreFull` after a few values | Its NVM holds only 256 bytes. Keep saved state tiny, or move to a board with more. See [Persisting data](persisting-data.md). |
