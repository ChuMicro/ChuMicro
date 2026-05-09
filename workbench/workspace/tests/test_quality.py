"""Tests for workspace.yml quality knobs."""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_workspace.loaders import WorkspaceConfigError
from chumicro_workspace.quality import (
    LintConfig,
    QualityConfig,
    load_quality_config,
)


def _write_workspace(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "workspace.yml"
    path.write_text(body)
    return path


class TestDefaults:
    """Permissive default — missing block + missing file behave the same."""

    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        config = load_quality_config(tmp_path / "no-such.yml")
        assert config == QualityConfig()
        assert config.lint == LintConfig()
        assert config.coverage_threshold is None

    def test_no_quality_block_returns_defaults(self, tmp_path: Path) -> None:
        path = _write_workspace(tmp_path, "defaults:\n  wifi:\n    ssid: a\n")
        assert load_quality_config(path) == QualityConfig()

    def test_empty_quality_block_returns_defaults(self, tmp_path: Path) -> None:
        path = _write_workspace(tmp_path, "quality:\n")
        assert load_quality_config(path) == QualityConfig()


class TestLint:
    def test_enabled_false(self, tmp_path: Path) -> None:
        path = _write_workspace(
            tmp_path,
            "quality:\n  lint:\n    enabled: false\n",
        )
        config = load_quality_config(path)
        assert config.lint.enabled is False

    def test_select_list(self, tmp_path: Path) -> None:
        path = _write_workspace(
            tmp_path,
            'quality:\n  lint:\n    select: ["E", "F", "I"]\n',
        )
        config = load_quality_config(path)
        assert config.lint.select == ["E", "F", "I"]

    def test_select_default_is_none(self, tmp_path: Path) -> None:
        path = _write_workspace(
            tmp_path,
            "quality:\n  lint:\n    enabled: true\n",
        )
        config = load_quality_config(path)
        assert config.lint.select is None

    def test_enabled_non_bool_raises(self, tmp_path: Path) -> None:
        path = _write_workspace(
            tmp_path,
            'quality:\n  lint:\n    enabled: "yes"\n',
        )
        with pytest.raises(WorkspaceConfigError, match="enabled.*bool"):
            load_quality_config(path)

    def test_select_not_list_of_strings_raises(self, tmp_path: Path) -> None:
        path = _write_workspace(
            tmp_path,
            "quality:\n  lint:\n    select: [1, 2]\n",
        )
        with pytest.raises(WorkspaceConfigError, match="list of strings"):
            load_quality_config(path)


class TestCoverageThreshold:
    def test_int_value_accepted(self, tmp_path: Path) -> None:
        path = _write_workspace(tmp_path, "quality:\n  coverage_threshold: 85\n")
        assert load_quality_config(path).coverage_threshold == 85

    def test_zero_accepted(self, tmp_path: Path) -> None:
        path = _write_workspace(tmp_path, "quality:\n  coverage_threshold: 0\n")
        assert load_quality_config(path).coverage_threshold == 0

    def test_default_is_none(self, tmp_path: Path) -> None:
        path = _write_workspace(
            tmp_path,
            "quality:\n  lint:\n    enabled: true\n",
        )
        assert load_quality_config(path).coverage_threshold is None

    def test_bool_value_rejected(self, tmp_path: Path) -> None:
        """``coverage_threshold: true`` shouldn't silently coerce to 1."""
        path = _write_workspace(
            tmp_path, "quality:\n  coverage_threshold: true\n",
        )
        with pytest.raises(WorkspaceConfigError, match="integer"):
            load_quality_config(path)

    def test_string_value_rejected(self, tmp_path: Path) -> None:
        path = _write_workspace(
            tmp_path, 'quality:\n  coverage_threshold: "85"\n',
        )
        with pytest.raises(WorkspaceConfigError, match="integer"):
            load_quality_config(path)


class TestShapeViolations:
    def test_quality_not_a_mapping_raises(self, tmp_path: Path) -> None:
        path = _write_workspace(tmp_path, "quality: [a, b]\n")
        with pytest.raises(WorkspaceConfigError, match="must be a mapping"):
            load_quality_config(path)

    def test_lint_not_a_mapping_raises(self, tmp_path: Path) -> None:
        path = _write_workspace(tmp_path, "quality:\n  lint: [E, F]\n")
        with pytest.raises(WorkspaceConfigError, match="lint.*mapping"):
            load_quality_config(path)
