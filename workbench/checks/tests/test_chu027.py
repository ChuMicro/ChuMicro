"""Tests for CHU027: cross-site duplicate comment / docstring blocks."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu027 import CHU027

#: A 12-token block, long enough to clear the min-token floor.
_LONG_BLOCK = (
    "# This helper coordinates timing of repeated transitions across\n"
    "# multiple device adapters and emits a single normalized event\n"
    "# when state actually changes from the last observed value.\n"
)

_LONG_DOCSTRING = '''"""This helper coordinates timing of repeated transitions across
multiple device adapters and emits a single normalized event when
state actually changes from the last observed value.
"""
'''


def _stage_lib(repo_root: Path, name: str, src_relative: str, body: str) -> Path:
    target = repo_root / "libraries" / name / "src" / "chumicro_" / src_relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


class TestSilentNoOp:
    def test_no_publishable_trees(self, tmp_path: Path) -> None:
        assert CHU027.check(tmp_path) == []

    def test_unique_blocks_pass(self, tmp_path: Path) -> None:
        _stage_lib(tmp_path, "foo", "x.py", _LONG_BLOCK + "\nvalue = 1\n")
        _stage_lib(tmp_path, "bar", "x.py", "# Different comment entirely.\nvalue = 2\n")
        assert CHU027.check(tmp_path) == []


class TestCrossPackageDuplication:
    def test_two_packages_flagged(self, tmp_path: Path) -> None:
        _stage_lib(tmp_path, "foo", "x.py", _LONG_BLOCK + "\nvalue = 1\n")
        _stage_lib(tmp_path, "bar", "x.py", _LONG_BLOCK + "\nvalue = 2\n")
        findings = CHU027.check(tmp_path)
        assert len(findings) == 2
        assert "duplicate comment / docstring block" in findings[0].message

    def test_docstring_dup_across_packages(self, tmp_path: Path) -> None:
        _stage_lib(tmp_path, "foo", "x.py", _LONG_DOCSTRING + "value = 1\n")
        _stage_lib(tmp_path, "bar", "x.py", _LONG_DOCSTRING + "value = 2\n")
        findings = CHU027.check(tmp_path)
        assert len(findings) == 2


class TestIntraPackageThreshold:
    def test_two_intra_package_not_flagged(self, tmp_path: Path) -> None:
        # Two occurrences in the same package is under the threshold (3).
        _stage_lib(tmp_path, "foo", "a.py", _LONG_BLOCK + "\nvalue = 1\n")
        _stage_lib(tmp_path, "foo", "b.py", _LONG_BLOCK + "\nvalue = 2\n")
        assert CHU027.check(tmp_path) == []

    def test_three_intra_package_flagged(self, tmp_path: Path) -> None:
        for filename in ("a.py", "b.py", "c.py"):
            _stage_lib(tmp_path, "foo", filename, _LONG_BLOCK + "\nvalue = 1\n")
        findings = CHU027.check(tmp_path)
        assert len(findings) == 3


class TestMinTokenFloor:
    def test_short_block_below_floor_not_flagged(self, tmp_path: Path) -> None:
        # 4-token block: below the 12-token floor.
        short = "# Returns the count.\n"
        _stage_lib(tmp_path, "foo", "x.py", short + "value = 1\n")
        _stage_lib(tmp_path, "bar", "x.py", short + "value = 2\n")
        assert CHU027.check(tmp_path) == []


class TestSuppression:
    def test_noqa_on_block_line_suppresses(self, tmp_path: Path) -> None:
        suppressed = "# noqa: CHU027 reason\n" + _LONG_BLOCK + "value = 1\n"
        # First line carries noqa: when blocks are extracted, the line of
        # the block is the line of the first '#'. The noqa line counts.
        _stage_lib(tmp_path, "foo", "x.py", suppressed)
        _stage_lib(tmp_path, "bar", "x.py", _LONG_BLOCK + "value = 2\n")
        # Only the bar finding remains.
        findings = CHU027.check(tmp_path)
        assert len(findings) == 1
        assert "bar" in str(findings[0].path)

    def test_noqa_on_def_line_suppresses_docstring(
        self, tmp_path: Path,
    ) -> None:
        # The noqa on the def line above suppresses the docstring block.
        docstring_body = (
            '    """This helper coordinates timing of repeated transitions across\n'
            '    multiple device adapters and emits a single normalized event when\n'
            '    state actually changes from the last observed value.\n'
            '    """\n'
        )
        body_foo = (
            "def helper():  # noqa: CHU027 see sibling\n"
            + docstring_body
            + "    return None\n"
        )
        body_bar = (
            "def helper():\n"
            + docstring_body
            + "    return None\n"
        )
        _stage_lib(tmp_path, "foo", "x.py", body_foo)
        _stage_lib(tmp_path, "bar", "x.py", body_bar)
        findings = CHU027.check(tmp_path)
        # foo is suppressed, so only bar's finding remains.
        assert len(findings) == 1
        assert "bar" in str(findings[0].path)


class TestPackageBoundaries:
    def test_support_test_harness_treated_as_package(
        self, tmp_path: Path,
    ) -> None:
        harness = tmp_path / "support" / "test_harness"
        harness.mkdir(parents=True)
        (harness / "a.py").write_text(_LONG_BLOCK + "value = 1\n", encoding="utf-8")
        _stage_lib(tmp_path, "foo", "x.py", _LONG_BLOCK + "value = 2\n")
        findings = CHU027.check(tmp_path)
        # Two packages (libraries/foo, support/test_harness) trigger the duplicate.
        assert len(findings) == 2


class TestRuleMetadata:
    def test_code(self) -> None:
        assert CHU027.code == "CHU027"

    def test_description_present(self) -> None:
        assert "duplicate" in CHU027.description.lower()
