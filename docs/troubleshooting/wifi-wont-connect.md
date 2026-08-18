# WiFi won't connect

This page is for when a board in your workspace won't join wifi, or joins and then behaves strangely.  Most week-one wifi trouble is one of five traps: credentials that never reached the board, a silent drop that raises nothing, a connect that freezes everything else, a specific board that needs its transmit power turned down, or a `settings.toml` that fights the wifi library for the radio.

## The functional tests all skip, or a deployed example never joins anything

The credentials never reached the board.  Wifi credentials start in `secrets.toml` at the workspace root, which the deploy merges into `/runtime_config.msgpack` for the board to read back.  Workspace setup materializes that file from a template with deliberately bogus placeholder values, so a fresh clone can't join a network by accident, and two states leave you with nothing happening and no wifi error to read:

- **`secrets.toml` is missing.**  Nothing is staged, so `load_runtime_config()` on the board raises `OSError`.  The networking libraries' functional tests catch this at collection time and skip every device test with a message naming the keys they wanted.  A deployed example has no such guard: it dies on the board, which you see only if you are tailing the serial output.
- **`secrets.toml` is there but still carries the placeholder SSID** (`replace-with-your-ap-ssid`).  The functional-test conftests read that placeholder as "no credentials yet" and stage nothing, so those tests skip the same way.  A deployed example fails fast instead: its helpers recognize both the in-file `WIFI_SSID` placeholder and the `secrets.toml` one, and raise immediately with a message naming where to put real credentials.

**Fix.** Put your real network name and password in the workspace-root `secrets.toml`, then deploy again:

```toml
# secrets.toml: gitignored, never committed
[wifi]
ssid = "your-network"
password = "your-password"
```

`chumicro-workspace dump-config <project>` prints the merged config a deploy would send, so you can confirm `wifi.ssid` before touching the board, and `chumicro-workspace deploy <project> --tail` shows what the board says once it boots.  (details: [Device testing](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/device-testing.md#configure-secretstoml))

## The board sits in `RECONNECTING`, nothing is raised, and `wifi.last_error` is `None`

On MicroPython on a Pi Pico W (the CYW43 radio), `connect()` returns right away and leaves `isconnected()` False without raising anything.  There is no exception and no error to read, so code that waits on `last_error` waits forever.

**Fix.** Don't gate recovery on `last_error`.  Check `wifi.state` and `wifi.connected` instead, which each adapter re-derives from `isconnected()` after every connect attempt.

## Everything else freezes for up to 15 seconds while a CircuitPython board connects

CircuitPython's `wifi.radio.connect()` blocks, and the firmware exposes no non-blocking variant.  While the board is `CONNECTING` or `RECONNECTING`, every other runner service (an LED heartbeat, an in-flight HTTP request, MQTT keep-alives) pauses, for up to `connect_timeout_ms` (default 15000).

**Fix.** Expect the stall on CircuitPython, and connect before you start time-critical work.  If a non-blocking connect is load-bearing, run MicroPython on an RP2040, RP2350, or ESP32 board, where `wlan.connect()` is non-blocking.

## Every join attempt fails with status 202 or 205 on a board that worked hours ago

A pre-2024 ESP32-S3 (the UM "P4" revision) has vendor-documented wifi instability, worst at full 20 dBm transmit power with native USB.  The tell is a marginal signal reading (RSSI around -82 where a healthy board reads -54) and hard join failures on every attempt through radio cycles.

**Fix.** Turn the radio's transmit power down to about 75% in your deploy config:

```
wifi.tx_power_dbm = 15
```

CircuitPython maps this to `wifi.radio.tx_power` and MicroPython to `sta.config(txpower=)`.  At `txpower=15` the same board joins in about 2 seconds with no loss.  This is a config knob only; the library never inspects the board for you.

## Flaky or competing wifi on CircuitPython

`CIRCUITPY_WIFI_SSID` and the other `CIRCUITPY_WIFI_*` keys in `settings.toml` switch on CircuitPython's own auto-connect supervisor, which then fights `chumicro-wifi` for control of the radio.  `settings.toml` is CircuitPython-only (MicroPython never reads it) and is reserved for `CIRCUITPY_*` keys.

**Fix.** Keep `CIRCUITPY_WIFI_*` out of `settings.toml`.  Put wifi and app config in `secrets.toml`, which the deploy converts to `runtime_config.msgpack` on the board, and ship a `settings.toml` with no wifi keys.  (background: [Decision 0057](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0057-two-file-config.md))
