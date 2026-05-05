"""End-to-end pipeline tests — read all sources + deep-merge + write.

Decision 0057 retired the ``!secret`` marker + ``secrets.yml``.  The
pipeline is now four parallel deep-merge layers (lowest → highest
precedence): ``workspace.yml`` → ``workspace.local.yml`` →
``projects/<name>/config.toml`` → ``projects/<name>/config.local.toml``.
Every layer shares the same section-namespaced shape; gitignored
overlays carry credentials and per-developer overrides.
"""

from pathlib import Path

from chumicro_workspace import (
    build_runtime_config,
    compose_runtime_config,
    write_runtime_config,
)
from msgpack import unpackb


def _seed_workspace(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Lay out a typical workspace under *tmp_path*; return four key paths."""
    workspace_yaml = tmp_path / "workspace.yml"
    workspace_yaml.write_text(
        "defaults:\n"
        "  wifi:\n"
        "    hostname_prefix: chu-\n"
        "  mqtt:\n"
        "    port: 1883\n"
    )

    workspace_local_yaml = tmp_path / "workspace.local.yml"
    workspace_local_yaml.write_text(
        "defaults:\n"
        "  wifi:\n"
        "    password: actual-password\n"
        "  mqtt:\n"
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
    return workspace_yaml, workspace_local_yaml, project_config, output_path


def test_build_runtime_config_writes_msgpack_with_overlay(tmp_path: Path) -> None:
    """End-to-end: workspace + workspace.local + project → msgpack on disk."""
    workspace_yaml, workspace_local_yaml, project_config, output_path = (
        _seed_workspace(tmp_path)
    )

    result = build_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=project_config,
        workspace_local_yaml=workspace_local_yaml,
        output_path=output_path,
    )

    expected = {
        "wifi": {
            "hostname_prefix": "chu-",       # from workspace.yml
            "ssid": "HomeNet",               # from project config.toml
            "password": "actual-password",   # from workspace.local.yml overlay
            "hostname": "back-porch",        # from project config.toml
        },
        "mqtt": {
            "port": 1883,                    # from workspace.yml
            "broker": "mqtt.home",           # from project config.toml
            "auth_token": "abc123",          # from workspace.local.yml overlay
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
    workspace_yaml, workspace_local_yaml, project_config, output_path = (
        _seed_workspace(tmp_path)
    )
    assert not output_path.parent.exists()
    build_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=project_config,
        workspace_local_yaml=workspace_local_yaml,
        output_path=output_path,
    )
    assert output_path.exists()
    assert output_path.parent.is_dir()


def test_build_runtime_config_works_without_local_overlay(tmp_path: Path) -> None:
    """Missing ``workspace.local.yml`` collapses to "no overrides"."""
    workspace_yaml, workspace_local_yaml, project_config, output_path = (
        _seed_workspace(tmp_path)
    )
    workspace_local_yaml.unlink()
    # Inline the password into the project config so the resulting dict
    # still has a complete wifi section.
    project_config.write_text(
        "[wifi]\n"
        'ssid = "HomeNet"\n'
        'password = "literal"\n'
    )

    result = build_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=project_config,
        workspace_local_yaml=workspace_local_yaml,
        output_path=output_path,
    )
    assert result["wifi"]["password"] == "literal"


def test_build_runtime_config_default_local_yaml_path(tmp_path: Path) -> None:
    """When ``workspace_local_yaml`` is omitted, the sibling path is auto-discovered."""
    workspace_yaml, _workspace_local_yaml, project_config, output_path = (
        _seed_workspace(tmp_path)
    )
    # Don't pass workspace_local_yaml at all — the sibling
    # workspace.local.yml should be picked up automatically.
    result = build_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=project_config,
        output_path=output_path,
    )
    assert result["wifi"]["password"] == "actual-password"


def test_build_runtime_config_picks_up_project_local_overlay(
    tmp_path: Path,
) -> None:
    """A ``config.local.toml`` sibling deep-merges as the highest-precedence layer."""
    workspace_yaml, workspace_local_yaml, project_config, output_path = (
        _seed_workspace(tmp_path)
    )
    project_local = project_config.with_name("config.local.toml")
    project_local.write_text(
        "[wifi]\n"
        'password = "project-specific-creds"\n'
    )

    result = build_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=project_config,
        workspace_local_yaml=workspace_local_yaml,
        output_path=output_path,
    )
    # config.local.toml wins over workspace.local.yml at the wifi.password
    # key — same shape, last-merge-wins precedence.
    assert result["wifi"]["password"] == "project-specific-creds"
    # Other fields from earlier layers still flow through.
    assert result["wifi"]["ssid"] == "HomeNet"
    assert result["mqtt"]["auth_token"] == "abc123"


def test_compose_runtime_config_returns_dict_without_writing(
    tmp_path: Path,
) -> None:
    """``compose_runtime_config`` is the dict-only sibling of build_runtime_config.

    Functional-test conftests use this to read merged ``[wifi]`` /
    ``[mqtt]`` from the unified config sources without leaving an
    unused msgpack file on disk.
    """
    workspace_yaml, workspace_local_yaml, project_config, output_path = (
        _seed_workspace(tmp_path)
    )

    result = compose_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=project_config,
        workspace_local_yaml=workspace_local_yaml,
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
    libraries inherit everything from workspace.yml + workspace.local.yml.
    The ``project_config`` arg accepts ``None`` or a path that doesn't
    exist; both yield "no project-level overrides".
    """
    workspace_yaml, workspace_local_yaml, _project_config, _output_path = (
        _seed_workspace(tmp_path)
    )

    # Pass None — should still merge workspace defaults + overlay.
    result_none = compose_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=None,
        workspace_local_yaml=workspace_local_yaml,
    )
    assert result_none == {
        "wifi": {"hostname_prefix": "chu-", "password": "actual-password"},
        "mqtt": {"port": 1883, "auth_token": "abc123"},
    }

    # Pass a path that doesn't exist — same result.
    result_missing = compose_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=tmp_path / "does-not-exist" / "config.toml",
        workspace_local_yaml=workspace_local_yaml,
    )
    assert result_missing == result_none


def test_compose_runtime_config_yaml_project_local_overlay(
    tmp_path: Path,
) -> None:
    """``config.local.yml`` works the same as ``config.local.toml``."""
    workspace_yaml = tmp_path / "workspace.yml"
    workspace_yaml.write_text("defaults:\n  wifi:\n    ssid: default\n")

    project_dir = tmp_path / "projects" / "p1"
    project_dir.mkdir(parents=True)
    project_config = project_dir / "config.yml"
    project_config.write_text("wifi:\n  ssid: from-project\n")
    project_local = project_dir / "config.local.yml"
    project_local.write_text("wifi:\n  password: overlay-secret\n")

    result = compose_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=project_config,
    )
    assert result == {"wifi": {"ssid": "from-project", "password": "overlay-secret"}}


def test_write_runtime_config_round_trips(tmp_path: Path) -> None:
    """The msgpack output decodes back to the same dict."""
    output_path = tmp_path / "out" / "runtime_config.msgpack"
    payload = {
        "wifi": {"ssid": "x", "password": "y"},
        "app": {"flags": {"new_ui": True}, "list": [1, 2, 3]},
    }
    write_runtime_config(payload, output_path)
    assert unpackb(output_path.read_bytes()) == payload
