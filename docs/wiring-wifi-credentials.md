# Wiring wifi credentials for examples and functional tests

The hardware-prefixed examples and `functional_tests/test_real_*.py` suites in the network-shaped libraries — [`chumicro-wifi`](../libraries/wifi/), [`chumicro-requests`](../libraries/requests/), [`chumicro-http-server`](../libraries/http_server/), [`chumicro-mqtt`](../libraries/mqtt/), [`chumicro-websockets`](../libraries/websockets/), [`chumicro-ntp`](../libraries/ntp/) — need wifi credentials before they can run on real hardware.

There are two ways to get credentials onto the device, depending on whether you're using a [`chumicro-workspace`](../workbench/workspace/) project layout.

## Recommended: use a chumicro-workspace

Put your wifi credentials (and, where relevant, broker host / port / topic settings) in your workspace's gitignored `secrets.toml` and `workspace.yml`:

```toml
# secrets.toml — gitignored, never committed
[wifi]
ssid = "your-network"
password = "your-password"
```

```yaml
# workspace.yml — gitignored, workspace-wide defaults
mqtt:
  broker:
    host: broker.example.com
    port: 1883
```

Then deploy with `chumicro-workspace deploy <project>`.  The bake-and-deploy pipeline merges `workspace.yml` + `secrets.toml` + per-project `project_config.toml` and writes the result to `/runtime_config.msgpack` on the device.  The example reads it back via `chumicro_config.load_runtime_config()` — see [`chumicro-config`](../libraries/config/) for the standard pattern.

The two-file split (`workspace.yml` for non-secret defaults, `secrets.toml` for credentials) is intentional — `workspace.yml` can be shared across teammates if you want, while `secrets.toml` never leaves your machine.  Per-project overrides go in `projects/<name>/project_config.toml`.

## Raw single-file deploy (no workspace)

If you're copying an example file directly to `/code.py` (CircuitPython) or `/main.py` (MicroPython) without a workspace, edit the constants near the top of the example before copying.  The pattern across all the hardware-prefixed examples is:

```python
WIFI_SSID = "your-network"            # ← replace before deploying
WIFI_PASSWORD = "your-password"

# For MQTT examples:
BROKER_HOST = "broker.example.com"
BROKER_PORT = 1883
TOPIC = "demo/telemetry"
```

The constants act as the fallback when no `runtime_config.msgpack` is present on the device, so the same example file works in both modes.

## What the library reads

None of the network-shaped libraries reads either `workspace.yml`, `secrets.toml`, or `runtime_config.msgpack` directly.  They all take a typed config object (`WifiConfig`, `HttpClient`, `MQTTClient(...)`) and a transport handle, and go.  The config wiring is application-layer — `chumicro-config` is what reads the msgpack, and your example or app code is what wires the typed config into the library.

See [`chumicro-config`](../libraries/config/) and [`chumicro-workspace`](../workbench/workspace/) for the deploy-time mechanics.
