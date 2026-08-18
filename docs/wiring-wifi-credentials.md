# Wiring wifi credentials for examples and functional tests

The examples and `functional_tests/test_real_*.py` suites in the network-shaped libraries ([`chumicro-wifi`](https://chumicro.com/ChuMicro/wifi/stable/), [`chumicro-requests`](https://chumicro.com/ChuMicro/requests/stable/), [`chumicro-http-server`](https://chumicro.com/ChuMicro/http_server/stable/), [`chumicro-mqtt`](https://chumicro.com/ChuMicro/mqtt/stable/), [`chumicro-websockets`](https://chumicro.com/ChuMicro/websockets/stable/), [`chumicro-ntp`](https://chumicro.com/ChuMicro/ntp/stable/)) need wifi credentials before they can run on real hardware.

How you get credentials onto the device depends on how you're running the code: out of a clone of this repository, out of a [`chumicro-workspace`](https://chumicro.com/ChuMicro/workspace/stable/) project, or by copying a single example file to the board by hand.

## Running an example from a clone of this repository

`chumicro-workspace deploy-example` deploys straight out of a clone, because this repository is itself a workspace and its `secrets.toml` sits at the repository root.  `python3 scripts/prepare_workspace.py` creates that file from a template on first run, filled with placeholder values so a fresh clone can't join a network by accident.

Edit it once per clone:

```toml
# secrets.toml at the repository root: gitignored, never committed
[wifi]
ssid = "your-network"
password = "your-password"

[mqtt.broker]
host = "broker.example.com"
port = 1883
```

Then deploy any of the networked examples:

```bash
chumicro-workspace deploy-example wifi connect_to_ap --tail
```

The deploy bakes `secrets.toml` into `/runtime_config.msgpack` on the board, and the example reads it back with `chumicro_config.load_runtime_config()`.  Leave the placeholder SSID in place and the example deploys fine but never joins anything; [WiFi won't connect](troubleshooting/wifi-wont-connect.md) covers what that looks like.

Point `mqtt.broker.host` at a broker you control before running the mqtt examples.  `chumicro-mqtt` refuses to dial a third-party broker on your behalf, so it stays a placeholder until you fill it in.

## Recommended: use a chumicro-workspace

Put your wifi credentials, and the broker settings where they're relevant, in your workspace's gitignored `secrets.toml`:

```toml
# secrets.toml: gitignored, never committed
[wifi]
ssid = "your-network"
password = "your-password"

[mqtt.broker]
host = "broker.example.com"
port = 1883
```

Then deploy with `chumicro-workspace deploy <project>`.  The bake-and-deploy pipeline merges `secrets.toml` with the project's `project_config.toml`, flattens the result to dotted keys (`wifi.ssid`, `mqtt.broker.host`), and writes it to `/runtime_config.msgpack` on the device.  The example reads it back via `chumicro_config.load_runtime_config()`; see [`chumicro-config`](https://chumicro.com/ChuMicro/config/stable/) for the standard pattern.

The split is intentional.  `secrets.toml` holds credentials plus the workspace-wide defaults a project inherits, and never leaves your machine.  Non-secret per-project configuration goes in `projects/<name>/project_config.toml`, which is safe to commit and deep-merges over the `secrets.toml` defaults at any nesting depth.  (`workspace.yml` is a third file in a workspace, but it configures the tooling itself, library sources and deploy targets and quality knobs, and nothing in it reaches the board.)  See [config files](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/config-files.md) for the full field lists.

## Raw single-file deploy (no workspace)

If you're copying an example file directly to `/code.py` (CircuitPython) or `/main.py` (MicroPython) without a workspace, edit the constants near the top of the example before copying.  The pattern across most of these examples is:

```python
WIFI_SSID = "your-wifi-ssid"          # replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # replace before deploying

# For MQTT examples:
BROKER_HOST = "broker.example.com"
BROKER_PORT = 1883
TOPIC = "demo/telemetry"
```

The constants act as the fallback when no `runtime_config.msgpack` is present on the device, so the same example file works in both modes.  Forget to edit them and the shared `examples/helpers.py` catches it: `wifi_up()` raises a `RuntimeError` naming the two constants rather than trying to join `your-wifi-ssid`.  `chumicro-wifi`'s own `connect_to_ap.py` is the exception, with no constants to edit: it reads the deployed config directly, so it needs one of the two workspace routes above.

## What the library reads

None of the network-shaped libraries reads `secrets.toml`, `project_config.toml`, or `runtime_config.msgpack` directly.  They all take a typed config object (`WifiConfig`, `HttpClient`, `MQTTClient(...)`) and a transport handle, and go.  The config wiring is application-layer: `chumicro-config` is what reads the msgpack, and your example or app code is what wires the typed config into the library.

See [`chumicro-config`](https://chumicro.com/ChuMicro/config/stable/) and [`chumicro-workspace`](https://chumicro.com/ChuMicro/workspace/stable/) for the deploy-time mechanics.
