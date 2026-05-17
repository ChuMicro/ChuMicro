"""Tests for chumicro_workspace.dep_resolver."""

from __future__ import annotations

from pathlib import Path

from chumicro_workspace.dep_resolver import (
    chumicro_dependencies,
    transitive_closure,
)


def _pyproject(tmp_path: Path, deps: list[str]) -> Path:
    rendered = ",\n    ".join(f'"{dep}"' for dep in deps)
    target = tmp_path / "pyproject.toml"
    target.write_text(
        '[project]\nname = "chumicro-demo"\ndependencies = [\n    '
        f"{rendered}\n]\n",
    )
    return target


class TestChumicroDependencies:
    def test_filters_to_chumicro_and_normalizes(self, tmp_path: Path):
        path = _pyproject(
            tmp_path,
            ["chumicro-sockets", "chumicro-http-server", "ruamel.yaml"],
        )
        assert chumicro_dependencies(path) == [
            "chumicro_http_server",
            "chumicro_sockets",
        ]

    def test_strips_version_specifiers_and_extras_and_markers(
        self, tmp_path: Path,
    ):
        path = _pyproject(
            tmp_path,
            [
                "chumicro-timing>=0.3.1",
                "chumicro-config[extra]",
                "chumicro-msgpack ; python_version >= '3.11'",
            ],
        )
        assert chumicro_dependencies(path) == [
            "chumicro_config",
            "chumicro_msgpack",
            "chumicro_timing",
        ]

    def test_dedupes(self, tmp_path: Path):
        path = _pyproject(
            tmp_path, ["chumicro-sockets", "chumicro-sockets>=0.1"],
        )
        assert chumicro_dependencies(path) == ["chumicro_sockets"]

    def test_missing_file_is_empty(self, tmp_path: Path):
        assert chumicro_dependencies(tmp_path / "nope.toml") == []

    def test_no_dependencies_key_is_empty(self, tmp_path: Path):
        target = tmp_path / "pyproject.toml"
        target.write_text('[project]\nname = "chumicro-demo"\n')
        assert chumicro_dependencies(target) == []


class TestTransitiveClosure:
    def test_breadth_first_deterministic_order(self):
        graph = {
            "chumicro_mqtt": ["chumicro_sockets", "chumicro_timing"],
            "chumicro_sockets": ["chumicro_timing"],
            "chumicro_timing": [],
        }
        result = transitive_closure(["chumicro_mqtt"], graph.__getitem__)
        assert result == [
            "chumicro_mqtt",
            "chumicro_sockets",
            "chumicro_timing",
        ]

    def test_each_name_once(self):
        graph = {
            "a": ["b", "c"],
            "b": ["c"],
            "c": ["b"],
        }
        result = transitive_closure(["a"], graph.__getitem__)
        assert sorted(result) == ["a", "b", "c"]
        assert len(result) == 3

    def test_cycle_terminates(self):
        graph = {"a": ["b"], "b": ["a"]}
        assert sorted(transitive_closure(["a"], graph.__getitem__)) == [
            "a",
            "b",
        ]

    def test_multiple_roots_preserve_order(self):
        graph = {"x": [], "y": ["x"], "z": []}
        assert transitive_closure(["z", "y"], graph.__getitem__) == [
            "z",
            "y",
            "x",
        ]
