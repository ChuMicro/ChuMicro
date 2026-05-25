"""Tests for CHU030: demo driver surface contract.

Verifies the forbidden-import list, the literal-vs-non-literal
deploy_mode kwarg distinction, the noqa suppression, and the silent
no-op when no ``demos/`` dir exists.
"""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu030 import CHU030


def _stage_demo(repo_root: Path, name: str, driver_source: str) -> Path:
    demo_dir = repo_root / "demos" / name
    demo_dir.mkdir(parents=True, exist_ok=True)
    target = demo_dir / "driver.py"
    target.write_text(driver_source, encoding="utf-8")
    return target


def _stage_app(repo_root: Path, name: str, app_source: str) -> Path:
    demo_dir = repo_root / "demos" / name
    demo_dir.mkdir(parents=True, exist_ok=True)
    target = demo_dir / "app.py"
    target.write_text(app_source, encoding="utf-8")
    return target


_CLEAN_DRIVER = (
    "from chumicro_workspace.deploy_api import deploy_project\n"
    "from chumicro_workspace.markers import MarkerTimeoutError\n"
    "from chumicro_pytest_device.fixtures.mosquitto import start_mosquitto_broker\n"
    "\n"
    "with deploy_project(\n"
    '    project_dir=None, device_id="x", deploy_mode="flash",\n'
    ") as session:\n"
    "    pass\n"
)


class TestSilentNoOp:
    def test_no_demos_dir(self, tmp_path: Path) -> None:
        assert CHU030.check(tmp_path) == []

    def test_clean_driver_passes(self, tmp_path: Path) -> None:
        _stage_demo(tmp_path, "ok_demo", _CLEAN_DRIVER)
        assert CHU030.check(tmp_path) == []


class TestForbiddenImports:
    def test_chumicro_deploy_import_flagged(self, tmp_path: Path) -> None:
        source = (
            "from chumicro_deploy import load_device_registry\n"
            + _CLEAN_DRIVER
        )
        _stage_demo(tmp_path, "bad_demo", source)
        findings = CHU030.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU030"
        assert "chumicro_deploy" in findings[0].message
        assert "chumicro_workspace.deploy_api" in findings[0].message

    def test_pytest_device_test_runner_flagged(self, tmp_path: Path) -> None:
        source = (
            "from chumicro_pytest_device.test_runner import "
            "build_transport_for_entry\n"
            + _CLEAN_DRIVER
        )
        _stage_demo(tmp_path, "bad_demo", source)
        findings = CHU030.check(tmp_path)
        assert len(findings) == 1
        assert "chumicro_pytest_device.test_runner" in findings[0].message

    def test_workspace_pipeline_flagged(self, tmp_path: Path) -> None:
        source = (
            "from chumicro_workspace.pipeline import compose_runtime_config\n"
            + _CLEAN_DRIVER
        )
        _stage_demo(tmp_path, "bad_demo", source)
        findings = CHU030.check(tmp_path)
        assert len(findings) == 1
        assert "chumicro_workspace.pipeline" in findings[0].message

    def test_device_runner_flagged(self, tmp_path: Path) -> None:
        source = (
            "from chumicro_workspace.device_runner import DeviceBootstrapRunner\n"
            + _CLEAN_DRIVER
        )
        _stage_demo(tmp_path, "bad_demo", source)
        findings = CHU030.check(tmp_path)
        assert len(findings) == 1
        assert "chumicro_workspace.device_runner" in findings[0].message

    def test_bare_import_flagged(self, tmp_path: Path) -> None:
        source = "import chumicro_deploy\n" + _CLEAN_DRIVER
        _stage_demo(tmp_path, "bad_demo", source)
        findings = CHU030.check(tmp_path)
        assert len(findings) == 1

    def test_noqa_suppression_silences_finding(self, tmp_path: Path) -> None:
        source = (
            "from chumicro_deploy import load_device_registry  # noqa: CHU030\n"
            + _CLEAN_DRIVER
        )
        _stage_demo(tmp_path, "ok_demo", source)
        assert CHU030.check(tmp_path) == []

    def test_fixtures_imports_allowed(self, tmp_path: Path) -> None:
        source = (
            "from chumicro_pytest_device.fixtures.lan import detect_lan_ip\n"
            "from chumicro_pytest_device.fixtures.mosquitto import "
            "start_mosquitto_broker\n"
            + _CLEAN_DRIVER
        )
        _stage_demo(tmp_path, "ok_demo", source)
        assert CHU030.check(tmp_path) == []


class TestDeployModeEnforcement:
    def test_deploy_mode_flash_literal_ok(self, tmp_path: Path) -> None:
        _stage_demo(tmp_path, "ok_demo", _CLEAN_DRIVER)
        assert CHU030.check(tmp_path) == []

    def test_deploy_mode_ram_literal_flagged(self, tmp_path: Path) -> None:
        source = (
            "from chumicro_workspace.deploy_api import deploy_project\n"
            "deploy_project(project_dir=None, device_id='x', deploy_mode='ram')\n"
        )
        _stage_demo(tmp_path, "bad_demo", source)
        findings = CHU030.check(tmp_path)
        assert len(findings) == 1
        assert "deploy_mode='ram'" in findings[0].message

    def test_missing_deploy_mode_kwarg_flagged(self, tmp_path: Path) -> None:
        source = (
            "from chumicro_workspace.deploy_api import deploy_project\n"
            "deploy_project(project_dir=None, device_id='x')\n"
        )
        _stage_demo(tmp_path, "bad_demo", source)
        findings = CHU030.check(tmp_path)
        assert len(findings) == 1
        assert "must pass deploy_mode=\"flash\"" in findings[0].message

    def test_non_literal_deploy_mode_allowed(self, tmp_path: Path) -> None:
        source = (
            "from chumicro_workspace.deploy_api import deploy_project\n"
            "deploy_project(project_dir=None, device_id='x', deploy_mode=args.mode)\n"
        )
        _stage_demo(tmp_path, "ok_demo", source)
        assert CHU030.check(tmp_path) == []

    def test_attribute_call_form_caught(self, tmp_path: Path) -> None:
        """``deploy_api.deploy_project(...)`` also gets the deploy_mode check."""
        source = (
            "from chumicro_workspace import deploy_api\n"
            "deploy_api.deploy_project(project_dir=None, device_id='x')\n"
        )
        _stage_demo(tmp_path, "bad_demo", source)
        findings = CHU030.check(tmp_path)
        assert len(findings) == 1
        assert "must pass deploy_mode=\"flash\"" in findings[0].message


class TestAppFileAlsoScanned:
    def test_forbidden_import_in_app_py_flagged(self, tmp_path: Path) -> None:
        """The rule scans every .py under demos/, not just driver.py."""
        _stage_app(
            tmp_path, "bad_demo",
            "from chumicro_deploy import load_device_registry\n",
        )
        findings = CHU030.check(tmp_path)
        assert len(findings) == 1
        assert "chumicro_deploy" in findings[0].message
