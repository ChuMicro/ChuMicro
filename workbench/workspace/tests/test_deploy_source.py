"""Tests for the chumicro-deploy integration glue.

Covers :class:`WithRuntimeConfig`, :func:`project_directory_source`,
:func:`find_project_config`, and the end-to-end "Deployer ships the
msgpack alongside app code" path through ``FakeTransport``.

The msgpack written here is the **flat** dotted-key shape produced
by ``compose_runtime_config``'s flatten step — on-device readers see
``"wifi.ssid"`` directly, no nested table walk.
"""

from pathlib import Path

import pytest
from chumicro_deploy import Deployer, Device, FileMapSource
from chumicro_deploy.testing import FakeTransport
from chumicro_workspace import (
    GENERATED_DIRNAME,
    RUNTIME_CONFIG_DEVICE_PATH,
    WithRuntimeConfig,
    find_project_config,
    project_directory_source,
)
from msgpack import unpackb

# ---------------------------------------------------------------------------
# find_project_config
# ---------------------------------------------------------------------------


class TestFindProjectConfig:
    def test_returns_project_config_toml_when_present(self, tmp_path: Path) -> None:
        (tmp_path / "project_config.toml").write_text("[wifi]\nssid = 'x'\n")
        assert find_project_config(tmp_path) == tmp_path / "project_config.toml"

    def test_returns_legacy_config_toml_when_only_legacy_present(
        self, tmp_path: Path,
    ) -> None:
        # User-edited workspaces from before the rename still work —
        # the legacy ``config.toml`` is found if no canonical sibling
        # exists.
        (tmp_path / "config.toml").write_text("[wifi]\nssid = 'x'\n")
        assert find_project_config(tmp_path) == tmp_path / "config.toml"

    def test_returns_yml_when_only_yaml_present(self, tmp_path: Path) -> None:
        (tmp_path / "config.yml").write_text("wifi:\n  ssid: x\n")
        assert find_project_config(tmp_path) == tmp_path / "config.yml"

    def test_returns_yaml_when_only_yaml_extension(self, tmp_path: Path) -> None:
        (tmp_path / "config.yaml").write_text("wifi:\n  ssid: x\n")
        assert find_project_config(tmp_path) == tmp_path / "config.yaml"

    def test_project_config_toml_wins_over_legacy_config_toml(
        self, tmp_path: Path,
    ) -> None:
        # Both the canonical and the legacy filenames present — the
        # canonical name wins so a partly-migrated workspace doesn't
        # silently load the older file.
        (tmp_path / "project_config.toml").write_text("[wifi]\nssid = 'new'\n")
        (tmp_path / "config.toml").write_text("[wifi]\nssid = 'old'\n")
        assert find_project_config(tmp_path) == tmp_path / "project_config.toml"

    def test_legacy_toml_wins_over_yml(self, tmp_path: Path) -> None:
        (tmp_path / "config.toml").write_text("[wifi]\nssid = 'toml'\n")
        (tmp_path / "config.yml").write_text("wifi:\n  ssid: yml\n")
        assert find_project_config(tmp_path) == tmp_path / "config.toml"

    def test_yml_wins_over_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "config.yml").write_text("wifi:\n  ssid: y\n")
        (tmp_path / "config.yaml").write_text("wifi:\n  ssid: y\n")
        assert find_project_config(tmp_path) == tmp_path / "config.yml"

    def test_raises_when_no_config_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            find_project_config(tmp_path)


# ---------------------------------------------------------------------------
# WithRuntimeConfig
# ---------------------------------------------------------------------------


def _seed_paths(tmp_path: Path) -> tuple[Path, Path]:
    """Lay out secrets.toml + projects/back-porch/project_config.toml."""
    secrets_toml = tmp_path / "secrets.toml"
    secrets_toml.write_text(
        "[wifi]\n"
        'hostname_prefix = "chu-"\n'
        'password = "shh"\n'
    )
    project_dir = tmp_path / "projects" / "back-porch"
    project_dir.mkdir(parents=True)
    project_config = project_dir / "project_config.toml"
    project_config.write_text(
        "[wifi]\n"
        'ssid = "HomeNet"\n'
    )
    return secrets_toml, project_config


class TestWithRuntimeConfig:
    def test_injects_msgpack_at_canonical_device_path(self, tmp_path: Path) -> None:
        secrets_toml, project_config = _seed_paths(tmp_path)
        inner = FileMapSource({"/code.py": "print('hi')\n"}, entrypoint="/code.py")

        decorated = WithRuntimeConfig(
            inner,
            secrets_toml=secrets_toml,
            project_config=project_config,
        )
        files = decorated.files()

        assert RUNTIME_CONFIG_DEVICE_PATH in files
        assert files["/code.py"] == b"print('hi')\n"
        decoded = unpackb(files[RUNTIME_CONFIG_DEVICE_PATH])
        assert decoded == {
            "wifi.hostname_prefix": "chu-",
            "wifi.ssid": "HomeNet",
            "wifi.password": "shh",
        }

    def test_forwards_inner_entrypoint(self, tmp_path: Path) -> None:
        secrets_toml, project_config = _seed_paths(tmp_path)
        inner = FileMapSource({"/main.py": ""}, entrypoint="/main.py")
        decorated = WithRuntimeConfig(
            inner,
            secrets_toml=secrets_toml,
            project_config=project_config,
        )
        assert decorated.entrypoint() == "/main.py"

    def test_default_output_path_lands_in_generated_dir(self, tmp_path: Path) -> None:
        """Convention from ADR 0035 §5: generated artifact under _generated/."""
        secrets_toml, project_config = _seed_paths(tmp_path)
        inner = FileMapSource({"/code.py": ""}, entrypoint="/code.py")
        decorated = WithRuntimeConfig(
            inner,
            secrets_toml=secrets_toml,
            project_config=project_config,
        )
        decorated.files()  # triggers the write
        expected = project_config.parent / GENERATED_DIRNAME / "runtime_config.msgpack"
        assert expected.exists()

    def test_explicit_output_path_used(self, tmp_path: Path) -> None:
        secrets_toml, project_config = _seed_paths(tmp_path)
        custom = tmp_path / "elsewhere" / "out.msgpack"
        inner = FileMapSource({"/code.py": ""}, entrypoint="/code.py")
        decorated = WithRuntimeConfig(
            inner,
            secrets_toml=secrets_toml,
            project_config=project_config,
            output_path=custom,
        )
        decorated.files()
        assert custom.exists()

    def test_explicit_device_path_used(self, tmp_path: Path) -> None:
        secrets_toml, project_config = _seed_paths(tmp_path)
        inner = FileMapSource({"/code.py": ""}, entrypoint="/code.py")
        decorated = WithRuntimeConfig(
            inner,
            secrets_toml=secrets_toml,
            project_config=project_config,
            device_path="/lib/_chu_config.msgpack",
        )
        files = decorated.files()
        assert "/lib/_chu_config.msgpack" in files
        assert RUNTIME_CONFIG_DEVICE_PATH not in files

    def test_collision_with_inner_path_raises(self, tmp_path: Path) -> None:
        secrets_toml, project_config = _seed_paths(tmp_path)
        inner = FileMapSource(
            {
                "/code.py": "",
                RUNTIME_CONFIG_DEVICE_PATH: b"\x80",
            },
            entrypoint="/code.py",
        )
        with pytest.raises(ValueError, match="already provides"):
            WithRuntimeConfig(
                inner,
                secrets_toml=secrets_toml,
                project_config=project_config,
            )

    def test_skips_validation_when_no_library_roots(
        self, tmp_path: Path,
    ) -> None:
        # Default ``library_roots=None`` keeps the pre-Phase-2
        # behaviour: no manifest reads, no validation.  Existing
        # callers that don't yet plumb the import-graph library
        # list through stay unaffected.
        secrets_toml, project_config = _seed_paths(tmp_path)
        inner = FileMapSource({"/code.py": ""}, entrypoint="/code.py")
        decorated = WithRuntimeConfig(
            inner,
            secrets_toml=secrets_toml,
            project_config=project_config,
        )
        # Would fail validation if it ran (no chumicro-wifi
        # manifest reachable, but project config has wifi).
        decorated.files()  # no exception

    def test_validates_when_library_roots_supplied_with_manifest(
        self, tmp_path: Path,
    ) -> None:
        # Plumb a library root with a manifest — validation reads
        # the manifest, unions with itself, and checks the merged
        # flat config against the union.  Wifi config is complete,
        # so validation passes.
        secrets_toml, project_config = _seed_paths(tmp_path)
        wifi_lib = tmp_path / "libraries" / "wifi"
        wifi_lib.mkdir(parents=True)
        (wifi_lib / "pyproject.toml").write_text(
            '[project]\nname = "chumicro-wifi"\n'
            "[tool.chumicro.config]\n"
            'required_keys = ["wifi.ssid", "wifi.password"]\n'
        )
        inner = FileMapSource({"/code.py": ""}, entrypoint="/code.py")
        decorated = WithRuntimeConfig(
            inner,
            secrets_toml=secrets_toml,
            project_config=project_config,
            library_roots=(wifi_lib,),
        )
        decorated.files()  # no exception — config has ssid + password

    def test_raises_when_library_roots_manifest_finds_missing_required(
        self, tmp_path: Path,
    ) -> None:
        # Project config drops ``password`` and there's no overlay —
        # validation must fire at deploy time, before the msgpack
        # lands on the device.
        from chumicro_workspace import ConfigManifestError  # noqa: PLC0415

        secrets_toml = tmp_path / "secrets.toml"
        secrets_toml.write_text("")
        project_dir = tmp_path / "projects" / "back-porch"
        project_dir.mkdir(parents=True)
        project_config = project_dir / "project_config.toml"
        project_config.write_text("[wifi]\nssid = 'HomeNet'\n")

        wifi_lib = tmp_path / "libraries" / "wifi"
        wifi_lib.mkdir(parents=True)
        (wifi_lib / "pyproject.toml").write_text(
            '[project]\nname = "chumicro-wifi"\n'
            "[tool.chumicro.config]\n"
            'required_keys = ["wifi.ssid", "wifi.password"]\n'
        )

        inner = FileMapSource({"/code.py": ""}, entrypoint="/code.py")
        decorated = WithRuntimeConfig(
            inner,
            secrets_toml=secrets_toml,
            project_config=project_config,
            library_roots=(wifi_lib,),
        )
        with pytest.raises(ConfigManifestError, match="wifi.password"):
            decorated.files()

    def test_files_regenerates_msgpack_each_call(self, tmp_path: Path) -> None:
        """Edits to project config show up on the next deploy without manual rebuild."""
        secrets_toml, project_config = _seed_paths(tmp_path)
        inner = FileMapSource({"/code.py": ""}, entrypoint="/code.py")
        decorated = WithRuntimeConfig(
            inner,
            secrets_toml=secrets_toml,
            project_config=project_config,
        )

        first = unpackb(decorated.files()[RUNTIME_CONFIG_DEVICE_PATH])
        project_config.write_text(
            "[wifi]\n"
            'ssid = "OtherNet"\n'
        )
        second = unpackb(decorated.files()[RUNTIME_CONFIG_DEVICE_PATH])

        assert first["wifi.ssid"] == "HomeNet"
        assert second["wifi.ssid"] == "OtherNet"


# ---------------------------------------------------------------------------
# project_directory_source
# ---------------------------------------------------------------------------


def _seed_project_dir(tmp_path: Path) -> tuple[Path, Path]:
    """Lay out a typical projects/<name>/ directory + secrets.toml."""
    secrets_toml = tmp_path / "secrets.toml"
    secrets_toml.write_text(
        "[wifi]\n"
        'hostname_prefix = "chu-"\n'
        'password = "shh"\n',
    )

    project_dir = tmp_path / "projects" / "back-porch"
    project_dir.mkdir(parents=True)
    (project_dir / "project_config.toml").write_text(
        "[wifi]\nssid = 'HomeNet'\n"
    )
    (project_dir / "code.py").write_text("print('hello')\n")
    (project_dir / "helpers.py").write_text("def add(left, right):\n    return left + right\n")
    return project_dir, secrets_toml


class TestProjectDirectorySource:
    def test_ships_app_code_plus_msgpack(self, tmp_path: Path) -> None:
        project_dir, secrets_toml = _seed_project_dir(tmp_path)
        source = project_directory_source(
            project_dir,
            secrets_toml=secrets_toml,
        )
        files = source.files()

        assert files["/code.py"] == b"print('hello')\n"
        assert files["/helpers.py"].startswith(b"def add(")
        assert RUNTIME_CONFIG_DEVICE_PATH in files

    def test_skips_host_only_config_file(self, tmp_path: Path) -> None:
        project_dir, secrets_toml = _seed_project_dir(tmp_path)
        source = project_directory_source(
            project_dir,
            secrets_toml=secrets_toml,
        )
        files = source.files()
        assert "/project_config.toml" not in files
        assert "/config.toml" not in files

    def test_skips_generated_dir(self, tmp_path: Path) -> None:
        project_dir, secrets_toml = _seed_project_dir(tmp_path)
        # Pre-create a stale generated artifact — must not ship.
        generated = project_dir / GENERATED_DIRNAME
        generated.mkdir()
        (generated / "stale.msgpack").write_bytes(b"\x80")

        source = project_directory_source(
            project_dir,
            secrets_toml=secrets_toml,
        )
        files = source.files()
        assert f"/{GENERATED_DIRNAME}/stale.msgpack" not in files

    def test_default_entrypoint_is_circuitpython_code_py(self, tmp_path: Path) -> None:
        project_dir, secrets_toml = _seed_project_dir(tmp_path)
        source = project_directory_source(
            project_dir,
            secrets_toml=secrets_toml,
        )
        assert source.entrypoint() == "/code.py"

    def test_micropython_entrypoint_override(self, tmp_path: Path) -> None:
        project_dir, secrets_toml = _seed_project_dir(tmp_path)
        (project_dir / "main.py").write_text("print('mp')\n")
        source = project_directory_source(
            project_dir,
            secrets_toml=secrets_toml,
            entrypoint="/main.py",
        )
        assert source.entrypoint() == "/main.py"
        assert "/main.py" in source.files()

    def test_extra_excluded_skips_named_dir(self, tmp_path: Path) -> None:
        project_dir, secrets_toml = _seed_project_dir(tmp_path)
        (project_dir / "notes").mkdir()
        (project_dir / "notes" / "draft.md").write_text("draft\n")
        source = project_directory_source(
            project_dir,
            secrets_toml=secrets_toml,
            extra_excluded=("notes",),
        )
        files = source.files()
        assert "/notes/draft.md" not in files

    def test_missing_config_raises_filenotfound(self, tmp_path: Path) -> None:
        empty_project = tmp_path / "projects" / "no-config"
        empty_project.mkdir(parents=True)
        (empty_project / "code.py").write_text("\n")
        with pytest.raises(FileNotFoundError):
            project_directory_source(
                empty_project,
                secrets_toml=tmp_path / "secrets.toml",
            )

    def test_target_runtime_drops_wrong_runtime_files(
        self, tmp_path: Path,
    ) -> None:
        """Decision 0044 — wrong-runtime ``.py`` files are filtered out."""
        project_dir, secrets_toml = _seed_project_dir(tmp_path)
        # Add a CP-only adapter beside the project's app code.
        (project_dir / "_cp_only.py").write_text(
            '__chumicro_runtimes__ = ("circuitpython",)\n',
        )
        (project_dir / "_mp_only.py").write_text(
            '__chumicro_runtimes__ = ("micropython",)\n',
        )

        source = project_directory_source(
            project_dir,
            secrets_toml=secrets_toml,
            target_runtime="micropython",
        )
        files = source.files()
        assert "/_mp_only.py" in files
        assert "/_cp_only.py" not in files
        # Universal app code still ships.
        assert "/code.py" in files


# ---------------------------------------------------------------------------
# End-to-end through Deployer + FakeTransport
# ---------------------------------------------------------------------------


class TestDeployerIntegration:
    """Prove the wrapped source flows through ``Deployer.deploy`` cleanly."""

    def test_deployer_ships_app_code_and_msgpack_via_fake_transport(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_dir, secrets_toml = _seed_project_dir(tmp_path)
        source = project_directory_source(
            project_dir,
            secrets_toml=secrets_toml,
        )

        transport = FakeTransport(execute_output="")
        device = Device(address="fake://device", transport="micropython")
        # ``Device`` is a frozen dataclass — patch the method on the
        # class instead.  ``monkeypatch.setattr`` reverts after the test.
        monkeypatch.setattr(Device, "create_transport", lambda self: transport)

        result = Deployer(device).deploy(source)
        assert result.success is True

        # The deployer recorded a deploy_files call carrying both
        # the app code and the merged runtime-config msgpack.
        deploy_calls = [call for call in transport.calls if call[0] == "deploy_files"]
        assert len(deploy_calls) == 1
        files, entrypoint = deploy_calls[0][1]
        assert entrypoint == "/code.py"
        assert files["/code.py"] == b"print('hello')\n"

        decoded = unpackb(files[RUNTIME_CONFIG_DEVICE_PATH])
        assert decoded["wifi.ssid"] == "HomeNet"
        assert decoded["wifi.password"] == "shh"
        assert decoded["wifi.hostname_prefix"] == "chu-"
