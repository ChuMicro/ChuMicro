"""End-to-end pipeline tests — read all sources + deep-merge + write.

Per Decision 0057, the pipeline is two gitignored layers:
``workspace.yml`` (defaults + credentials in one place) and
``projects/<name>/config.{toml,yml,yaml}`` (per-project).  Both
share the section-namespaced shape and deep-merge with
last-layer-wins precedence at any nesting depth.
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
    project_config = project_dir / "config.toml"
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


def test_build_runtime_config_writes_msgpack(tmp_path: Path) -> None:
    """End-to-end: workspace.yml + project config → msgpack on disk."""
    workspace_yaml, project_config, output_path = _seed_workspace(tmp_path)

    result = build_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=project_config,
        output_path=output_path,
    )

    expected = {
        "wifi": {
            "hostname_prefix": "chu-",       # from workspace.yml
            "password": "actual-password",   # from workspace.yml (gitignored)
            "ssid": "HomeNet",               # from project config.toml
            "hostname": "back-porch",        # from project config.toml
        },
        "mqtt": {
            "port": 1883,                    # from workspace.yml
            "auth_token": "abc123",          # from workspace.yml (gitignored)
            "broker": "mqtt.home",           # from project config.toml
        },
        "app": {
            "sample_period_ms": 30000,       # from project config.toml
        },
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
    # Override the wifi.password (workspace-default) from the project layer.
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
    assert result["wifi"]["password"] == "project-specific"
    # Other workspace defaults still flow through.
    assert result["wifi"]["hostname_prefix"] == "chu-"
    assert result["mqtt"]["port"] == 1883


def test_compose_runtime_config_returns_dict_without_writing(
    tmp_path: Path,
) -> None:
    """``compose_runtime_config`` is the dict-only sibling of build_runtime_config.

    Functional-test conftests use this to read merged ``[wifi]`` /
    ``[mqtt]`` from the unified config sources without leaving an
    unused msgpack file on disk.
    """
    workspace_yaml, project_config, output_path = _seed_workspace(tmp_path)

    result = compose_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=project_config,
    )
    assert result["wifi"]["ssid"] == "HomeNet"
    assert result["wifi"]["password"] == "actual-password"
    # No msgpack written — output_path was never passed.
    assert not output_path.exists()


def test_compose_runtime_config_treats_missing_project_config_as_empty(
    tmp_path: Path,
) -> None:
    """Missing per-library config.toml is fine — workspace defaults pass through.

    Per-library functional-test config.toml files are optional: most
    libraries inherit everything from workspace.yml.  The ``project_config``
    arg accepts ``None`` or a path that doesn't exist; both yield "no
    project-level overrides".
    """
    workspace_yaml, _project_config, _output_path = _seed_workspace(tmp_path)

    # Pass None — workspace defaults pass through unchanged.
    result_none = compose_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=None,
    )
    assert result_none == {
        "wifi": {"hostname_prefix": "chu-", "password": "actual-password"},
        "mqtt": {"port": 1883, "auth_token": "abc123"},
    }

    # Pass a path that doesn't exist — same result.
    result_missing = compose_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=tmp_path / "does-not-exist" / "config.toml",
    )
    assert result_missing == result_none


def test_compose_runtime_config_yaml_project_config(tmp_path: Path) -> None:
    """``config.yml`` works the same as ``config.toml`` (suffix decides parser)."""
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
    assert result == {"wifi": {"ssid": "from-project", "password": "yaml-secret"}}


def test_write_runtime_config_round_trips(tmp_path: Path) -> None:
    """The msgpack output decodes back to the same dict."""
    output_path = tmp_path / "out" / "runtime_config.msgpack"
    payload = {
        "wifi": {"ssid": "x", "password": "y"},
        "app": {"flags": {"new_ui": True}, "list": [1, 2, 3]},
    }
    write_runtime_config(payload, output_path)
    assert unpackb(output_path.read_bytes()) == payload
