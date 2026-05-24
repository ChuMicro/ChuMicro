"""Host-side fixtures for chumicro-mqtt functional tests.

Two responsibilities:

1. Register the merged runtime-config dict (secrets.toml + per-library
   overrides) with pytest-device so it stages at
   `/runtime_config.msgpack` on the device. On-device tests read wifi
   creds + the `mqtt.broker` host/port from there.
2. Spawn a host-side Mosquitto broker on the LAN interface so
   `test_real_broker.py` has a counterparty.

The broker comes up via `chumicro_pytest_device.fixtures.mosquitto.
start_mosquitto_broker`. When `mosquitto` is not on PATH or the LAN IP
can't be detected, the broker fixture stays down and the test runs
against whatever `mqtt.broker.host` / `mqtt.broker.port` the user has
put in `secrets.toml` (or the per-library `config.toml` override).
`MQTTClient.from_config` raises `MissingConfigKey` if neither source
supplies them.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from chumicro_pytest_device.fixtures.lan import detect_lan_ip
from chumicro_pytest_device.fixtures.mosquitto import start_mosquitto_broker
from chumicro_pytest_device.runtime_config import set_runtime_config
from chumicro_workspace import compose_runtime_config

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_SECRETS_TOML = _REPO_ROOT / "secrets.toml"
_LIBRARY_CONFIG = _HERE / "config.toml"  # optional, absent leaves workspace defaults only


def _merged_runtime_config_with_creds() -> dict | None:
    """Return the deep-merged + flattened runtime-config dict, or `None`."""
    if not _SECRETS_TOML.is_file():
        return None
    # Any exception from `compose_runtime_config` propagates. A
    # malformed `secrets.toml` is a real bug to surface, not the same
    # shape as a fresh-clone "user hasn't filled it in yet." The
    # missing-file path above is the only silent-skip case.
    merged = compose_runtime_config(
        secrets_toml=_SECRETS_TOML,
        project_config=_LIBRARY_CONFIG,
    )
    ssid = merged.get("wifi.ssid")
    password = merged.get("wifi.password")
    if not isinstance(ssid, str) or not isinstance(password, str):
        return None
    if ssid == "replace-with-your-ap-ssid":
        return None
    return merged


_BROKER_PROCESS: subprocess.Popen[bytes] | None = None
_BROKER_WORKDIR: Path | None = None


#: Placeholder broker hostname shipped in the secrets.toml starter
#: (the chumicro_workspace payload). Treated as "broker unset" so the
#: pytest-device plugin skips at collection time with a clear missing-
#: keys message instead of letting the test run against a hostname
#: that won't resolve.
_BROKER_PLACEHOLDER = "replace-with-your-broker-host"


def pytest_configure(config: pytest.Config) -> None:
    """Spin up the host Mosquitto broker. Register the runtime-config payload."""
    global _BROKER_PROCESS, _BROKER_WORKDIR

    merged = _merged_runtime_config_with_creds()

    if merged is not None:
        lan_ip = detect_lan_ip()
        if lan_ip is not None:
            workdir = Path(tempfile.mkdtemp(prefix="chumicro_mqtt_broker_"))
            broker = start_mosquitto_broker(lan_ip, workdir)
            if broker is not None:
                _BROKER_PROCESS, broker_port = broker
                _BROKER_WORKDIR = workdir
                merged["mqtt.broker.host"] = lan_ip
                merged["mqtt.broker.port"] = broker_port
            else:
                shutil.rmtree(workdir, ignore_errors=True)

        # If the local mosquitto fixture didn't take over, honor the
        # workspace-template placeholder by suppressing the payload.
        # `required_keys` then skips the session at collection time.
        # Mirrors the wifi-ssid placeholder handling above.
        if merged.get("mqtt.broker.host") == _BROKER_PLACEHOLDER:
            merged = None

    set_runtime_config(
        config,
        merged,
        required_keys=(
            "wifi.ssid",
            "wifi.password",
            "mqtt.broker.host",
            "mqtt.broker.port",
        ),
    )


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001 - pytest hook
    """Tear down the Mosquitto broker."""
    global _BROKER_PROCESS, _BROKER_WORKDIR
    if _BROKER_PROCESS is not None:
        _BROKER_PROCESS.terminate()
        try:
            _BROKER_PROCESS.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _BROKER_PROCESS.kill()
        _BROKER_PROCESS = None
    if _BROKER_WORKDIR is not None and _BROKER_WORKDIR.exists():
        shutil.rmtree(_BROKER_WORKDIR, ignore_errors=True)
        _BROKER_WORKDIR = None
