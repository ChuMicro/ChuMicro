"""Tests for the scripts/verify_examples.py shim.

The full implementation lives in
``workbench/workspace/src/chumicro_workspace/example_verify.py`` —
see ``workbench/workspace/tests/test_example_verify.py`` for the
detail-level tests.  This file only verifies the shim delegates with
the mono-repo's ROOT as ``display_root``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import verify_examples


def test_shim_delegates_to_workspace_implementation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shim forwards package_dirs and pins display_root to repo_layout.ROOT."""
    captured: dict[str, object] = {}

    def fake_verify(
        package_dirs: list[Path], *, display_root: Path | None = None,
    ) -> int:
        captured["package_dirs"] = package_dirs
        captured["display_root"] = display_root
        return 0

    monkeypatch.setattr(verify_examples, "_verify_examples", fake_verify)
    monkeypatch.setattr(verify_examples, "ROOT", tmp_path)

    package_dir = tmp_path / "library"
    result = verify_examples.verify_examples([package_dir])

    assert result == 0
    assert captured["package_dirs"] == [package_dir]
    assert captured["display_root"] == tmp_path
