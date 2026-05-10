"""Hardware-gated tests for the example_sensor project in the canonical
workspace template repo (`ChuMicro-Workspace-Template`).

The sensor project exercises the full ChuMicro runtime stack
(wifi + sockets + mqtt + kvstore + workspace) on a real board.  This
file does as much of that as can be checked from the contributor CI
flow without standing up extra fixtures (test wifi network, test
broker, subscriber to verify message receipt).

Two layers, both ratchet up the strictness:

1. **Import resolution** — runs without hardware.  Proves the
   sensor project's `app.py` imports cleanly through the published
   chumicro-workspace dep tree on CPython.  Catches API drift that
   per-library tests miss (e.g. a `WifiConfig.from_dict` rename
   would surface here).

2. **Deploy + boot phase markers** — runs on a real board.  Deploys
   the sensor project with a fail-fast wifi config (bogus SSID,
   ``reconnect_max=0``, short connect timeout) so `run()` reaches
   the wifi-bringup loop, the loop fails, and `run()` raises
   `SystemExit` cleanly within seconds.  The execute output is
   asserted to contain the boot-counter print + the wifi-connecting
   marker — proves kvstore + config + import-graph + boot-shim all
   landed correctly without needing a live AP.  Skips when
   devices.yml lacks a matching entry or the template repo isn't
   reachable.

Layer-3 (live broker round-trip — Mosquitto fixture + paho-mqtt
subscriber on the host) is exercised end-to-end by the mqtt
library's `functional_tests/test_real_broker.py` instead.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from chumicro_deploy import Deployer, Device, DeviceEntry
from chumicro_workspace import project_import_graph_source
from chumicro_workspace.workspace import WorkspaceLayout

# ---------------------------------------------------------------------------
# Locate the canonical workspace template clone (or skip)
# ---------------------------------------------------------------------------


def _find_template_repo() -> Path | None:
    """Look for a local clone of `ChuMicro-Workspace-Template`.

    Checks (in order):
    1. `CHUMICRO_WORKSPACE_TEMPLATE_PATH` environment variable.
    2. `~/circuitpython/ChuMicro-Workspace-Template/` — the canonical
       contributor layout (mono-repo at `~/circuitpython/chumicro`,
       template repo as a sibling).
    """
    override = os.environ.get("CHUMICRO_WORKSPACE_TEMPLATE_PATH")
    if override:
        candidate = Path(override).expanduser()
        if (candidate / "projects" / "example_sensor" / "app.py").is_file():
            return candidate
    sibling = Path.home() / "circuitpython" / "ChuMicro-Workspace-Template"
    if (sibling / "projects" / "example_sensor" / "app.py").is_file():
        return sibling
    return None


@pytest.fixture
def template_repo() -> Path:
    repo = _find_template_repo()
    if repo is None:
        pytest.skip(
            "ChuMicro-Workspace-Template clone not found.  "
            "Set CHUMICRO_WORKSPACE_TEMPLATE_PATH or clone it next to chumicro/.",
        )
    return repo


# ---------------------------------------------------------------------------
# Layer 1: import-resolution (no hardware required)
# ---------------------------------------------------------------------------


def test_sensor_project_imports_resolve_on_cpython(template_repo: Path) -> None:
    """app.py imports successfully through the chumicro-workspace stack on CPython.

    Catches API drift: a renamed `WifiConfig.from_dict`, a missing
    `MQTTClient.state`, a `Runner.add` signature change — all surface
    here before they hit a real board.
    """
    import importlib.util
    import sys as _sys

    app_path = template_repo / "projects" / "example_sensor" / "app.py"
    spec = importlib.util.spec_from_file_location(
        "example_sensor_app_under_test", app_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        _sys.modules.pop("example_sensor_app_under_test", None)

    # Public surface the boot module + tests rely on.
    assert callable(module.run)
    assert hasattr(module, "HeartbeatPublisher")
    publisher_class = module.HeartbeatPublisher
    # check / handle is the runner contract — both must exist.
    assert callable(publisher_class.check)
    assert callable(publisher_class.handle)


# ---------------------------------------------------------------------------
# Layer 2: deploy + boot phase markers (hardware-gated, fail-fast wifi)
# ---------------------------------------------------------------------------


_FAIL_FAST_CONFIG_TOML = """\
# Per-project config used by the Layer-2 functional test.  Picks an SSID
# guaranteed not to be in range, caps the connect timeout to a couple
# of seconds, and zeroes the reconnect budget so wifi transitions to
# FAILED on the first miss — `run()` then raises SystemExit and the
# deploy returns within seconds, letting us assert phase markers.
[wifi]
ssid = "chumicro-layer2-test-bogus"
connect_timeout_ms = 2000
reconnect_max = 0

[mqtt]
broker = "localhost"
port = 1883
client_id = "chumicro-layer2-test"

[sensor]
topic = "chumicro/layer2/test"
publish_period_ms = 5000
"""


def _build_device(entry: DeviceEntry) -> Device:
    """Translate a chumicro ``DeviceEntry`` into a public ``Device``."""
    return Device(
        transport=entry.runtime,
        address=entry.address,
        baudrate=entry.serial_baudrate,
        deploy_mode=entry.deploy_mode,
    )


def _chumicro_mono_repo_root() -> Path:
    """The mono-repo root that holds this test file.

    `<root>/workbench/workspace/functional_tests/test_sensor_project_hardware.py`
    so the root is three parents up.
    """
    return Path(__file__).resolve().parents[3]


def _chumicro_library_search_paths() -> list[Path]:
    """Every `<root>/libraries/<name>/src` directory.

    The sensor project imports several chumicro libs; the import-graph
    walker needs each library's `src/` on its search path so the
    transitively-needed source files get shipped to the device.
    """
    libraries_dir = _chumicro_mono_repo_root() / "libraries"
    return sorted(
        path / "src"
        for path in libraries_dir.iterdir()
        if path.is_dir() and (path / "src").is_dir()
    )


def _stage_layer2_workspace(
    tmp_path: Path,
    template_repo: Path,
) -> tuple[WorkspaceLayout, Path]:
    """Build a tmp_path workspace whose `projects/example_sensor/` is the
    canonical sensor project's source with the fail-fast config above.

    Returns (workspace_layout, sensor_project_dir).
    """
    (tmp_path / "workspace.yml").write_text(
        "defaults:\n"
        "  app_marker_prefix: layer2-sensor\n"
        "  wifi:\n"
        "    password: bogus-test-password\n",
    )
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    sensor_dir = projects_dir / "example_sensor"
    sensor_dir.mkdir()
    shutil.copy(
        template_repo / "projects" / "example_sensor" / "app.py",
        sensor_dir / "app.py",
    )
    (sensor_dir / "config.toml").write_text(_FAIL_FAST_CONFIG_TOML)
    # Bootstrap entrypoint for the import-graph deploy: import app, run.
    # The runtime calls main.py / code.py at boot, which calls our run().
    # Boot-shim path (active.py + workspace_runtime.boot()) doesn't compose
    # with project_import_graph_source; this is the simpler shape for tests.
    _entrypoint_source = "from app import run\nrun()\n"
    (sensor_dir / "main.py").write_text(_entrypoint_source)
    (sensor_dir / "code.py").write_text(_entrypoint_source)
    return WorkspaceLayout(root=tmp_path), sensor_dir


def _skip_unless_flash_mode(entry: DeviceEntry) -> None:
    """Layer-2 tests require flash mode.

    The sensor project calls ``chumicro_config.load_runtime_config()`` which
    reads ``/runtime_config.msgpack`` from the device's actual filesystem.
    RAM-mode deploys (``mpremote mount`` / inline-exec on CP) don't
    persist files to the on-device root — they only map the host tmp
    dir under ``/remote`` — so the msgpack ends up unreachable from
    `/runtime_config.msgpack`.  Set ``defaults.deploy_mode: flash`` in
    devices.yml (or per-device override) to enable.
    """
    if entry.deploy_mode != "flash":
        pytest.skip(
            f"Layer-2 sensor project test requires deploy_mode=flash; this "
            f"device is deploy_mode={entry.deploy_mode!r} — set "
            "defaults.deploy_mode: flash in devices.yml to enable.",
        )


def _assert_layer2_phase_markers(execute_output: str) -> None:
    """Common assertions for both runtimes: the boot-shim chain reached
    the wifi-bringup phase before failing, proving every prior phase
    (deploy + import-graph + kvstore + config + boot-shim) worked.
    """
    assert "sensor: boot #" in execute_output, (
        f"kvstore boot-counter print missing; got:\n{execute_output}"
    )
    assert "sensor: connecting to wifi..." in execute_output, (
        f"wifi-bringup phase marker missing; got:\n{execute_output}"
    )


def test_sensor_project_reaches_boot_phase_marker_on_micropython(
    micropython_device: DeviceEntry,
    template_repo: Path,
    tmp_path: Path,
) -> None:
    """MP: sensor project reaches `sensor: connecting to wifi...` and
    SystemExit's cleanly when wifi fails fast.
    """
    _skip_unless_flash_mode(micropython_device)
    workspace, sensor_dir = _stage_layer2_workspace(tmp_path, template_repo)
    device = _build_device(micropython_device)
    source = project_import_graph_source(
        sensor_dir,
        workspace=workspace,
        entrypoint_filename="main.py",
        device_entrypoint="/main.py",
        extra_search_paths=_chumicro_library_search_paths(),
    )
    result = Deployer(device).deploy(source)
    _assert_layer2_phase_markers(result.execute_output)


def test_sensor_project_reaches_boot_phase_marker_on_circuitpython(
    circuitpython_device: DeviceEntry,
    template_repo: Path,
    tmp_path: Path,
) -> None:
    """CP: sensor project reaches `sensor: connecting to wifi...` and
    SystemExit's cleanly when wifi fails fast.
    """
    _skip_unless_flash_mode(circuitpython_device)
    workspace, sensor_dir = _stage_layer2_workspace(tmp_path, template_repo)
    device = _build_device(circuitpython_device)
    source = project_import_graph_source(
        sensor_dir,
        workspace=workspace,
        entrypoint_filename="code.py",
        device_entrypoint="/code.py",
        extra_search_paths=_chumicro_library_search_paths(),
    )
    result = Deployer(device).deploy(source)
    _assert_layer2_phase_markers(result.execute_output)


def test_sensor_project_boot_counter_persists_across_deploys_on_micropython(
    micropython_device: DeviceEntry,
    template_repo: Path,
    tmp_path: Path,
) -> None:
    """MP: boot counter persists across two deploys (kvstore lifecycle).

    Skipped on RAM mode — RAM mode wipes per deploy so the counter
    can't carry over.  Run with ``defaults.deploy_mode: flash`` (or
    a per-device override) in devices.yml to enable.
    """
    _skip_unless_flash_mode(micropython_device)
    workspace, sensor_dir = _stage_layer2_workspace(tmp_path, template_repo)
    device = _build_device(micropython_device)
    source = project_import_graph_source(
        sensor_dir,
        workspace=workspace,
        entrypoint_filename="main.py",
        device_entrypoint="/main.py",
        extra_search_paths=_chumicro_library_search_paths(),
    )
    deployer = Deployer(device)

    first = deployer.deploy(source)
    _assert_layer2_phase_markers(first.execute_output)

    second = deployer.deploy(source)
    _assert_layer2_phase_markers(second.execute_output)
    # Boot counter went up between deploys.  Allow the first to be any
    # number ≥ 1 (in case a contributor's KVStore already had a count
    # from a prior run); the second must be strictly greater.
    import re

    first_count = int(
        re.search(r"sensor: boot #(\d+)", first.execute_output).group(1),
    )
    second_count = int(
        re.search(r"sensor: boot #(\d+)", second.execute_output).group(1),
    )
    assert second_count == first_count + 1, (
        f"boot counter did not advance: first={first_count} second={second_count}"
    )


# ---------------------------------------------------------------------------
# Layer 3: live broker round-trip (heavily gated — needs wifi creds + LAN broker)
# ---------------------------------------------------------------------------


_LAYER3_TOPIC = "chumicro/layer3/temperature"
_LAYER3_REQUIRED_MESSAGES = 2
_LAYER3_DEPLOY_TIMEOUT_SECONDS = 60.0


def _detect_host_lan_ip() -> str:
    """Return the host's LAN IP that devices on the same wifi can reach.

    Connects a UDP socket to a public IP — doesn't actually send; just
    asks the kernel which local interface would be used for that route,
    which on a wifi-attached laptop is the LAN address (192.168.x.y).
    Loopback (127.0.0.1) doesn't work because devices see a different
    network namespace.
    """
    import socket as _socket

    probe = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    finally:
        probe.close()


def _layer3_required_environment() -> dict[str, str]:
    """Return the env vars Layer-3 needs, or skip with a list of missing ones.

    * ``CHUMICRO_TEST_WIFI_SSID`` — the AP the device should join.
    * ``CHUMICRO_TEST_WIFI_PASSWORD`` — its passphrase.
    * ``CHUMICRO_TEST_BROKER_HOST`` (optional) — host the device dials.
      Defaults to the host's auto-detected LAN IP; override when running
      Mosquitto somewhere other than the test host.
    """
    required = (
        "CHUMICRO_TEST_WIFI_SSID",
        "CHUMICRO_TEST_WIFI_PASSWORD",
    )
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        pytest.skip(
            f"Layer-3 needs {', '.join(missing)} in the environment.  "
            "Set them when you have a test wifi network the device can "
            "reach.",
        )
    return {
        "ssid": os.environ["CHUMICRO_TEST_WIFI_SSID"],
        "password": os.environ["CHUMICRO_TEST_WIFI_PASSWORD"],
        "broker_host": os.environ.get(
            "CHUMICRO_TEST_BROKER_HOST", _detect_host_lan_ip(),
        ),
    }


def _spawn_lan_mosquitto(workdir: Path) -> tuple[subprocess.Popen, int]:
    """Spawn a Mosquitto broker bound to all interfaces.

    Returns (process, port).  Caller must terminate the process.
    Skips when ``mosquitto`` isn't on PATH.
    """
    import socket as _socket

    if shutil.which("mosquitto") is None:
        pytest.skip("mosquitto not on PATH (install with `brew install mosquitto`)")

    # Pick a free port on 0.0.0.0.
    bind_probe = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    bind_probe.bind(("0.0.0.0", 0))  # noqa: S104 — broker must accept LAN clients
    port = bind_probe.getsockname()[1]
    bind_probe.close()

    config_path = workdir / "broker.conf"
    config_path.write_text(
        f"listener {port} 0.0.0.0\n"
        "allow_anonymous true\n"
        "persistence false\n"
        f"log_dest file {workdir}/broker.log\n",
    )
    # Mosquitto 2.0 on macOS: setrlimit(RLIMIT_NOFILE) above default soft
    # cap fails with "Out of memory" — drop the cap in the child.
    def _reduce_fd_limit() -> None:  # pragma: no cover — runs in spawned child
        import resource  # noqa: PLC0415

        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))

    process = subprocess.Popen(  # noqa: S603 — args fully controlled
        ["mosquitto", "-c", str(config_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=_reduce_fd_limit,  # noqa: PLW1509 — macOS rlimit quirk
    )

    # Wait until the broker accepts connections.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            ready_probe = _socket.create_connection(("127.0.0.1", port), timeout=0.5)
        except OSError:
            time.sleep(0.05)
            continue
        ready_probe.close()
        return process, port
    process.terminate()
    process.wait(timeout=2)
    pytest.skip(f"mosquitto failed to start on port {port}")
    raise AssertionError("unreachable")  # pragma: no cover — pytest.skip exits


def _spawn_subscriber(broker_port: int, topic: str) -> subprocess.Popen:
    """Spawn ``mosquitto_sub`` in line-buffered mode capturing payloads."""
    return subprocess.Popen(  # noqa: S603 — args fully controlled
        [
            "mosquitto_sub",
            "-h", "127.0.0.1",
            "-p", str(broker_port),
            "-t", topic,
            "-q", "1",
            "-V", "mqttv311",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )


def _read_n_lines(
    process: subprocess.Popen,
    count: int,
    *,
    timeout_seconds: float,
) -> list[str]:
    """Read at most *count* stdout lines from *process* within timeout."""
    import selectors

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_seconds
    lines: list[str] = []
    while len(lines) < count and time.monotonic() < deadline:
        remaining = max(0.05, deadline - time.monotonic())
        if not selector.select(timeout=remaining):
            continue
        line = process.stdout.readline()
        if not line:
            break  # subscriber closed
        lines.append(line.rstrip("\r\n"))
    return lines


def _live_broker_config_toml(environment: dict[str, str], port: int) -> str:
    return (
        "[wifi]\n"
        f'ssid = "{environment["ssid"]}"\n'
        "connect_timeout_ms = 15000\n"
        "\n"
        "[mqtt]\n"
        f'broker = "{environment["broker_host"]}"\n'
        f"port = {port}\n"
        'client_id = "chumicro-layer3-sensor"\n'
        "\n"
        "[sensor]\n"
        f'topic = "{_LAYER3_TOPIC}"\n'
        "publish_period_ms = 2000\n"
    )


def test_sensor_project_publishes_to_live_broker(
    micropython_device: DeviceEntry,
    template_repo: Path,
    tmp_path: Path,
) -> None:
    """End-to-end smoke: deploy → wifi up → mqtt connect → N messages
    arrive on the host's mosquitto_sub within the configured window.

    Skips unless flash mode + wifi env vars + mosquitto are all available.
    """
    _skip_unless_flash_mode(micropython_device)
    environment = _layer3_required_environment()

    # Stage workspace BEFORE Mosquitto spawn: real wifi creds in the
    # gitignored workspace.yml, sensor pointing
    # at a placeholder broker that we'll overwrite with the real port
    # after Mosquitto comes up.
    workspace, sensor_dir = _stage_layer2_workspace(tmp_path, template_repo)
    # Overwrite workspace.yml with the real password for layer 3.
    (tmp_path / "workspace.yml").write_text(
        "defaults:\n"
        "  app_marker_prefix: layer2-sensor\n"
        "  wifi:\n"
        f'    password: "{environment["password"]}"\n',
    )

    broker_workdir = tmp_path / "mosquitto"
    broker_workdir.mkdir()
    broker_process, broker_port = _spawn_lan_mosquitto(broker_workdir)
    subscriber_process = _spawn_subscriber(broker_port, _LAYER3_TOPIC)

    try:
        (sensor_dir / "config.toml").write_text(
            _live_broker_config_toml(environment, broker_port),
        )

        # Deploy + boot.  The deploy returns once the entrypoint exits;
        # since this project's run() is `while not _SHUTDOWN_REQUESTED`,
        # it'll keep running until the deploy times out.  We don't need
        # to wait for the deploy to return — we just need it to start.
        # Run the deploy in the foreground for now and accept that the
        # test takes ~the deploy timeout.
        device = _build_device(micropython_device)
        source = project_import_graph_source(
            sensor_dir,
            workspace=workspace,
            entrypoint_filename="main.py",
            device_entrypoint="/main.py",
            extra_search_paths=_chumicro_library_search_paths(),
        )
        # Read messages while the deploy is still pumping.  The deploy
        # blocks until the on-device script terminates (which it won't —
        # the sensor publishes forever).  So we drive deploy + read in
        # parallel via threads.  Simplest split: deploy runs in a
        # background thread, the main thread reads N messages.
        import threading

        deploy_result_box: list[object] = []
        deploy_error_box: list[BaseException] = []

        staged_files: list[str] = []

        def _run_deploy() -> None:
            try:
                deploy_result_box.append(
                    Deployer(device).deploy(
                        source,
                        on_file_staged=lambda path: staged_files.append(path),
                    ),
                )
            except BaseException as deploy_error:  # noqa: BLE001 — stash + re-raise
                deploy_error_box.append(deploy_error)

        deploy_thread = threading.Thread(
            target=_run_deploy,
            name="layer3-deploy",
            daemon=True,
        )
        deploy_thread.start()

        lines = _read_n_lines(
            subscriber_process,
            count=_LAYER3_REQUIRED_MESSAGES,
            timeout_seconds=_LAYER3_DEPLOY_TIMEOUT_SECONDS,
        )

        # Wait briefly for the deploy thread to settle so we can include
        # its output in any assertion failure message.
        deploy_thread.join(timeout=5.0)
        deploy_state = "running" if deploy_thread.is_alive() else "returned"
        deploy_output = ""
        deploy_traceback = ""
        if deploy_result_box:
            deploy_output = getattr(deploy_result_box[0], "execute_output", "") or ""
            deploy_traceback = getattr(deploy_result_box[0], "traceback", "") or ""
        deploy_error = deploy_error_box[0] if deploy_error_box else None

        adapter_files = sorted(
            name for name in staged_files if "_adapter" in name or "_backend" in name
        )
        assert len(lines) >= _LAYER3_REQUIRED_MESSAGES, (
            f"expected ≥{_LAYER3_REQUIRED_MESSAGES} heartbeat messages, "
            f"got {len(lines)}; deploy state: {deploy_state}; "
            f"subscriber lines: {lines}\n"
            f"adapter / backend files staged ({len(adapter_files)}):\n  "
            + "\n  ".join(adapter_files) + "\n"
            f"deploy.execute_output:\n{deploy_output}\n"
            f"deploy.traceback:\n{deploy_traceback}\n"
            f"deploy_error: {deploy_error!r}"
        )
        # Each line is a JSON-ish payload: {"boot": N, "celsius": T, "n": K}
        for line in lines:
            assert "boot" in line and "celsius" in line, (
                f"unexpected payload shape: {line!r}"
            )
    finally:
        subscriber_process.terminate()
        try:
            subscriber_process.wait(timeout=3)
        except subprocess.TimeoutExpired:  # pragma: no cover — defensive
            subscriber_process.kill()
            subscriber_process.wait()
        broker_process.terminate()
        try:
            broker_process.wait(timeout=3)
        except subprocess.TimeoutExpired:  # pragma: no cover — defensive
            broker_process.kill()
            broker_process.wait()
