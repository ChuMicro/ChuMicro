"""Hardware-gated tests for the example-sensor thing in the canonical
workspace template repo (`ChuMicro-Workspace-Template`).

Phase 7 acceptance: the sensor thing exercises the full ChuMicro
runtime stack (wifi + sockets + mqtt + kvstore + workspace) on a
real board.  This file does as much of that as can be checked from
the chumicro mono-repo's CI / contributor flow without standing up
extra fixtures (test wifi network, test broker, subscriber to
verify message receipt).

Two layers, both ratchet up the strictness:

1. **Import resolution** — runs without hardware.  Proves the
   sensor thing's `app.py` imports cleanly through the published
   chumicro-workspace dep tree on CPython.  Catches API drift that
   per-library tests miss (e.g. a `WifiConfig.from_dict` rename
   would surface here).

2. **Deploy + boot phase markers** — runs on a real board.  Deploys
   the sensor thing and tails REPL for a window, asserts the boot
   reaches phase markers (`sensor: boot #`, `sensor: connecting to
   wifi…`).  Skipped automatically when devices.yml or the template
   repo isn't reachable.

The full "publish round-trip → broker confirms receipt" assertion
isn't in this file yet — it needs a Mosquitto fixture + a paho-mqtt
subscriber on the host + wifi creds reachable from the test environment.
Track in `plans/workstreams/phase-7-integration.md`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# scripts/ is on sys.path via root conftest.py.
from device_config import DeviceEntry  # type: ignore[import-not-found]

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
        if (candidate / "things" / "example-sensor" / "app.py").is_file():
            return candidate
    sibling = Path.home() / "circuitpython" / "ChuMicro-Workspace-Template"
    if (sibling / "things" / "example-sensor" / "app.py").is_file():
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


def test_sensor_thing_imports_resolve_on_cpython(template_repo: Path) -> None:
    """app.py imports successfully through the chumicro-workspace stack on CPython.

    Catches API drift: a renamed `WifiConfig.from_dict`, a missing
    `MQTTClient.state`, a `Runner.add` signature change — all surface
    here before they hit a real board.
    """
    import importlib.util
    import sys as _sys

    app_path = template_repo / "things" / "example-sensor" / "app.py"
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
# Layer 2: deploy + boot phase markers (hardware-gated)
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "Phase 7 follow-on: needs chumicro-repl tail() + a deploy-and-observe "
        "pattern that handles `while True: runner.tick()` (the sensor thing "
        "never returns control, so the existing `Deployer.deploy()` "
        "execute_output assertion model from test_boot_shim_hardware.py "
        "doesn't apply).  Tracked in plans/workstreams/phase-7-integration.md."
    ),
)
def test_sensor_thing_reaches_boot_phase_marker_on_micropython(
    micropython_device: DeviceEntry,
    template_repo: Path,
) -> None:
    """Sensor thing's `print('sensor: boot #N')` appears in REPL within 10 s of deploy.

    Validates that the import-graph deploy ships every chumicro
    library `app.py` imports, that `chumicro-config.load_runtime_config`
    finds the merged msgpack on device, and that
    `chumicro-kvstore.KVStore` initializes — all before any wifi /
    mqtt traffic is attempted.

    Implementation requires:
    - A `chumicro-repl.tail(timeout_seconds=...)` invocation against
      the deployed board, capturing REPL output for the window.
    - Workspace fixtures: a tmp_path workspace with a real
      `secrets.yml` (`wifi_password`) and a `workspace.yml` whose
      `things/example-sensor/config.toml` is overridable via env vars
      so CI can drive its own test wifi network.
    """
