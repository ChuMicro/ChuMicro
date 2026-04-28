"""Host-side fixtures for chumicro-mqtt functional tests.

Two responsibilities:

1. Materialise ``_test_creds.py`` from ``chumicro-dev-config.toml``
   so the on-device test inherits the LAN credentials.
2. Spawn a host-side Mosquitto broker on the LAN interface so
   ``test_real_broker.py`` has a counterparty.  ``test.mosquitto.org``
   is unreachable from the bench-ap network and the public broker
   isn't reliable enough for a CI-shaped functional test anyway.

The broker fixture mirrors the ``test_mosquitto_integration.py``
``mosquitto_broker`` fixture from the host-side test suite — same
macOS ``setrlimit(RLIMIT_NOFILE)`` workaround for Mosquitto 2.0 on
Apple Silicon.

Skips the broker fixture (and so the real-broker test) silently
when ``mosquitto`` is not on ``PATH`` or the LAN IP can't be
detected; the credential shim still gets materialised so other
fixtures keep working.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import tempfile
import time
import tomllib
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_DEV_CONFIG = _REPO_ROOT / "chumicro-dev-config.toml"
_SHIM_PATH = _HERE / "_test_creds.py"


def _read_wifi_section() -> tuple[str, str] | None:
    if not _DEV_CONFIG.exists():
        return None
    try:
        data = tomllib.loads(_DEV_CONFIG.read_text())
        wifi = data["wifi"]
        return wifi["ssid"], wifi["password"]
    except (KeyError, ValueError):
        return None


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


def pytest_configure(config) -> None:  # noqa: ARG001 - pytest hook signature
    """Refresh ``_test_creds.py``; spin up the host Mosquitto broker."""
    global _BROKER_PROCESS, _BROKER_WORKDIR

    creds = _read_wifi_section()
    broker_host: str | None = None
    broker_port: int | None = None

    if creds is not None:
        lan_ip = _detect_lan_ip()
        if lan_ip is not None:
            workdir = Path(tempfile.mkdtemp(prefix="chumicro_mqtt_broker_"))
            broker = _start_mosquitto_broker(lan_ip, workdir)
            if broker is not None:
                _BROKER_PROCESS, broker_port = broker
                _BROKER_WORKDIR = workdir
                broker_host = lan_ip
            else:
                shutil.rmtree(workdir, ignore_errors=True)

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
    if broker_host is not None and broker_port is not None:
        lines.extend(
            (
                f"BROKER_HOST = {broker_host!r}\n",
                f"BROKER_PORT = {broker_port!r}\n",
            ),
        )
    else:
        lines.extend(
            (
                "BROKER_HOST = None\n",
                "BROKER_PORT = None\n",
            ),
        )
    _SHIM_PATH.write_text("".join(lines))


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
