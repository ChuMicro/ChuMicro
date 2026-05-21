"""Tests for CHU013: mid-tick ticks_ms refetch."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu013 import CHU013


def _stage(repo_root: Path, relative: str, content: str) -> Path:
    target = repo_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


class TestSilentNoOp:
    def test_empty_repo(self, tmp_path: Path) -> None:
        assert CHU013.check(tmp_path) == []

    def test_no_libraries_dir(self, tmp_path: Path) -> None:
        (tmp_path / "workbench").mkdir()
        (tmp_path / "workbench" / "foo.py").write_text(
            "def handle(self, now_ms):\n    return self._ticks.ticks_ms()\n",
        )
        # Scope is libraries/<pkg>/src/ only.
        assert CHU013.check(tmp_path) == []


class TestFlags:
    def test_handle_method_refetches_via_object(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "libraries/foo/src/chumicro_foo/core.py",
            "class Service:\n"
            "    def handle(self, now_ms):\n"
            "        return self._ticks.ticks_ms()\n",
        )
        findings = CHU013.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU013"
        assert "'handle'" in findings[0].message

    def test_handle_method_refetches_via_legacy_attr(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "libraries/foo/src/chumicro_foo/core.py",
            "class Service:\n"
            "    def handle(self, now_ms):\n"
            "        return self._ticks_ms()\n",
        )
        findings = CHU013.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU013"

    def test_private_helper_with_now_ms_param(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "libraries/foo/src/chumicro_foo/core.py",
            "class Service:\n"
            "    def _check_deadlines(self, now_ms):\n"
            "        return self._ticks.ticks_ms()\n",
        )
        findings = CHU013.check(tmp_path)
        assert len(findings) == 1


class TestSkips:
    def test_method_without_now_ms_param_is_fine(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "libraries/foo/src/chumicro_foo/core.py",
            "class Service:\n"
            "    def connect(self):\n"
            "        return self._ticks.ticks_ms()\n",
        )
        assert CHU013.check(tmp_path) == []

    def test_optional_now_ms_pattern_passes(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "libraries/foo/src/chumicro_foo/core.py",
            "class Service:\n"
            "    def _deadline(self, offset_ms, *, now_ms=None):\n"
            "        if now_ms is None:\n"
            "            now_ms = self._ticks.ticks_ms()\n"
            "        return self._ticks.ticks_add(now_ms, offset_ms)\n",
        )
        assert CHU013.check(tmp_path) == []

    def test_test_file_not_in_scope(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "libraries/foo/tests/test_core.py",
            "class Service:\n"
            "    def handle(self, now_ms):\n"
            "        return self._ticks.ticks_ms()\n",
        )
        assert CHU013.check(tmp_path) == []


class TestSuppression:
    def test_noqa_comment_mutes_finding(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "libraries/foo/src/chumicro_foo/core.py",
            "class Service:\n"
            "    def handle(self, now_ms):\n"
            "        return self._ticks.ticks_ms()  # noqa: CHU013\n",
        )
        assert CHU013.check(tmp_path) == []
