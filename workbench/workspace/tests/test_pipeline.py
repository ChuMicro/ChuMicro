"""End-to-end pipeline tests — read all sources + merge + resolve + write."""

from pathlib import Path

import pytest
from chumicro_workspace import (
    UnresolvedSecretError,
    build_runtime_config,
    compose_runtime_config,
    write_runtime_config,
)
from msgpack import unpackb


def _seed_workspace(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Lay out a typical workspace under *tmp_path*; return the four paths."""
    workspace_yaml = tmp_path / "workspace.yml"
    workspace_yaml.write_text(
        "defaults:\n"
        "  wifi:\n"
        "    hostname_prefix: chu-\n"
        "  mqtt:\n"
        "    port: 1883\n"
    )

    project_dir = tmp_path / "projects" / "back-porch"
    project_dir.mkdir(parents=True)
    project_config = project_dir / "config.toml"
    project_config.write_text(
        "[wifi]\n"
        'ssid = "HomeNet"\n'
        'password = "!secret wifi_password"\n'
        'hostname = "back-porch"\n'
        "\n"
        "[mqtt]\n"
        'broker = "mqtt.home"\n'
        'auth_token = "!secret mqtt_token"\n'
        "\n"
        "[app]\n"
        "sample_period_ms = 30000\n"
    )

    secrets_yaml = tmp_path / "secrets.yml"
    secrets_yaml.write_text(
        "wifi_password: actual-password\n"
        "mqtt_token: abc123\n"
    )

    output_path = project_dir / "_generated" / "runtime_config.msgpack"
    return workspace_yaml, project_config, secrets_yaml, output_path


def test_build_runtime_config_writes_msgpack_with_merged_secrets(tmp_path: Path) -> None:
    """End-to-end: workspace + project + secrets → msgpack on disk."""
    workspace_yaml, project_config, secrets_yaml, output_path = _seed_workspace(tmp_path)

    result = build_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=project_config,
        secrets_yaml=secrets_yaml,
        output_path=output_path,
    )

    expected = {
        "wifi": {
            "hostname_prefix": "chu-",       # from workspace
            "ssid": "HomeNet",               # from project
            "password": "actual-password",   # secret resolved
            "hostname": "back-porch",        # from project
        },
        "mqtt": {
            "port": 1883,                    # from workspace
            "broker": "mqtt.home",           # from project
            "auth_token": "abc123",          # secret resolved
        },
        "app": {
            "sample_period_ms": 30000,       # from project
        },
    }
    assert result == expected

    # File-on-disk decodes to the same dict.
    decoded = unpackb(output_path.read_bytes())
    assert decoded == expected


def test_build_runtime_config_creates_generated_dir(tmp_path: Path) -> None:
    """``_generated/`` is gitignored and may not exist before the first deploy."""
    workspace_yaml, project_config, secrets_yaml, output_path = _seed_workspace(tmp_path)
    assert not output_path.parent.exists()
    build_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=project_config,
        secrets_yaml=secrets_yaml,
        output_path=output_path,
    )
    assert output_path.exists()
    assert output_path.parent.is_dir()


def test_build_runtime_config_works_without_secrets_file(tmp_path: Path) -> None:
    """Missing ``secrets.yml`` is fine when no ``!secret`` references exist."""
    workspace_yaml, project_config, secrets_yaml, output_path = _seed_workspace(tmp_path)
    secrets_yaml.unlink()
    # Strip secret references too.
    project_config.write_text(
        "[wifi]\n"
        'ssid = "HomeNet"\n'
        'password = "literal"\n'
    )

    result = build_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=project_config,
        secrets_yaml=secrets_yaml,
        output_path=output_path,
    )
    assert result["wifi"]["password"] == "literal"


def test_build_runtime_config_raises_on_unresolved_secret(tmp_path: Path) -> None:
    """A ``!secret <name>`` reference with no matching secret fails fast."""
    workspace_yaml, project_config, secrets_yaml, output_path = _seed_workspace(tmp_path)
    secrets_yaml.write_text("only_this_one: present\n")
    with pytest.raises(UnresolvedSecretError):
        build_runtime_config(
            workspace_yaml=workspace_yaml,
            project_config=project_config,
            secrets_yaml=secrets_yaml,
            output_path=output_path,
        )


def test_compose_runtime_config_returns_dict_without_writing(
    tmp_path: Path,
) -> None:
    """``compose_runtime_config`` is the dict-only sibling of build_runtime_config.

    Functional-test conftests (Phase 4 of the unification workstream)
    use this to read merged ``[wifi]`` / ``[mqtt]`` from
    workspace.yml + secrets.yml without leaving an unused msgpack
    file on disk.
    """
    workspace_yaml, project_config, secrets_yaml, output_path = _seed_workspace(tmp_path)

    result = compose_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=project_config,
        secrets_yaml=secrets_yaml,
    )
    assert result["wifi"]["ssid"] == "HomeNet"
    assert result["wifi"]["password"] == "actual-password"
    # No msgpack written — output_path was never passed.
    assert not output_path.exists()


def test_compose_runtime_config_treats_missing_project_config_as_empty(
    tmp_path: Path,
) -> None:
    """Missing per-library config.toml is fine — workspace defaults pass through.

    Per-library functional-test config.toml files are optional in
    Phase 4: most libraries inherit everything from workspace.yml.
    The ``project_config`` arg accepts ``None`` or a path that
    doesn't exist; both yield "no project-level overrides".
    """
    workspace_yaml, _project_config, secrets_yaml, _output_path = _seed_workspace(tmp_path)

    # Pass None — should still merge workspace defaults + secrets.
    result_none = compose_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=None,
        secrets_yaml=secrets_yaml,
    )
    assert result_none == {
        "wifi": {"hostname_prefix": "chu-"},
        "mqtt": {"port": 1883},
    }

    # Pass a path that doesn't exist — same result.
    result_missing = compose_runtime_config(
        workspace_yaml=workspace_yaml,
        project_config=tmp_path / "does-not-exist" / "config.toml",
        secrets_yaml=secrets_yaml,
    )
    assert result_missing == result_none


def test_write_runtime_config_round_trips(tmp_path: Path) -> None:
    """The msgpack output decodes back to the same dict."""
    output_path = tmp_path / "out" / "runtime_config.msgpack"
    payload = {
        "wifi": {"ssid": "x", "password": "y"},
        "app": {"flags": {"new_ui": True}, "list": [1, 2, 3]},
    }
    write_runtime_config(payload, output_path)
    assert unpackb(output_path.read_bytes()) == payload
