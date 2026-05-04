"""Host-side fixtures for chumicro-websockets functional tests.

Two responsibilities:

1. Materialise ``_test_creds.py`` from the unified config sources
   (``workspace.yml`` + per-library ``functional_tests/config.toml``
   + ``secrets.yml``) so the on-device test inherits the LAN
   credentials.
2. Spawn a host-side ``websockets`` PyPI echo server on the LAN
   interface so ``test_real_client_against_host.py`` has a battle-
   tested third-party counterparty.

Skips the echo-server fixture (and so the host-counterparty test)
silently when the ``websockets`` PyPI package isn't installed in
the host venv or the LAN IP can't be detected; the credential shim
still gets materialised so the loopback test keeps working.

Phase 4 of the unification workstream
(``plans/workstreams/scripts-workbench-config-unification.md``)
retired the legacy ``chumicro-dev-config.toml`` source — every
networking library's conftest reads from the same
``workspace.yml`` + ``secrets.yml`` pair the workspace-template's
user projects use.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

from chumicro_workspace import compose_runtime_config

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_WORKSPACE_YAML = _REPO_ROOT / "workspace.yml"
_LIBRARY_CONFIG = _HERE / "config.toml"  # optional; absent → workspace defaults only
_SECRETS_YAML = _REPO_ROOT / "secrets.yml"
_SHIM_PATH = _HERE / "_test_creds.py"
_HOST_ECHO_SCRIPT = _HERE / "_host_echo_server.py"


def _read_wifi_section() -> tuple[str, str] | None:
    """Return ``(ssid, password)`` from the unified config, or ``None``.

    Silent-skip on every "creds not configured" path: missing
    workspace.yml, missing wifi section, missing keys, secrets
    resolution failure, placeholder SSID still in place.
    """
    if not _WORKSPACE_YAML.is_file():
        return None
    try:
        merged = compose_runtime_config(
            workspace_yaml=_WORKSPACE_YAML,
            project_config=_LIBRARY_CONFIG,
            secrets_yaml=_SECRETS_YAML,
        )
    except Exception:  # noqa: BLE001 — silent skip on any config error
        return None
    wifi = merged.get("wifi")
    if not isinstance(wifi, dict):
        return None
    ssid = wifi.get("ssid")
    password = wifi.get("password")
    if not isinstance(ssid, str) or not isinstance(password, str):
        return None
    if ssid == "replace-with-your-ap-ssid":
        return None
    return ssid, password


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


def pytest_configure(config) -> None:  # noqa: ARG001 - pytest hook signature
    """Refresh ``_test_creds.py``; spin up the host echo-server fixture."""
    global _ECHO_PROCESS

    creds = _read_wifi_section()
    echo_host: str | None = None
    echo_port: int | None = None

    if creds is not None:
        lan_ip = _detect_lan_ip()
        if lan_ip is not None:
            spawned = _start_host_echo_server(lan_ip)
            if spawned is not None:
                _ECHO_PROCESS, echo_port = spawned
                echo_host = lan_ip

    if creds is None:
        if _SHIM_PATH.exists():
            _SHIM_PATH.unlink()
        return

    ssid, password = creds
    lines = [
        '"""Auto-generated test creds shim — do not check in."""\n',
        f"SSID = {ssid!r}\n",
        f"PASSWORD = {password!r}\n",
    ]
    if echo_host is not None and echo_port is not None:
        lines.extend(
            (
                f"WS_SERVER_HOST = {echo_host!r}\n",
                f"WS_SERVER_PORT = {echo_port!r}\n",
            ),
        )
    else:
        lines.extend(
            (
                "WS_SERVER_HOST = None\n",
                "WS_SERVER_PORT = None\n",
            ),
        )
    _SHIM_PATH.write_text("".join(lines))


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
