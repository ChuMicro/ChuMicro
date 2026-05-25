"""Tests for chumicro_workspace.deploy_api.

The deploy_api wraps device-resolution + staging + bg-thread bootstrap +
marker queue.  Tests use FakeTransport + a monkeypatched
``build_transport_for_entry`` so no real serial port is required.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_deploy import DeviceEntry
from chumicro_deploy.testing import FakeTransport
from chumicro_workspace import deploy_api
from chumicro_workspace.markers import MarkerTimeoutError


def _make_workspace(tmp_path: Path, *, with_secrets: bool = True) -> Path:
    """Materialize a minimal workspace tree under *tmp_path*.

    Lays out: secrets.toml (optional), devices.yml, libraries/, and
    support/test_harness/src — enough for deploy_api to resolve and
    stage without erroring.
    """
    (tmp_path / "libraries").mkdir()
    harness_dir = tmp_path / "support" / "test_harness" / "src"
    harness_dir.mkdir(parents=True)
    (tmp_path / "devices.yml").write_text(
        "defaults:\n  deploy_mode: flash\ndevices: []\n",
    )
    if with_secrets:
        (tmp_path / "secrets.toml").write_text(
            '[wifi]\nssid = "test"\npassword = "test"\n',
        )
    return tmp_path


def _make_project(workspace_root: Path, app_body: str = "") -> Path:
    """Materialize a demos-shaped project under *workspace_root*."""
    project_dir = workspace_root / "demos" / "fake_demo"
    project_dir.mkdir(parents=True)
    (project_dir / "app.py").write_text(app_body or "# fake demo\n")
    return project_dir


def _fake_entry(*, deploy_mode: str = "flash", runtime: str = "circuitpython") -> DeviceEntry:
    return DeviceEntry(
        identifier="fake-board-1",
        runtime=runtime,
        address="/dev/null",
        deploy_mode=deploy_mode,
    )


@pytest.fixture
def patched_transport_and_registry(monkeypatch: pytest.MonkeyPatch):
    """Replace device resolution + transport build with FakeTransport.

    Returns a function ``configure(entry, transport=None)`` that arms
    the patches.  ``configure`` returns the FakeTransport instance so
    the test can assert on ``calls``.
    """

    transport_holder: dict = {}
    entry_holder: dict = {}

    def configure(entry: DeviceEntry, transport: FakeTransport | None = None):
        fake = transport or FakeTransport(mode=entry.deploy_mode)
        transport_holder["transport"] = fake
        entry_holder["entry"] = entry

        def fake_load(*, workspace_root=None):  # noqa: ARG001
            from chumicro_deploy.config.default import DeviceDefaults
            return [entry], DeviceDefaults(circuitpython=None, micropython=None)

        def fake_build(device_entry, deploy_mode=None):  # noqa: ARG001
            return fake

        monkeypatch.setattr(deploy_api, "load_device_registry", fake_load)
        monkeypatch.setattr(deploy_api, "build_transport_for_entry", fake_build)
        return fake

    return configure


class TestDeployProjectHappyPath:
    """deploy_project resolves device, stages, and starts the bootstrap."""

    def test_stages_app_file_and_starts_runner(
        self, tmp_path: Path, patched_transport_and_registry,
    ) -> None:
        """app.py is staged and DeviceBootstrapRunner is running."""
        root = _make_workspace(tmp_path)
        project = _make_project(root)
        entry = _fake_entry()
        fake = patched_transport_and_registry(entry)

        session = deploy_api.deploy_project(
            project_dir=project,
            device_id=entry.identifier,
            deploy_mode="flash",
            workspace_root=root,
        )
        try:
            assert session.device_entry is entry
            stage_calls = [call for name, call in fake.calls if name == "stage"]
            assert len(stage_calls) == 1
            (_source_dirs, test_files, _harness, _extra_modules,
             extra_files, _include_test_support) = stage_calls[0]
            assert test_files == [project / "app.py"]
            assert extra_files is not None
            assert "/runtime_config.msgpack" in extra_files
        finally:
            session.shutdown()

    def test_extra_runtime_config_overrides_secrets(
        self, tmp_path: Path, patched_transport_and_registry,
    ) -> None:
        """Caller-supplied extras beat secrets.toml on key collisions."""
        from msgpack import unpackb

        root = _make_workspace(tmp_path)
        (root / "secrets.toml").write_text(
            '[wifi]\nssid = "from-secrets"\npassword = "x"\n'
            '[mqtt.broker]\nhost = "secrets-default-host"\nport = 1\n',
        )
        project = _make_project(root)
        entry = _fake_entry()
        fake = patched_transport_and_registry(entry)

        session = deploy_api.deploy_project(
            project_dir=project,
            device_id=entry.identifier,
            deploy_mode="flash",
            extra_runtime_config={
                "mqtt.broker.host": "override-host",
                "mqtt.broker.port": 8888,
            },
            workspace_root=root,
        )
        try:
            stage_call = [call for name, call in fake.calls if name == "stage"][0]
            extra_files = stage_call[4]
            payload = unpackb(extra_files["/runtime_config.msgpack"])
            assert payload["mqtt.broker.host"] == "override-host"
            assert payload["mqtt.broker.port"] == 8888
            assert payload["wifi.ssid"] == "from-secrets"
        finally:
            session.shutdown()

    def test_deploy_mode_override_beats_device_entry(
        self, tmp_path: Path, patched_transport_and_registry,
    ) -> None:
        """deploy_mode='flash' is passed through to build_transport_for_entry."""
        captured_kwargs: dict = {}
        root = _make_workspace(tmp_path)
        project = _make_project(root)
        entry = _fake_entry(deploy_mode="ram")
        fake = FakeTransport(mode="flash")

        def fake_load(*, workspace_root=None):  # noqa: ARG001
            from chumicro_deploy.config.default import DeviceDefaults
            return [entry], DeviceDefaults(circuitpython=None, micropython=None)

        def fake_build(device_entry, deploy_mode=None):  # noqa: ARG001
            captured_kwargs["deploy_mode"] = deploy_mode
            return fake

        import pytest as _pytest
        monkeypatch = _pytest.MonkeyPatch()
        monkeypatch.setattr(deploy_api, "load_device_registry", fake_load)
        monkeypatch.setattr(deploy_api, "build_transport_for_entry", fake_build)
        try:
            session = deploy_api.deploy_project(
                project_dir=project,
                device_id=entry.identifier,
                deploy_mode="flash",
                workspace_root=root,
            )
            try:
                assert captured_kwargs["deploy_mode"] == "flash"
            finally:
                session.shutdown()
        finally:
            monkeypatch.undo()


class TestDeployProjectErrors:
    """deploy_project fails fast on misconfiguration."""

    def test_missing_app_py_raises(
        self, tmp_path: Path, patched_transport_and_registry,
    ) -> None:
        root = _make_workspace(tmp_path)
        project = root / "demos" / "no_app"
        project.mkdir(parents=True)
        patched_transport_and_registry(_fake_entry())

        with pytest.raises(deploy_api.DeployApiError, match="no app.py"):
            deploy_api.deploy_project(
                project_dir=project, device_id="fake-board-1",
                deploy_mode="flash", workspace_root=root,
            )

    def test_unknown_device_id_raises(
        self, tmp_path: Path, patched_transport_and_registry,
    ) -> None:
        root = _make_workspace(tmp_path)
        project = _make_project(root)
        patched_transport_and_registry(_fake_entry())

        with pytest.raises(deploy_api.DeviceNotFoundError, match="no device"):
            deploy_api.deploy_project(
                project_dir=project, device_id="not-a-real-board",
                deploy_mode="flash", workspace_root=root,
            )

    def test_runtime_filter_mismatch_raises(
        self, tmp_path: Path, patched_transport_and_registry,
    ) -> None:
        root = _make_workspace(tmp_path)
        project = _make_project(root)
        patched_transport_and_registry(
            _fake_entry(runtime="circuitpython"),
        )

        with pytest.raises(deploy_api.DeployApiError, match="Drop one"):
            deploy_api.deploy_project(
                project_dir=project, device_id="fake-board-1",
                runtime="micropython", deploy_mode="flash",
                workspace_root=root,
            )


class TestDeployedProjectMarkerWaits:
    """DeployedProject.wait_for + wait_for_completion happy paths."""

    def test_wait_for_returns_marker_on_arrival(
        self, tmp_path: Path, patched_transport_and_registry,
    ) -> None:
        root = _make_workspace(tmp_path)
        project = _make_project(root)
        entry = _fake_entry()
        # Output the fake board emits during execute(); the runner's
        # on_line callback parses each line and pushes markers.
        fake = FakeTransport(
            mode="flash",
            execute_output="READY answer=42\nDEMO_COMPLETE\n",
        )
        patched_transport_and_registry(entry, transport=fake)

        with deploy_api.deploy_project(
            project_dir=project, device_id=entry.identifier,
            deploy_mode="flash", workspace_root=root,
        ) as session:
            marker = session.wait_for("READY", timeout_s=2.0)
            assert marker.values == {"answer": "42"}
            output = session.wait_for_completion(timeout_s=2.0)
            assert "DEMO_COMPLETE" in output

    def test_wait_for_times_out_on_silent_board(
        self, tmp_path: Path, patched_transport_and_registry,
    ) -> None:
        root = _make_workspace(tmp_path)
        project = _make_project(root)
        entry = _fake_entry()
        fake = FakeTransport(mode="flash", execute_output="not-a-marker\n")
        patched_transport_and_registry(entry, transport=fake)

        with deploy_api.deploy_project(
            project_dir=project, device_id=entry.identifier,
            deploy_mode="flash", workspace_root=root,
        ) as session:
            with pytest.raises(MarkerTimeoutError, match=r"READY"):
                session.wait_for("READY", timeout_s=0.1)


class TestContextManagerTeardown:
    """__exit__ closes the transport even when the body raises."""

    def test_exit_closes_transport_on_exception(
        self, tmp_path: Path, patched_transport_and_registry,
    ) -> None:
        root = _make_workspace(tmp_path)
        project = _make_project(root)
        entry = _fake_entry()
        fake = FakeTransport(mode="flash", execute_output="DEMO_COMPLETE\n")
        patched_transport_and_registry(entry, transport=fake)

        with pytest.raises(RuntimeError, match="user code"):
            with deploy_api.deploy_project(
                project_dir=project, device_id=entry.identifier,
                deploy_mode="flash", workspace_root=root,
            ):
                raise RuntimeError("user code")

        # The transport got a disconnect call as part of shutdown.
        assert any(name == "disconnect" for name, _ in fake.calls)
