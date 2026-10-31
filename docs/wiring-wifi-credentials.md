# Wiring WiFi credentials

Your wifi name and password live in one file on your laptop, `secrets.toml`, and never in your code.  Each deploy copies them to the board, and your program reads them there.

## The smallest secrets.toml

```toml
[wifi]
ssid = "your-network"
password = "your-password"
```

The file sits at the top of your workspace, next to `workspace.yml`, and git ignores it, so the password stays out of your history.  Workspace setup creates it with placeholder values that never join anything; replace the two values with your own.

Deploy as usual:

```bash
python3 run.py deploy <project>
```

On the board, `load_runtime_config()` hands your program the values, and `WifiService.from_config()` picks out `wifi.ssid` and `wifi.password`:

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

If the board never prints `wifi: connecting -> connected`, [WiFi won't connect](troubleshooting/wifi-wont-connect.md) starts from that symptom.

## What the deploy does with it

The deploy merges `secrets.toml` with the project's own `project_config.toml`, joins each table name and key with a dot, so `ssid` under `[wifi]` becomes `wifi.ssid`, and writes the result to `/runtime_config.msgpack` on the board.  `load_runtime_config()` reads that file back as a dictionary keyed by the dotted names.

Two commands show the result without touching a board:

```bash
python3 run.py dump-config <project>       # print what the board will receive
python3 run.py config-validate <project>   # check every library finds the keys it needs
```

`secrets.toml` holds credentials and the defaults every project shares.  Settings that are not secret, such as an MQTT topic or a sample period, go in `projects/<name>/project_config.toml`, which is safe to commit and wins over `secrets.toml` for any key both files set.

## Adding an MQTT broker

`chumicro-mqtt` has no default broker, so `MQTTClient.from_config()` stops with a missing-key error until you name one:

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

The repository is a workspace too, with its own gitignored `secrets.toml` at the root.  `python3 scripts/prepare_workspace.py` creates it from the same placeholder template on first run.  Fill in `[wifi]`, and `[mqtt.broker]` for the MQTT examples, then deploy any networked example:

```bash
chumicro-workspace deploy-example wifi connect_to_ap --tail
```

The library examples and the hardware tests under each library's `functional_tests/` read the same file.

## Without a workspace

Copying an example straight to the board as `code.py` (CircuitPython) or `main.py` (MicroPython) skips the deploy, so no `/runtime_config.msgpack` reaches the board.  Most networked examples carry constants near the top for this case:

```python
WIFI_SSID = "your-wifi-ssid"          # replace before copying
WIFI_PASSWORD = "your-wifi-password"  # replace before copying
```

Those examples import `wifi_up()` from the `helpers.py` beside them, so copy `helpers.py` to the board too.  When a `/runtime_config.msgpack` is present, its values win over the constants.  When it is absent, the constants are used, and `wifi_up()` stops with a `RuntimeError` naming them if they still hold the placeholders.  The MQTT examples add a `BROKER_HOST` constant, empty until you set it.  `connect_to_ap.py` in `chumicro-wifi` has no constants and needs a workspace deploy.

In your own code without a workspace, build the settings in code instead of reading them from the board:

```python
from chumicro_wifi import WifiConfig, WifiService

wifi = WifiService(WifiConfig(ssid="your-network", password="your-password"))
```

That puts the password in a file on the board, so keep that file out of git.
