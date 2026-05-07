"""Host-side fixtures for chumicro-mqtt functional tests.

Two responsibilities:

1. Register the merged runtime-config dict (secrets.toml +
   per-library overrides) with pytest-device so it stages at
   ``/runtime_config.msgpack`` on the device — on-device tests read
   wifi creds + the ``mqtt.broker`` host/port from there.
2. Spawn a host-side Mosquitto broker on the LAN interface so
   ``test_real_broker.py`` has a counterparty.  We bring up our own
   broker because the LAN-bound listener gives us a deterministic,
   CI-shaped fixture — no flakiness from the open internet.

The broker fixture mirrors the ``test_mosquitto_integration.py``
``mosquitto_broker`` fixture from the host-side test suite — same
macOS ``setrlimit(RLIMIT_NOFILE)`` workaround for Mosquitto 2.0 on
Apple Silicon.

If ``mosquitto`` is not on ``PATH`` or the LAN IP can't be detected,
the broker fixture stays down and the test runs against whatever
``mqtt.broker.host`` / ``mqtt.broker.port`` the user has put in
``secrets.toml`` (or the per-library ``config.toml`` override) —
``MQTTClient.from_config`` raises ``MissingConfigKey`` if neither
source supplies them.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
from chumicro_pytest_device.runtime_config import set_runtime_config
from chumicro_workspace import compose_runtime_config

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_SECRETS_TOML = _REPO_ROOT / "secrets.toml"
_LIBRARY_CONFIG = _HERE / "config.toml"  # optional; absent → workspace defaults only


def _merged_runtime_config_with_creds() -> dict | None:
    """Return the deep-merged + flattened runtime-config dict, or ``None``."""
    if not _SECRETS_TOML.is_file():
        return None
    # Any exception from ``compose_runtime_config`` propagates — a
    # malformed ``secrets.toml`` is a real bug to surface, not the
    # same shape as a fresh-clone "user hasn't filled it in yet."
    # The missing-file path above is the only silent-skip case.
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


def _detect_lan_ip() -> str | None:
    """Return the host's primary LAN IPv4, or ``None`` if undetectable."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        host, _port = sock.getsockname()
        if host.startswith("127."):
            return None
        return host
    except OSError:
        return None
    finally:
        sock.close()


def _find_free_port(bind_host: str) -> int:
    """Bind a temporary socket on *bind_host* and return the OS-allocated port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((bind_host, 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _wait_until_listening(host: str, port: int, *, deadline_seconds: float = 5.0) -> bool:
    """Poll ``(host, port)`` until something accepts a TCP connect."""
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        try:
            probe = socket.create_connection((host, port), timeout=0.5)
        except OSError:
            time.sleep(0.05)
            continue
        probe.close()
        return True
    return False


def _start_mosquitto_broker(
    bind_host: str,
    workdir: Path,
) -> tuple[subprocess.Popen[bytes], int] | None:
    """Spawn Mosquitto bound on *bind_host*; return ``(process, port)`` or ``None``."""
    if shutil.which("mosquitto") is None:
        return None

    port = _find_free_port(bind_host)
    config_path = workdir / "broker.conf"
    config_path.write_text(
        f"listener {port} {bind_host}\n"
        "allow_anonymous true\n"
        "persistence false\n"
        f"log_dest file {workdir}/broker.log\n",
    )

    # Mosquitto 2.0 on macOS / Apple Silicon fails with
    # "Error: Out of memory" when it inherits the default soft limit
    # for ``RLIMIT_NOFILE``.  Drop it in the child via preexec_fn so
    # mosquitto's setrlimit upgrade no-ops.
    def _reduce_fd_limit() -> None:  # pragma: no cover — runs in spawned child
        import resource  # noqa: PLC0415

        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))

    process = subprocess.Popen(
        ["mosquitto", "-c", str(config_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=_reduce_fd_limit,  # noqa: PLW1509 — needed for macOS rlimit quirk
    )
    if not _wait_until_listening(bind_host, port):
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
        return None
    return process, port


_BROKER_PROCESS: subprocess.Popen[bytes] | None = None
_BROKER_WORKDIR: Path | None = None


#: Placeholder broker hostname shipped in the workspace template's
#: ``secrets.toml`` (``_workspace_template/secrets.toml`` and the
#: published ``chumicro-workspace`` payload).  Treated as "broker
#: unset" — the pytest-device plugin then skips at collection time
#: with a clear missing-keys message instead of letting the test
#: run against a hostname that won't resolve.
_BROKER_PLACEHOLDER = "replace-with-your-broker-host"


def pytest_configure(config: pytest.Config) -> None:
    """Spin up the host Mosquitto broker; register the runtime-config payload."""
    global _BROKER_PROCESS, _BROKER_WORKDIR

    merged = _merged_runtime_config_with_creds()

    if merged is not None:
        lan_ip = _detect_lan_ip()
        if lan_ip is not None:
            workdir = Path(tempfile.mkdtemp(prefix="chumicro_mqtt_broker_"))
            broker = _start_mosquitto_broker(lan_ip, workdir)
            if broker is not None:
                _BROKER_PROCESS, broker_port = broker
                _BROKER_WORKDIR = workdir
                merged["mqtt.broker.host"] = lan_ip
                merged["mqtt.broker.port"] = broker_port
            else:
                shutil.rmtree(workdir, ignore_errors=True)

        # If the local mosquitto fixture didn't take over, honour the
        # workspace-template placeholder by suppressing the payload —
        # ``required_keys`` then skips the session at collection time.
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


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001 — pytest hook
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
