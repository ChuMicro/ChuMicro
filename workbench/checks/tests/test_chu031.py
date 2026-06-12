"""Tests for CHU031: noqa / pragma explanation separator."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu031 import CHU031


def _stage(repo_root: Path, relative: str, content: str) -> Path:
    """Stage *content* at ``repo_root/relative`` and return the path."""
    target = repo_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


_LIB_SRC = "libraries/foo/src/chumicro_foo/mod.py"


class TestSilentNoOp:
    """Repos without any src scan roots emit no findings."""

    def test_empty_repo(self, tmp_path: Path) -> None:
        assert CHU031.check(tmp_path) == []

    def test_no_src_dir(self, tmp_path: Path) -> None:
        # A library directory without a src/ child contributes no root.
        (tmp_path / "libraries" / "foo").mkdir(parents=True)
        assert CHU031.check(tmp_path) == []


class TestDriftedSeparators:
    """Em-dash, en-dash, and double-hyphen separators all fire."""

    def test_em_dash_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, _LIB_SRC, "x = 1  # noqa: ARG002 — runner contract\n")
        findings = CHU031.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU031"
        assert "' - '" in findings[0].message

    def test_en_dash_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, _LIB_SRC, "x = 1  # noqa: ARG002 – runner contract\n")
        findings = CHU031.check(tmp_path)
        assert len(findings) == 1

    def test_double_hyphen_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, _LIB_SRC, "x = 1  # noqa: SLF001 -- internal handoff\n")
        findings = CHU031.check(tmp_path)
        assert len(findings) == 1

    def test_pragma_em_dash_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _LIB_SRC,
            "except OSError:  # pragma: no cover — defensive\n",
        )
        findings = CHU031.check(tmp_path)
        assert len(findings) == 1

    def test_multi_code_noqa_em_dash_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _LIB_SRC,
            "from x import y  # noqa: E402, I001 — preceded by gc.collect().\n",
        )
        findings = CHU031.check(tmp_path)
        assert len(findings) == 1


class TestAcceptedForms:
    """The ' - ' form and the non-explanation / parenthetical forms pass."""

    def test_space_hyphen_space_passes(self, tmp_path: Path) -> None:
        _stage(tmp_path, _LIB_SRC, "x = 1  # noqa: ARG002 - runner contract\n")
        assert CHU031.check(tmp_path) == []

    def test_bare_code_no_explanation_passes(self, tmp_path: Path) -> None:
        _stage(tmp_path, _LIB_SRC, "import ssl  # noqa: PLC0415\n")
        assert CHU031.check(tmp_path) == []

    def test_parenthetical_form_passes(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _LIB_SRC,
            "def check(self, now_ms):  # noqa: ARG002 (runner contract uses now_ms)\n",
        )
        assert CHU031.check(tmp_path) == []

    def test_pragma_space_hyphen_space_passes(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _LIB_SRC,
            "except OSError:  # pragma: no cover - defensive\n",
        )
        assert CHU031.check(tmp_path) == []

    def test_em_dash_outside_noqa_passes(self, tmp_path: Path) -> None:
        # An em-dash in an ordinary comment is the writing-tone reviewer's
        # business, not this rule's; CHU031 only governs noqa / pragma
        # explanation separators.
        _stage(tmp_path, _LIB_SRC, "x = 1  # a plain comment — with an em-dash\n")
        assert CHU031.check(tmp_path) == []


class TestSuppression:
    """Adding CHU031 to the line's own noqa list mutes the rule."""

    def test_self_listed_noqa_suppresses(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _LIB_SRC,
            "x = 1  # noqa: ARG002, CHU031 — em-dash kept deliberately\n",
        )
        assert CHU031.check(tmp_path) == []


class TestScope:
    """Only ``src`` trees under libraries / workbench / test_harness scan."""

    def test_workbench_src_scanned(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "workbench/bar/src/chumicro_bar/mod.py",
            "x = 1  # noqa: S603 — args fully controlled\n",
        )
        assert len(CHU031.check(tmp_path)) == 1

    def test_test_harness_src_scanned(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "support/test_harness/src/chumicro_test_harness/net.py",
            "import wifi  # noqa: PLC0415 — CP-only\n",
        )
        assert len(CHU031.check(tmp_path)) == 1

    def test_tests_dir_not_scanned(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "libraries/foo/tests/test_mod.py",
            "x = 1  # noqa: ARG002 — runner contract\n",
        )
        assert CHU031.check(tmp_path) == []

    def test_non_py_not_scanned(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "libraries/foo/src/chumicro_foo/data.txt",
            "x = 1  # noqa: ARG002 — runner contract\n",
        )
        assert CHU031.check(tmp_path) == []


class TestSelfExempt:
    """The rule's own source / tests carry drifted examples and are exempt."""

    def test_rule_source_exempt(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "workbench/checks/src/chumicro_checks/rules/chu031.py",
            "x = 1  # noqa: ARG002 — runner contract\n",
        )
        assert CHU031.check(tmp_path) == []

    def test_rule_tests_exempt(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "workbench/checks/tests/test_chu031.py",
            "x = 1  # noqa: ARG002 — runner contract\n",
        )
        assert CHU031.check(tmp_path) == []


class TestRuleMetadata:
    def test_code(self) -> None:
        assert CHU031.code == "CHU031"

    def test_description_present(self) -> None:
        assert "noqa" in CHU031.description.lower()
