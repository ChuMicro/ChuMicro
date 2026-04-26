"""End-to-end pipeline tests — read all sources + merge + resolve + write."""

from pathlib import Path

import pytest
from chumicro_msgpack import unpackb
from chumicro_workspace import (
    UnresolvedSecretError,
    build_runtime_config,
    write_runtime_config,
)


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

    thing_dir = tmp_path / "things" / "back-porch"
    thing_dir.mkdir(parents=True)
    thing_config = thing_dir / "config.toml"
    thing_config.write_text(
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

    output_path = thing_dir / "_generated" / "runtime_config.msgpack"
    return workspace_yaml, thing_config, secrets_yaml, output_path


def test_build_runtime_config_writes_msgpack_with_merged_secrets(tmp_path: Path) -> None:
    """End-to-end: workspace + thing + secrets → msgpack on disk."""
    workspace_yaml, thing_config, secrets_yaml, output_path = _seed_workspace(tmp_path)

    result = build_runtime_config(
        workspace_yaml=workspace_yaml,
        thing_config=thing_config,
        secrets_yaml=secrets_yaml,
        output_path=output_path,
    )

    expected = {
        "wifi": {
            "hostname_prefix": "chu-",       # from workspace
            "ssid": "HomeNet",               # from thing
            "password": "actual-password",   # secret resolved
            "hostname": "back-porch",        # from thing
        },
        "mqtt": {
            "port": 1883,                    # from workspace
            "broker": "mqtt.home",           # from thing
            "auth_token": "abc123",          # secret resolved
        },
        "app": {
            "sample_period_ms": 30000,       # from thing
        },
    }
    assert result == expected

    # File-on-disk decodes to the same dict.
    decoded = unpackb(output_path.read_bytes())
    assert decoded == expected


def test_build_runtime_config_creates_generated_dir(tmp_path: Path) -> None:
    """``_generated/`` is gitignored and may not exist before the first deploy."""
    workspace_yaml, thing_config, secrets_yaml, output_path = _seed_workspace(tmp_path)
    assert not output_path.parent.exists()
    build_runtime_config(
        workspace_yaml=workspace_yaml,
        thing_config=thing_config,
        secrets_yaml=secrets_yaml,
        output_path=output_path,
    )
    assert output_path.exists()
    assert output_path.parent.is_dir()


def test_build_runtime_config_works_without_secrets_file(tmp_path: Path) -> None:
    """Missing ``secrets.yml`` is fine when no ``!secret`` references exist."""
    workspace_yaml, thing_config, secrets_yaml, output_path = _seed_workspace(tmp_path)
    secrets_yaml.unlink()
    # Strip secret references too.
    thing_config.write_text(
        "[wifi]\n"
        'ssid = "HomeNet"\n'
        'password = "literal"\n'
    )

    result = build_runtime_config(
        workspace_yaml=workspace_yaml,
        thing_config=thing_config,
        secrets_yaml=secrets_yaml,
        output_path=output_path,
    )
    assert result["wifi"]["password"] == "literal"


def test_build_runtime_config_raises_on_unresolved_secret(tmp_path: Path) -> None:
    """A ``!secret <name>`` reference with no matching secret fails fast."""
    workspace_yaml, thing_config, secrets_yaml, output_path = _seed_workspace(tmp_path)
    secrets_yaml.write_text("only_this_one: present\n")
    with pytest.raises(UnresolvedSecretError):
        build_runtime_config(
            workspace_yaml=workspace_yaml,
            thing_config=thing_config,
            secrets_yaml=secrets_yaml,
            output_path=output_path,
        )


def test_write_runtime_config_round_trips_via_chumicro_msgpack(tmp_path: Path) -> None:
    """The msgpack output decodes back to the same dict via chumicro-msgpack."""
    output_path = tmp_path / "out" / "runtime_config.msgpack"
    payload = {
        "wifi": {"ssid": "x", "password": "y"},
        "app": {"flags": {"new_ui": True}, "list": [1, 2, 3]},
    }
    write_runtime_config(payload, output_path)
    assert unpackb(output_path.read_bytes()) == payload
