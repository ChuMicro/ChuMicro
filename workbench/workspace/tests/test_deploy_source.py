"""Tests for the chumicro-deploy integration glue.

Covers :class:`WithRuntimeConfig`, :func:`thing_directory_source`,
:func:`find_thing_config`, and the end-to-end "Deployer ships the
msgpack alongside app code" path through ``FakeTransport``.
"""

from pathlib import Path

import pytest
from chumicro_deploy import Deployer, Device, FileMapSource
from chumicro_deploy.testing import FakeTransport
from chumicro_workspace import (
    GENERATED_DIRNAME,
    RUNTIME_CONFIG_DEVICE_PATH,
    WithRuntimeConfig,
    find_thing_config,
    thing_directory_source,
)
from msgpack import unpackb

# ---------------------------------------------------------------------------
# find_thing_config
# ---------------------------------------------------------------------------


class TestFindThingConfig:
    def test_returns_toml_when_present(self, tmp_path: Path) -> None:
        (tmp_path / "config.toml").write_text("[wifi]\nssid = 'x'\n")
        assert find_thing_config(tmp_path) == tmp_path / "config.toml"

    def test_returns_yml_when_only_yaml_present(self, tmp_path: Path) -> None:
        (tmp_path / "config.yml").write_text("wifi:\n  ssid: x\n")
        assert find_thing_config(tmp_path) == tmp_path / "config.yml"

    def test_returns_yaml_when_only_yaml_extension(self, tmp_path: Path) -> None:
        (tmp_path / "config.yaml").write_text("wifi:\n  ssid: x\n")
        assert find_thing_config(tmp_path) == tmp_path / "config.yaml"

    def test_toml_wins_over_yml(self, tmp_path: Path) -> None:
        """Decision 0035 §1: one config per thing, TOML is canonical."""
        (tmp_path / "config.toml").write_text("[wifi]\nssid = 'toml'\n")
        (tmp_path / "config.yml").write_text("wifi:\n  ssid: yml\n")
        assert find_thing_config(tmp_path) == tmp_path / "config.toml"

    def test_yml_wins_over_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "config.yml").write_text("wifi:\n  ssid: y\n")
        (tmp_path / "config.yaml").write_text("wifi:\n  ssid: y\n")
        assert find_thing_config(tmp_path) == tmp_path / "config.yml"

    def test_raises_when_no_config_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            find_thing_config(tmp_path)


# ---------------------------------------------------------------------------
# WithRuntimeConfig
# ---------------------------------------------------------------------------


def _seed_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Lay out workspace.yml, things/back-porch/config.toml, secrets.yml."""
    workspace_yaml = tmp_path / "workspace.yml"
    workspace_yaml.write_text(
        "defaults:\n"
        "  wifi:\n"
        "    hostname_prefix: chu-\n"
    )
    thing_dir = tmp_path / "things" / "back-porch"
    thing_dir.mkdir(parents=True)
    thing_config = thing_dir / "config.toml"
    thing_config.write_text(
        "[wifi]\n"
        'ssid = "HomeNet"\n'
        'password = "!secret wifi_password"\n'
    )
    secrets_yaml = tmp_path / "secrets.yml"
    secrets_yaml.write_text("wifi_password: shh\n")
    return workspace_yaml, thing_config, secrets_yaml


class TestWithRuntimeConfig:
    def test_injects_msgpack_at_canonical_device_path(self, tmp_path: Path) -> None:
        workspace_yaml, thing_config, secrets_yaml = _seed_paths(tmp_path)
        inner = FileMapSource({"/code.py": "print('hi')\n"}, entrypoint="/code.py")

        decorated = WithRuntimeConfig(
            inner,
            workspace_yaml=workspace_yaml,
            thing_config=thing_config,
            secrets_yaml=secrets_yaml,
        )
        files = decorated.files()

        assert RUNTIME_CONFIG_DEVICE_PATH in files
        assert files["/code.py"] == b"print('hi')\n"
        decoded = unpackb(files[RUNTIME_CONFIG_DEVICE_PATH])
        assert decoded == {
            "wifi": {
                "hostname_prefix": "chu-",
                "ssid": "HomeNet",
                "password": "shh",
            },
        }

    def test_forwards_inner_entrypoint(self, tmp_path: Path) -> None:
        workspace_yaml, thing_config, secrets_yaml = _seed_paths(tmp_path)
        inner = FileMapSource({"/main.py": ""}, entrypoint="/main.py")
        decorated = WithRuntimeConfig(
            inner,
            workspace_yaml=workspace_yaml,
            thing_config=thing_config,
            secrets_yaml=secrets_yaml,
        )
        assert decorated.entrypoint() == "/main.py"

    def test_default_output_path_lands_in_generated_dir(self, tmp_path: Path) -> None:
        """Convention from ADR 0035 §5: generated artifact under _generated/."""
        workspace_yaml, thing_config, secrets_yaml = _seed_paths(tmp_path)
        inner = FileMapSource({"/code.py": ""}, entrypoint="/code.py")
        decorated = WithRuntimeConfig(
            inner,
            workspace_yaml=workspace_yaml,
            thing_config=thing_config,
            secrets_yaml=secrets_yaml,
        )
        decorated.files()  # triggers the write
        expected = thing_config.parent / GENERATED_DIRNAME / "runtime_config.msgpack"
        assert expected.exists()

    def test_explicit_output_path_used(self, tmp_path: Path) -> None:
        workspace_yaml, thing_config, secrets_yaml = _seed_paths(tmp_path)
        custom = tmp_path / "elsewhere" / "out.msgpack"
        inner = FileMapSource({"/code.py": ""}, entrypoint="/code.py")
        decorated = WithRuntimeConfig(
            inner,
            workspace_yaml=workspace_yaml,
            thing_config=thing_config,
            secrets_yaml=secrets_yaml,
            output_path=custom,
        )
        decorated.files()
        assert custom.exists()

    def test_explicit_device_path_used(self, tmp_path: Path) -> None:
        workspace_yaml, thing_config, secrets_yaml = _seed_paths(tmp_path)
        inner = FileMapSource({"/code.py": ""}, entrypoint="/code.py")
        decorated = WithRuntimeConfig(
            inner,
            workspace_yaml=workspace_yaml,
            thing_config=thing_config,
            secrets_yaml=secrets_yaml,
            device_path="/lib/_chu_config.msgpack",
        )
        files = decorated.files()
        assert "/lib/_chu_config.msgpack" in files
        assert RUNTIME_CONFIG_DEVICE_PATH not in files

    def test_collision_with_inner_path_raises(self, tmp_path: Path) -> None:
        workspace_yaml, thing_config, secrets_yaml = _seed_paths(tmp_path)
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
                workspace_yaml=workspace_yaml,
                thing_config=thing_config,
                secrets_yaml=secrets_yaml,
            )

    def test_files_regenerates_msgpack_each_call(self, tmp_path: Path) -> None:
        """Edits to thing config show up on the next deploy without manual rebuild."""
        workspace_yaml, thing_config, secrets_yaml = _seed_paths(tmp_path)
        inner = FileMapSource({"/code.py": ""}, entrypoint="/code.py")
        decorated = WithRuntimeConfig(
            inner,
            workspace_yaml=workspace_yaml,
            thing_config=thing_config,
            secrets_yaml=secrets_yaml,
        )

        first = unpackb(decorated.files()[RUNTIME_CONFIG_DEVICE_PATH])
        thing_config.write_text(
            "[wifi]\n"
            'ssid = "OtherNet"\n'
            'password = "!secret wifi_password"\n'
        )
        second = unpackb(decorated.files()[RUNTIME_CONFIG_DEVICE_PATH])

        assert first["wifi"]["ssid"] == "HomeNet"
        assert second["wifi"]["ssid"] == "OtherNet"


# ---------------------------------------------------------------------------
# thing_directory_source
# ---------------------------------------------------------------------------


def _seed_thing_dir(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Lay out a typical things/<name>/ directory + workspace + secrets."""
    workspace_yaml = tmp_path / "workspace.yml"
    workspace_yaml.write_text("defaults:\n  wifi:\n    hostname_prefix: chu-\n")
    secrets_yaml = tmp_path / "secrets.yml"
    secrets_yaml.write_text("wifi_password: shh\n")

    thing_dir = tmp_path / "things" / "back-porch"
    thing_dir.mkdir(parents=True)
    (thing_dir / "config.toml").write_text(
        "[wifi]\nssid = 'HomeNet'\npassword = '!secret wifi_password'\n"
    )
    (thing_dir / "code.py").write_text("print('hello')\n")
    (thing_dir / "helpers.py").write_text("def add(left, right):\n    return left + right\n")
    return thing_dir, workspace_yaml, secrets_yaml


class TestThingDirectorySource:
    def test_ships_app_code_plus_msgpack(self, tmp_path: Path) -> None:
        thing_dir, workspace_yaml, secrets_yaml = _seed_thing_dir(tmp_path)
        source = thing_directory_source(
            thing_dir,
            workspace_yaml=workspace_yaml,
            secrets_yaml=secrets_yaml,
        )
        files = source.files()

        assert files["/code.py"] == b"print('hello')\n"
        assert files["/helpers.py"].startswith(b"def add(")
        assert RUNTIME_CONFIG_DEVICE_PATH in files

    def test_skips_host_only_config_file(self, tmp_path: Path) -> None:
        thing_dir, workspace_yaml, secrets_yaml = _seed_thing_dir(tmp_path)
        source = thing_directory_source(
            thing_dir,
            workspace_yaml=workspace_yaml,
            secrets_yaml=secrets_yaml,
        )
        files = source.files()
        assert "/config.toml" not in files

    def test_skips_generated_dir(self, tmp_path: Path) -> None:
        thing_dir, workspace_yaml, secrets_yaml = _seed_thing_dir(tmp_path)
        # Pre-create a stale generated artifact — must not ship.
        generated = thing_dir / GENERATED_DIRNAME
        generated.mkdir()
        (generated / "stale.msgpack").write_bytes(b"\x80")

        source = thing_directory_source(
            thing_dir,
            workspace_yaml=workspace_yaml,
            secrets_yaml=secrets_yaml,
        )
        files = source.files()
        assert f"/{GENERATED_DIRNAME}/stale.msgpack" not in files

    def test_default_entrypoint_is_circuitpython_code_py(self, tmp_path: Path) -> None:
        thing_dir, workspace_yaml, secrets_yaml = _seed_thing_dir(tmp_path)
        source = thing_directory_source(
            thing_dir,
            workspace_yaml=workspace_yaml,
            secrets_yaml=secrets_yaml,
        )
        assert source.entrypoint() == "/code.py"

    def test_micropython_entrypoint_override(self, tmp_path: Path) -> None:
        thing_dir, workspace_yaml, secrets_yaml = _seed_thing_dir(tmp_path)
        (thing_dir / "main.py").write_text("print('mp')\n")
        source = thing_directory_source(
            thing_dir,
            workspace_yaml=workspace_yaml,
            secrets_yaml=secrets_yaml,
            entrypoint="/main.py",
        )
        assert source.entrypoint() == "/main.py"
        assert "/main.py" in source.files()

    def test_extra_excluded_skips_named_dir(self, tmp_path: Path) -> None:
        thing_dir, workspace_yaml, secrets_yaml = _seed_thing_dir(tmp_path)
        (thing_dir / "notes").mkdir()
        (thing_dir / "notes" / "draft.md").write_text("draft\n")
        source = thing_directory_source(
            thing_dir,
            workspace_yaml=workspace_yaml,
            secrets_yaml=secrets_yaml,
            extra_excluded=("notes",),
        )
        files = source.files()
        assert "/notes/draft.md" not in files

    def test_missing_config_raises_filenotfound(self, tmp_path: Path) -> None:
        empty_thing = tmp_path / "things" / "no-config"
        empty_thing.mkdir(parents=True)
        (empty_thing / "code.py").write_text("\n")
        with pytest.raises(FileNotFoundError):
            thing_directory_source(
                empty_thing,
                workspace_yaml=tmp_path / "workspace.yml",
                secrets_yaml=tmp_path / "secrets.yml",
            )

    def test_target_runtime_drops_wrong_runtime_files(
        self, tmp_path: Path,
    ) -> None:
        """Decision 0044 — wrong-runtime ``.py`` files are filtered out."""
        thing_dir, workspace_yaml, secrets_yaml = _seed_thing_dir(tmp_path)
        # Add a CP-only adapter beside the thing's app code.
        (thing_dir / "_cp_only.py").write_text(
            '__chumicro_runtimes__ = ("circuitpython",)\n',
        )
        (thing_dir / "_mp_only.py").write_text(
            '__chumicro_runtimes__ = ("micropython",)\n',
        )

        source = thing_directory_source(
            thing_dir,
            workspace_yaml=workspace_yaml,
            secrets_yaml=secrets_yaml,
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
        thing_dir, workspace_yaml, secrets_yaml = _seed_thing_dir(tmp_path)
        source = thing_directory_source(
            thing_dir,
            workspace_yaml=workspace_yaml,
            secrets_yaml=secrets_yaml,
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
        assert decoded["wifi"]["ssid"] == "HomeNet"
        assert decoded["wifi"]["password"] == "shh"
        assert decoded["wifi"]["hostname_prefix"] == "chu-"
