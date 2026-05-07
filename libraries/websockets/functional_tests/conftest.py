"""Host-side fixtures for chumicro-websockets functional tests.

Two responsibilities:

1. Register the merged runtime-config dict (secrets.toml +
   per-library overrides) with pytest-device so it stages at
   ``/runtime_config.msgpack`` on the device — on-device tests read
   wifi creds + the dynamic ``websockets.server`` host/port from there.
2. Spawn a host-side ``websockets`` PyPI echo server on the LAN
   interface so ``test_real_client_against_host.py`` has a battle-
   tested third-party counterparty.

Skips the echo-server fixture (and so the host-counterparty test)
silently when the ``websockets`` PyPI package isn't installed in
the host venv or the LAN IP can't be detected; the loopback test
still runs against the on-device server using the staged
credentials.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from chumicro_pytest_device.runtime_config import set_runtime_config
from chumicro_workspace import compose_runtime_config

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_SECRETS_TOML = _REPO_ROOT / "secrets.toml"
_LIBRARY_CONFIG = _HERE / "config.toml"  # optional; absent → workspace defaults only
_HOST_ECHO_SCRIPT = _HERE / "_host_echo_server.py"


def _merged_runtime_config_with_creds() -> dict | None:
    """Return the deep-merged + flattened runtime-config dict, or ``None``."""
    if not _SECRETS_TOML.is_file():
        return None
    try:
        merged = compose_runtime_config(
            secrets_toml=_SECRETS_TOML,
            project_config=_LIBRARY_CONFIG,
        )
    except Exception:  # noqa: BLE001 — silent skip on any config error
        return None
    ssid = merged.get("wifi.ssid")
    password = merged.get("wifi.password")
    if not isinstance(ssid, str) or not isinstance(password, str):
        return None
    if ssid == "replace-with-your-ap-ssid":
        return None
    return merged


def _detect_lan_ip() -> str | None:
    """Return the host's primary LAN IPv4, or ``None`` if undetectable.

    Mirrors :func:`chumicro_mqtt.functional_tests.conftest._detect_lan_ip`.
    """
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
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((bind_host, 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _wait_until_listening(
    host: str,
    port: int,
    *,
    deadline_seconds: float = 5.0,
) -> bool:
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


def _start_host_echo_server(
    bind_host: str,
) -> tuple[subprocess.Popen[bytes], int] | None:
    """Spawn ``_host_echo_server.py`` bound on *bind_host*.

    Returns ``(process, port)`` or ``None`` if the ``websockets``
    PyPI package isn't installed.
    """
    try:
        import websockets  # noqa: F401 — availability probe
    except ImportError:
        return None

    port = _find_free_port(bind_host)
    process = subprocess.Popen(
        [sys.executable, str(_HOST_ECHO_SCRIPT), bind_host, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not _wait_until_listening(bind_host, port):
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
        return None
    return process, port


_ECHO_PROCESS: subprocess.Popen[bytes] | None = None


def pytest_configure(config: pytest.Config) -> None:
    """Spin up the host echo server; register the runtime-config payload.

    Always emits ``websockets.server.host`` / ``websockets.server.port``
    keys when a payload is registered — values are ``None`` when the
    fixture didn't spawn, so on-device test code can read
    ``config["websockets.server.host"]`` directly without defensive
    ``.get()`` chaining.
    """
    global _ECHO_PROCESS

    merged = _merged_runtime_config_with_creds()

    if merged is not None:
        server_host: str | None = None
        server_port: int | None = None
        lan_ip = _detect_lan_ip()
        if lan_ip is not None:
            spawned = _start_host_echo_server(lan_ip)
            if spawned is not None:
                _ECHO_PROCESS, server_port = spawned
                server_host = lan_ip
        merged["websockets.server.host"] = server_host
        merged["websockets.server.port"] = server_port

    set_runtime_config(
        config,
        merged,
        required_keys=(
            "wifi.ssid",
            "wifi.password",
            "websockets.server.host",
            "websockets.server.port",
        ),
    )


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    """Tear down the host echo server."""
    global _ECHO_PROCESS
    if _ECHO_PROCESS is not None:
        _ECHO_PROCESS.terminate()
        try:
            _ECHO_PROCESS.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _ECHO_PROCESS.kill()
        _ECHO_PROCESS = None
