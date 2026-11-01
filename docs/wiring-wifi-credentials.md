# Wiring WiFi credentials

Your WiFi name and password live in one file on your laptop, `secrets.toml`, and never in your code.  Each deploy copies them to the board, where your program reads them.

## The smallest secrets.toml

```toml
[wifi]
ssid = "your-network"
password = "your-password"
```

The file sits at the top of your workspace, next to `workspace.yml`.  Git ignores it, so the password stays out of your history.  `python3 run.py setup` creates the file with placeholder values.  Replace both with your own, then deploy:

```bash
python3 run.py deploy <project>
```

On the board, `load_runtime_config()` returns the values.  `WifiService.from_config()` picks out `wifi.ssid` and `wifi.password`:

```python
from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_wifi import WifiService


def show_wifi(old_state, new_state):
    print("wifi:", old_state, "->", new_state)


config = load_runtime_config()
wifi = WifiService.from_config(config)
wifi.on_state_change(show_wifi)

runner = Runner()
runner.add(wifi)

while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

When the board never prints `wifi: connecting -> connected`, [WiFi won't connect](troubleshooting/wifi-wont-connect.md) starts from that symptom.

## What the deploy does with it

Each deploy merges `secrets.toml` with the project's own `project_config.toml`.  It joins each table name and key with a dot, so `ssid` under `[wifi]` becomes `wifi.ssid`.  It writes the result to `/runtime_config.msgpack` on the board.  `load_runtime_config()` reads that file back as a dictionary keyed by the dotted names.

`dump-config` and `config-validate` read the merged settings without touching a board:

```bash
python3 run.py dump-config <project>       # print what the board will receive
python3 run.py config-validate <project>   # check every library finds the keys it needs
```

`secrets.toml` holds credentials and the defaults every project shares.  Settings that are not secret, such as an MQTT topic or a sample period, go in `projects/<name>/project_config.toml`.  That file is safe to commit.  For a key both files set, `project_config.toml` wins.

## CircuitPython auto-connect

CircuitPython reads `CIRCUITPY_WIFI_SSID` and `CIRCUITPY_WIFI_PASSWORD` from a `settings.toml` on the board.  Those keys switch on the firmware's own auto-connect, which fights `WifiService` for the radio.  Keep them out of `settings.toml`.  A workspace deploy removes `settings.toml` from the board for that reason.

## Adding an MQTT broker

`chumicro-mqtt` ships with no default broker.  `MQTTClient.from_config()` raises a missing-key error until `secrets.toml` names one:

```toml
[wifi]
ssid = "your-network"
password = "your-password"

[mqtt]
username = "your-mqtt-user"       # only if your broker asks for a login
password = "your-mqtt-password"

[mqtt.broker]
host = "broker.example.com"       # your broker's name or IP address
port = 1883
```

## Keys the libraries read

| Key | Read by | Needed |
|---|---|---|
| `wifi.ssid`, `wifi.password` | `WifiService.from_config()` | Yes |
| `wifi.hostname`, `wifi.connect_timeout_ms`, `wifi.first_connect_timeout_ms`, `wifi.reconnect_backoff_start_ms`, `wifi.reconnect_backoff_max_ms`, `wifi.reconnect_max`, `wifi.power_save`, `wifi.tx_power_dbm` | `WifiService.from_config()` | No, each has a default |
| `mqtt.broker.host`, `mqtt.broker.port` | `MQTTClient.from_config()` | Yes |
| `mqtt.username`, `mqtt.password`, `mqtt.client_id`, `mqtt.keep_alive_seconds`, `mqtt.when_disconnected` | `MQTTClient.from_config()` | No, each has a default |

## Running an example from a clone of the ChuMicro repository

A clone of the ChuMicro repository is a workspace too, with its own gitignored `secrets.toml` at the root.  `python3 scripts/prepare_workspace.py` creates that file with placeholder values on its first run.  Fill in `[wifi]`, plus `[mqtt.broker]` for the MQTT examples.  Then deploy any networked example:

```bash
chumicro-workspace deploy-example wifi connect_to_ap --tail
```

The library examples and the hardware tests under each library's `functional_tests/` read the same file.

## Without a workspace

An example copied straight to the board as `code.py` or `main.py` skips the deploy, so no `/runtime_config.msgpack` reaches the board.  Most networked examples carry constants near the top for this case:

```python
WIFI_SSID = "your-wifi-ssid"          # replace before copying
WIFI_PASSWORD = "your-wifi-password"  # replace before copying
```

Those examples import `wifi_up()` from the `helpers.py` beside them.  Copy `helpers.py` to the board too.  When `/runtime_config.msgpack` is present, its values win over the constants.  When it is absent, `wifi_up()` uses the constants.  If they still hold the placeholders, `wifi_up()` raises a `RuntimeError` that names them.  The MQTT examples add a `BROKER_HOST` constant, empty until you set it.  `connect_to_ap.py` in `chumicro-wifi` reads its settings only from a deploy, so it needs a workspace.

Your own code can build the settings itself instead of reading them from the board:

```python
from chumicro_wifi import WifiConfig, WifiService

wifi = WifiService(WifiConfig(ssid="your-network", password="your-password"))
```

That puts the password in a file on the board.  Keep that file out of git.
