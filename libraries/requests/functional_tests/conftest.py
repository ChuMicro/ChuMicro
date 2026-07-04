"""Host-side fixtures for chumicro-requests functional tests.

Two responsibilities:

1. Register the merged runtime-config dict from ``workspace.yml`` +
   this library's optional ``functional_tests/config.toml`` with
   pytest-device, which msgpack-encodes it once and stages it at
   ``/runtime_config.msgpack`` on the device.  On-device tests read it
   back via ``chumicro_config.load_runtime_config()`` (wifi creds, the
   RTC seed, and the dynamic large-body host/port below).
2. Spawn a host-side HTTP server (``_host_large_body_server.py``) on the
   LAN interface serving a deterministic large body, so
   ``test_real_large_stream.py`` has a controlled multi-hundred-KB
   download counterparty for the streamed-body bake.

Bakes the host's current UTC into ``requests.now_utc_tuple`` (a
6-tuple) so the HTTPS test (``test_real_get_tls.py``) can seed the
device RTC before TLS validation — boot RTC lands at 2021-01-01 on
most ports, which makes mbedTLS reject any cert with NotBefore after
that.  Real deployments NTP-sync; this is the bench-test equivalent.

The large-body fixture registers ``requests.large_body.server.host`` /
``.port`` — ``None`` when no LAN IP was detectable to bind it, in which
case the stream test skips in its body (``required_keys`` treats a
present-but-``None`` value as satisfied).  The other requests tests dial
public endpoints and ignore these keys.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from chumicro_pytest_device.runtime_config import set_runtime_config
from chumicro_workspace import compose_runtime_config

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_SECRETS_TOML = _REPO_ROOT / "secrets.toml"
_LIBRARY_CONFIG = _HERE / "config.toml"  # optional; absent → workspace defaults only
_HOST_LARGE_BODY_SCRIPT = _HERE / "_host_large_body_server.py"


def _merged_runtime_config() -> dict | None:
    """Return the deep-merged + flattened runtime-config dict, or ``None``.

    Adds ``requests.now_utc_tuple`` — the bench-test RTC seed used by
    the HTTPS test — into the flat dict so the on-device test reads
    it via ``config["requests.now_utc_tuple"]``.
    """
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
    now = datetime.now(UTC)
    merged["requests.now_utc_tuple"] = (
        now.year, now.month, now.day, now.hour, now.minute, now.second,
    )
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


def _start_host_large_body_server(
    bind_host: str,
) -> tuple[subprocess.Popen[bytes], int] | None:
    """Spawn ``_host_large_body_server.py`` bound on *bind_host*.

    Returns ``(process, port)``, or ``None`` if it never came up.  The
    server is stdlib-only (``http.server``), so unlike the websockets
    echo fixture there's no third-party-package availability gate.
    """
    port = _find_free_port(bind_host)
    process = subprocess.Popen(
        [sys.executable, str(_HOST_LARGE_BODY_SCRIPT), bind_host, str(port)],
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


_SERVER_PROCESS: subprocess.Popen[bytes] | None = None


def pytest_configure(config: pytest.Config) -> None:
    """Spin up the large-body host fixture; register the runtime-config payload.

    Always emits ``requests.large_body.server.host`` / ``.port`` when a
    payload is registered — ``None`` when the fixture didn't spawn, so
    on-device test code can read ``config["requests.large_body.server.host"]``
    directly without defensive ``.get()`` chaining.
    """
    global _SERVER_PROCESS

    merged = _merged_runtime_config()

    if merged is not None:
        server_host: str | None = None
        server_port: int | None = None
        lan_ip = _detect_lan_ip()
        if lan_ip is not None:
            spawned = _start_host_large_body_server(lan_ip)
            if spawned is not None:
                _SERVER_PROCESS, server_port = spawned
                server_host = lan_ip
        merged["requests.large_body.server.host"] = server_host
        merged["requests.large_body.server.port"] = server_port

    set_runtime_config(
        config,
        merged,
        required_keys=(
            "wifi.ssid",
            "wifi.password",
            "requests.large_body.server.host",
            "requests.large_body.server.port",
        ),
    )


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    """Tear down the large-body host fixture."""
    global _SERVER_PROCESS
    if _SERVER_PROCESS is not None:
        _SERVER_PROCESS.terminate()
        try:
            _SERVER_PROCESS.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _SERVER_PROCESS.kill()
        _SERVER_PROCESS = None
