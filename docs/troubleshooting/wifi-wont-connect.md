# WiFi won't connect

This page is for a board that never joins your wifi, or joins and then drops or stalls. Start with the first section: most of the time the board never received your network name and password.

## The board never joins, and `wifi.last_error` is `None`

The quickest check is the first line the wifi example prints. `connect_to_ap` in `chumicro-wifi` opens with `joining <your network name>`; if it prints `joining replace-with-your-ap-ssid`, your real network never made it into the deploy.

To check any project, look at what the deploy sends to the board:

```bash
python3 run.py dump-config <project>
```

Look at `wifi.ssid`. If it reads `replace-with-your-ap-ssid`, the board is trying to join a network by that name: `secrets.toml` still holds the placeholder it was created with. If the command stops with a `FileNotFoundError` naming `secrets.toml`, the file is missing; `python3 run.py setup` creates it again with the placeholders in it.

Put your network's name and password in `secrets.toml` in the workbench folder, then deploy again and watch what the board prints:

```toml
[wifi]
ssid = "your-network"
password = "your-password"
```

```bash
python3 run.py deploy <project> --tail
```

If the name and password are right and the board still never joins:

- Check the band. ESP32, ESP32-S2, ESP32-S3, and Pi Pico W radios only see 2.4 GHz networks, so a router that offers only 5 GHz is invisible to them.
- Check spelling and case. Network names and passwords are case-sensitive.

`wifi.last_error` stays `None` because a wrong name or password raises nothing you can read. On CircuitPython, `WifiService` catches the radio's connection error and counts a failed attempt. A Pi Pico W on MicroPython stays unconnected without raising at all. (An ESP32 on MicroPython does raise, and `last_error` holds that error.) `WifiService` then tries again, one second later at first, doubling the wait each time up to a minute, and keeps trying forever, with `wifi.state` reading `"connecting"`. Watch `wifi.state` and `wifi.connected` to see what the radio is doing. To have it give up instead, set `reconnect_max` (a number of attempts) under `[wifi]` in `secrets.toml`; `wifi.state` becomes `"failed"` when it runs out.

[Wiring wifi credentials](../wiring-wifi-credentials.md) covers where credentials live and how they reach the board. In the ChuMicro repository, the same missing credentials make the networking libraries' hardware tests skip, each with a message naming the keys it needs.

## An example stops with `RuntimeError: set WIFI_SSID + WIFI_PASSWORD at the top of the example`

Several library examples check for placeholder credentials before touching the radio. The deploy sent no real network name, so the example stopped rather than try to join `your-wifi-ssid`.

Put your network in `secrets.toml` as shown above and deploy the example again. If you copy the example onto a board by hand instead of deploying it, type your network into the `WIFI_SSID` and `WIFI_PASSWORD` lines at its top.

## Everything freezes for up to 15 seconds while a CircuitPython board connects

CircuitPython's `wifi.radio.connect()` waits until it joins or gives up, and the firmware offers no version that returns early. While `WifiService` is connecting on CircuitPython, everything else in your loop (a blinking LED, an HTTP request, MQTT keep-alive messages) waits with it, for up to `connect_timeout_ms` per attempt: 15000, which is 15 seconds, unless you set it.

Join wifi before you start anything that has to keep time. To shorten each stall, lower `connect_timeout_ms` under `[wifi]` in `secrets.toml`. On MicroPython the join runs in the background, so the loop keeps going while the board connects.

## Joins fail every time on an ESP32-S3 board that worked earlier

Early ESP32-S3 boards from Unexpected Maker (P4 and P7 revisions made before 2024) are [documented by the vendor](https://help.unexpectedmaker.com/docs/boards/wifi-stability-issues/) as unstable at full transmit power. The tell is a weak signal reading where a neighbouring board reads strong, and joins that fail on every attempt with status 202 or 205.

Turn the transmit power down to 15 dBm, about three quarters of full power, under `[wifi]` in `secrets.toml`:

```toml
[wifi]
ssid = "your-network"
password = "your-password"
tx_power_dbm = 15
```

On the bench, a board that failed every join at full power joined in two seconds at 15. The wifi library applies whatever value you set and never guesses from the board, so a board without the problem keeps its full power.

## WiFi drops or fights itself on CircuitPython

A `settings.toml` on the board with `CIRCUITPY_WIFI_SSID` or another `CIRCUITPY_WIFI_*` key makes CircuitPython join wifi on its own at startup. It then competes with the wifi library for the radio, and connections drop or never settle.

Keep wifi settings in the workbench's `secrets.toml` and out of the board's `settings.toml`. A deploy already removes a `settings.toml` it finds on the board and prints a warning when it does. MicroPython never reads `settings.toml`.
