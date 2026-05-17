"""Tests for chumicro_workspace.managed_block — workspace.yml surgery."""

from __future__ import annotations

from pathlib import Path

from chumicro_workspace.managed_block import sync_managed_block

_MARKER = "managed by test"


def _sync(path: Path, children: list[str], *, key: str = "demo") -> bool:
    return sync_managed_block(path, key, _MARKER, children)


class TestSyncManagedBlock:
    def test_creates_file_when_missing(self, tmp_path: Path):
        target = tmp_path / "workspace.yml"
        changed = _sync(target, ["  a: 1"])
        assert changed is True
        assert target.read_text() == f"# {_MARKER}\ndemo:\n  a: 1\n"

    def test_idempotent_rerun_returns_false(self, tmp_path: Path):
        target = tmp_path / "workspace.yml"
        _sync(target, ["  a: 1"])
        assert _sync(target, ["  a: 1"]) is False

    def test_replaces_block_preserving_surrounding_bytes(self, tmp_path: Path):
        target = tmp_path / "workspace.yml"
        target.write_text(
            "# header comment\n\n"
            f"# {_MARKER}\n"
            "demo:\n  a: 1\n"
            "\n# trailing user key\nother: keep\n",
        )
        _sync(target, ["  a: 2", "  b: 3"])
        text = target.read_text()
        assert "# header comment\n" in text
        assert "# trailing user key\nother: keep\n" in text
        assert "  a: 2\n  b: 3\n" in text
        assert "  a: 1" not in text

    def test_replaces_bare_block_and_adds_marker(self, tmp_path: Path):
        target = tmp_path / "workspace.yml"
        target.write_text("demo:\n  a: 1\n")
        _sync(target, ["  a: 2"])
        text = target.read_text()
        assert text == f"# {_MARKER}\ndemo:\n  a: 2\n"

    def test_appends_with_separator_when_no_block(self, tmp_path: Path):
        target = tmp_path / "workspace.yml"
        target.write_text("# existing\nother: value\n")
        _sync(target, ["  a: 1"])
        text = target.read_text()
        assert text == (
            "# existing\nother: value\n\n"
            f"# {_MARKER}\ndemo:\n  a: 1\n"
        )

    def test_nested_children_block_matched(self, tmp_path: Path):
        target = tmp_path / "workspace.yml"
        _sync(target, ["  parent:", "    child: 1"])
        _sync(target, ["  parent:", "    child: 2"])
        text = target.read_text()
        assert "    child: 2\n" in text
        assert "child: 1" not in text

    def test_key_reference_in_comment_not_caught(self, tmp_path: Path):
        target = tmp_path / "workspace.yml"
        target.write_text("# mentions demo: in prose\nreal: 1\n")
        _sync(target, ["  a: 1"])
        text = target.read_text()
        assert "# mentions demo: in prose\nreal: 1\n" in text
        assert text.endswith(f"# {_MARKER}\ndemo:\n  a: 1\n")

    def test_distinct_keys_coexist(self, tmp_path: Path):
        target = tmp_path / "workspace.yml"
        sync_managed_block(target, "alpha", _MARKER, ["  a: 1"])
        sync_managed_block(target, "beta", _MARKER, ["  b: 2"])
        text = target.read_text()
        assert "alpha:\n  a: 1\n" in text
        assert "beta:\n  b: 2\n" in text
        # Re-syncing alpha leaves beta untouched.
        assert sync_managed_block(target, "beta", _MARKER, ["  b: 2"]) is False
