"""Spawn a host-side Mosquitto broker for chumicro-mqtt functional tests.

`start_mosquitto_broker(bind_host, workdir)` returns `(process, port)`
on success or `None` when `mosquitto` is not on PATH. The caller owns
teardown: terminate the process and remove the workdir from its own
pytest_sessionfinish hook.

The broker config is anonymous-auth, no persistence, single LAN-bound
listener. Suitable for an isolated test session; not a production
shape.

Workbench-only (CPython).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from chumicro_pytest_device.fixtures.lan import find_free_port, wait_until_listening


def start_mosquitto_broker(
    bind_host: str,
    workdir: Path,
) -> tuple[subprocess.Popen[bytes], int] | None:
    """Spawn Mosquitto bound on `bind_host` using `workdir` for config + log.

    Returns `(process, port)` after the broker is accepting connections,
    or `None` when `mosquitto` is not on PATH or the broker failed to
    bind within the deadline. The caller is responsible for terminating
    the returned process at session end.
    """
    if shutil.which("mosquitto") is None:
        return None

    port = find_free_port(bind_host)
    config_path = workdir / "broker.conf"
    config_path.write_text(
        f"listener {port} {bind_host}\n"
        "allow_anonymous true\n"
        "persistence false\n"
        f"log_dest file {workdir}/broker.log\n",
    )

    # Mosquitto 2.0 on macOS / Apple Silicon fails with "Error: Out of
    # memory" when it inherits the default soft limit for
    # `RLIMIT_NOFILE`. Drop it in the child via preexec_fn so
    # mosquitto's setrlimit upgrade no-ops.
    def _reduce_fd_limit() -> None:  # pragma: no cover - runs in spawned child
        import resource  # noqa: PLC0415

        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))

    process = subprocess.Popen(
        ["mosquitto", "-c", str(config_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=_reduce_fd_limit,  # noqa: PLW1509 - needed for macOS rlimit quirk
    )
    if not wait_until_listening(bind_host, port):  # pragma: no cover - exercised by mqtt tests
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
        return None
    return process, port  # pragma: no cover - exercised by mqtt tests
