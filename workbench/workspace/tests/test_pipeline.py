"""End-to-end pipeline tests — read all sources + deep-merge + flatten + write.

The pipeline is two layers (workspace.yml + per-project config), deep-
merged with project-wins precedence, then **flattened** to dotted keys
before the msgpack write so the on-device reader sees the wire shape
it consumes natively.
"""

from pathlib import Path

from chumicro_workspace import (
    build_runtime_config,
    compose_runtime_config,
    write_runtime_config,
)
from msgpack import unpackb


def _seed_workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Lay out a typical workspace under *tmp_path*; return three key paths."""
    workspace_yaml = tmp_path / "workspace.yml"
    workspace_yaml.write_text(
        "defaults:\n"
        "  wifi:\n"
        "    hostname_prefix: chu-\n"
        "    password: actual-password\n"
        "  mqtt:\n"
        "    port: 1883\n"
        "    auth_token: abc123\n"
    )

    project_dir = tmp_path / "projects" / "back-porch"
    project_dir.mkdir(parents=True)
    project_config = project_dir / "project_config.toml"
    project_config.write_text(
        "[wifi]\n"
        'ssid = "HomeNet"\n'
        'hostname = "back-porch"\n'
        "\n"
        "[mqtt]\n"
        'broker = "mqtt.home"\n'
        "\n"
        "[app]\n"
        "sample_period_ms = 30000\n"
    )

    output_path = project_dir / "_generated" / "runtime_config.msgpack"
    return workspace_yaml, project_config, output_path


def test_build_runtime_config_writes_flat_msgpack(tmp_path: Path) -> None:
    """End-to-end: workspace.yml + project config → flat msgpack on disk."""
    workspace_yaml, project_config, output_path = _seed_workspace(tmp_path)

    result = build_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=project_config,
        output_path=output_path,
    )

    expected = {
        "wifi.hostname_prefix": "chu-",       # from workspace.yml
        "wifi.password": "actual-password",   # from workspace.yml
        "wifi.ssid": "HomeNet",               # from project config
        "wifi.hostname": "back-porch",        # from project config
        "mqtt.port": 1883,                    # from workspace.yml
        "mqtt.auth_token": "abc123",          # from workspace.yml
        "mqtt.broker": "mqtt.home",           # from project config
        "app.sample_period_ms": 30000,        # from project config
    }
    assert result == expected

    decoded = unpackb(output_path.read_bytes())
    assert decoded == expected


def test_build_runtime_config_creates_generated_dir(tmp_path: Path) -> None:
    """``_generated/`` is gitignored and may not exist before the first deploy."""
    workspace_yaml, project_config, output_path = _seed_workspace(tmp_path)
    assert not output_path.parent.exists()
    build_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=project_config,
        output_path=output_path,
    )
    assert output_path.exists()
    assert output_path.parent.is_dir()


def test_build_runtime_config_project_overrides_workspace_defaults(
    tmp_path: Path,
) -> None:
    """Per-project config wins over workspace defaults at any nesting depth."""
    workspace_yaml, project_config, output_path = _seed_workspace(tmp_path)
    project_config.write_text(
        "[wifi]\n"
        'ssid = "HomeNet"\n'
        'password = "project-specific"\n'
    )

    result = build_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=project_config,
        output_path=output_path,
    )
    assert result["wifi.password"] == "project-specific"
    assert result["wifi.hostname_prefix"] == "chu-"
    assert result["mqtt.port"] == 1883


def test_compose_runtime_config_returns_flat_dict_without_writing(
    tmp_path: Path,
) -> None:
    """``compose_runtime_config`` returns the flat dict, no msgpack written."""
    workspace_yaml, project_config, output_path = _seed_workspace(tmp_path)

    result = compose_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=project_config,
    )
    assert result["wifi.ssid"] == "HomeNet"
    assert result["wifi.password"] == "actual-password"
    assert "wifi" not in result  # no nested table left over
    assert not output_path.exists()


def test_compose_runtime_config_treats_missing_project_config_as_empty(
    tmp_path: Path,
) -> None:
    """Missing per-library config is fine — workspace defaults pass through."""
    workspace_yaml, _project_config, _output_path = _seed_workspace(tmp_path)

    result_none = compose_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=None,
    )
    assert result_none == {
        "wifi.hostname_prefix": "chu-",
        "wifi.password": "actual-password",
        "mqtt.port": 1883,
        "mqtt.auth_token": "abc123",
    }

    result_missing = compose_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=tmp_path / "does-not-exist" / "project_config.toml",
    )
    assert result_missing == result_none


def test_compose_runtime_config_yaml_project_config(tmp_path: Path) -> None:
    """``config.yml`` works the same as TOML (suffix decides parser)."""
    workspace_yaml = tmp_path / "workspace.yml"
    workspace_yaml.write_text("defaults:\n  wifi:\n    ssid: default\n")

    project_dir = tmp_path / "projects" / "p1"
    project_dir.mkdir(parents=True)
    project_config = project_dir / "config.yml"
    project_config.write_text("wifi:\n  ssid: from-project\n  password: yaml-secret\n")

    result = compose_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=project_config,
    )
    assert result == {"wifi.ssid": "from-project", "wifi.password": "yaml-secret"}


def test_write_runtime_config_round_trips_flat_dict(tmp_path: Path) -> None:
    """The msgpack output decodes back to the same flat dict."""
    output_path = tmp_path / "out" / "runtime_config.msgpack"
    payload = {
        "wifi.ssid": "x",
        "wifi.password": "y",
        "app.list": [1, 2, 3],
        "app.flags.new_ui": True,
    }
    write_runtime_config(payload, output_path)
    assert unpackb(output_path.read_bytes()) == payload
