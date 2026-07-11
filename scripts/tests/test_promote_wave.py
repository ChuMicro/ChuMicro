"""Tests for promote_wave.py — dependency-ordered promotion dispatch.

Only the pure planning half is tested (tag parsing, dependency mapping,
topological order).  The dispatch/watch half shells out to ``gh`` and is
exercised on launch day, not here.
"""

from __future__ import annotations

from pathlib import Path

import promote_wave
import pytest
import repo_layout
from promote_validate import PromoteValidationError


def _make_package(
    root: Path, parent: str, basename: str, pypi_name: str, deps: list[str],
) -> None:
    """Materialize a minimal publishable package under *root*."""
    package_dir = root / parent / basename
    package_dir.mkdir(parents=True)
    (package_dir / "VERSION").write_text("1.0.0\n")
    dep_lines = "".join(f'    "{dep}",\n' for dep in deps)
    (package_dir / "pyproject.toml").write_text(
        f'[project]\nname = "{pypi_name}"\ndependencies = [\n{dep_lines}]\n'
    )


@pytest.fixture()
def synthetic_publish_set(tmp_path: Path, monkeypatch) -> Path:
    """A workspace where mqtt -> sockets -> (nothing), wifi -> config."""
    _make_package(tmp_path, "libraries", "sockets", "chumicro-sockets", [])
    _make_package(tmp_path, "libraries", "config", "chumicro-config", [])
    _make_package(
        tmp_path, "libraries", "mqtt", "chumicro-mqtt",
        ["chumicro-sockets", "chumicro-config"],
    )
    _make_package(
        tmp_path, "libraries", "wifi", "chumicro-wifi", ["chumicro-config"],
    )
    _make_package(
        tmp_path, "workbench", "pytest-device", "chumicro-pytest-device",
        ["chumicro-deploy>=0.1.0"],
    )
    _make_package(tmp_path, "workbench", "deploy", "chumicro-deploy", [])
    monkeypatch.setattr(repo_layout, "ROOT", tmp_path)
    monkeypatch.setattr(promote_wave, "ROOT", tmp_path)
    return tmp_path


class TestOrderTagsForPromotion:
    """Tests for order_tags_for_promotion."""

    def test_dependencies_come_first(self, synthetic_publish_set):
        """A dependent library's tag sorts after all of its deps' tags."""
        ordered = promote_wave.order_tags_for_promotion([
            "chumicro-mqtt-v1.0.0-experimental",
            "chumicro-config-v1.0.0-experimental",
            "chumicro-sockets-v1.0.0-experimental",
        ])

        assert ordered.index("chumicro-mqtt-v1.0.0-experimental") == 2

    def test_specifier_carrying_deps_are_resolved(self, synthetic_publish_set):
        """A dep with a version specifier still orders its dependent later."""
        ordered = promote_wave.order_tags_for_promotion([
            "chumicro-pytest-device-v1.0.0-experimental",
            "chumicro-deploy-v1.0.0-experimental",
        ])

        assert ordered == [
            "chumicro-deploy-v1.0.0-experimental",
            "chumicro-pytest-device-v1.0.0-experimental",
        ]

    def test_deps_outside_the_wave_are_ignored(self, synthetic_publish_set):
        """Promoting one dependent alone works; absent deps don't block it."""
        ordered = promote_wave.order_tags_for_promotion([
            "chumicro-wifi-v1.0.0-experimental",
        ])

        assert ordered == ["chumicro-wifi-v1.0.0-experimental"]

    def test_malformed_tag_fails(self, synthetic_publish_set):
        """A tag missing the chumicro- prefix fails with the format error."""
        with pytest.raises(PromoteValidationError, match="Expected an experimental tag"):
            promote_wave.order_tags_for_promotion(["wifi-v1.0.0-experimental"])

    def test_unknown_package_fails(self, synthetic_publish_set):
        """A well-formed tag naming a package the workspace lacks fails."""
        with pytest.raises(PromoteValidationError, match="unknown package"):
            promote_wave.order_tags_for_promotion([
                "chumicro-nonexistent-v1.0.0-experimental",
            ])
