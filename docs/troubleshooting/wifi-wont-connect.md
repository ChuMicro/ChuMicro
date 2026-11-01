# WiFi won't connect

A board that never joins wifi has, most often, never received your network name and password.

## The board never joins, and `wifi.last_error` is `None`

The `connect_to_ap.py` example in `chumicro-wifi` prints `joining <network name>` first. When it prints `joining replace-with-your-ap-ssid`, your real network never reached the deploy.

To check any project, print the config the deploy sends to the board:

```bash
python3 run.py dump-config <project>
```

A `wifi.ssid` of `replace-with-your-ap-ssid` means `secrets.toml` still holds the placeholder it was created with, and the board is trying to join a network by that name. A `FileNotFoundError` naming `secrets.toml` means the file is missing. `python3 run.py setup` creates it again, placeholders included.

Put your network's name and password in `secrets.toml` in the [workspace](../glossary.md#workspace) folder:

```toml
[wifi]
ssid = "your-network"
password = "your-password"
```

Then deploy again and watch what the board prints:

```bash
python3 run.py deploy <project> --tail
```

When the name and password are right and the board still never joins:

- Check the band. ESP32, ESP32-S2, ESP32-S3, and Pi Pico W radios see only 2.4 GHz networks, so a router that offers only 5 GHz is invisible to them.
- Check spelling and case. Network names and passwords are case-sensitive.

`wifi.last_error` stays `None` because a wrong name or password raises nothing readable. On CircuitPython, `WifiService` catches the radio's connection error and counts a failed attempt. A Pi Pico W on MicroPython stays unconnected without raising at all. An ESP32 on MicroPython does raise, and `last_error` holds that error.

`WifiService` then tries again after one second, doubles the wait after each failure up to a minute, and keeps trying forever, with `wifi.state` reading `"connecting"`. Watch `wifi.state` and `wifi.connected` to see what the radio is doing. To make it give up, set `reconnect_max`, a number of attempts, under `[wifi]` in `secrets.toml`. `wifi.state` becomes `"failed"` once the attempts run out.

[Wiring wifi credentials](../wiring-wifi-credentials.md) covers where credentials live and how they reach the board.

## An example stops with `RuntimeError: set WIFI_SSID + WIFI_PASSWORD at the top of the example`

Put your network in `secrets.toml` as the previous section shows, and deploy the example again. For an example copied onto a board by hand, type your network into the `WIFI_SSID` and `WIFI_PASSWORD` lines at its top.

Several library examples check for placeholder credentials before touching the radio. The deploy sent no real network name, so the example stopped rather than try to join `your-wifi-ssid`.

## Everything freezes for up to 15 seconds while a CircuitPython board connects

Join wifi before you start anything that has to keep time. To shorten each stall, lower `connect_timeout_ms` under `[wifi]` in `secrets.toml`. `first_connect_timeout_ms` sets the first attempt's limit on its own.

CircuitPython's `wifi.radio.connect()` waits until it joins or gives up, and the firmware offers no call that returns early. While `WifiService` connects on CircuitPython, everything else in your loop waits with it: a blinking LED, an HTTP request, MQTT keep-alive messages. Each attempt holds the loop for up to `connect_timeout_ms`, which defaults to 15000, or 15 seconds.

On MicroPython the join runs in the background, so the loop keeps going while the board connects.

## Joins fail every time on an ESP32-S3 board that worked earlier

Look for a weak signal reading where a neighbouring board reads strong, and joins that fail on every attempt with status 202 or 205.

Turn the transmit power down to 15 dBm, about three quarters of full power, under `[wifi]` in `secrets.toml`:

```toml
[wifi]
ssid = "your-network"
password = "your-password"
tx_power_dbm = 15
```

On the bench, a board that failed every join at full power joined in two seconds at 15. The wifi library applies the value you set, and leaves a board without the setting at full power.

Unexpected Maker [documents](https://help.unexpectedmaker.com/docs/boards/wifi-stability-issues/) its early ESP32-S3 boards, the P4 and P7 revisions made before 2024, as unstable at full transmit power.

## WiFi drops or fights itself on CircuitPython

Keep wifi settings in the workspace's `secrets.toml`, and out of the board's `settings.toml`. A deploy removes a `settings.toml` it finds on the board, and prints a warning when it does.

A `settings.toml` on the board with `CIRCUITPY_WIFI_SSID` or another `CIRCUITPY_WIFI_*` key makes CircuitPython join wifi on its own at startup. It then competes with the wifi library for the radio, and connections drop or never settle. MicroPython never reads `settings.toml`.
