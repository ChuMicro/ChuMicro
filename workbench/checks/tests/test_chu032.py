"""Tests for CHU032: cross-reference pointer phrases in publishable comments."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu032 import CHU032


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
        assert CHU032.check(tmp_path) == []

    def test_no_src_dir(self, tmp_path: Path) -> None:
        (tmp_path / "libraries" / "foo").mkdir(parents=True)
        assert CHU032.check(tmp_path) == []


class TestPointerPhrases:
    """Each enumerated cross-reference phrase fires."""

    def test_see_named_docstring_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _LIB_SRC,
            "# see ``SocketConnector``'s docstring for the contract\n",
        )
        findings = CHU032.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU032"
        assert "docstring" in findings[0].message

    def test_documents_the_rationale_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _LIB_SRC,
            '"""The sibling module documents the rationale for this cap."""\n',
        )
        findings = CHU032.check(tmp_path)
        assert len(findings) == 1
        assert "documents the rationale" in findings[0].message

    def test_documents_the_why_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _LIB_SRC,
            "# the adapter module documents the why behind this fallback\n",
        )
        findings = CHU032.check(tmp_path)
        assert len(findings) == 1

    def test_follows_the_pattern_in_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _LIB_SRC,
            "# follows the pattern in the requests client\n",
        )
        findings = CHU032.check(tmp_path)
        assert len(findings) == 1
        assert "follows the pattern" in findings[0].message

    def test_follows_the_pattern_of_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _LIB_SRC,
            "# follows the pattern of the sibling factory\n",
        )
        findings = CHU032.check(tmp_path)
        assert len(findings) == 1

    def test_per_the_pattern_in_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _LIB_SRC,
            "# closes the socket per the pattern in the websockets server\n",
        )
        findings = CHU032.check(tmp_path)
        assert len(findings) == 1


class TestLegitimatePhrases:
    """Same-file references and dependency mentions stay clean."""

    def test_see_module_docstring_passes(self, tmp_path: Path) -> None:
        # No backtick-quoted name + possessive: a same-file pointer at
        # this module's own docstring, legible to a cold reader here.
        _stage(tmp_path, _LIB_SRC, "# see module docstring for the contract\n")
        assert CHU032.check(tmp_path) == []

    def test_see_class_docstring_above_passes(self, tmp_path: Path) -> None:
        _stage(tmp_path, _LIB_SRC, "# see the class docstring above\n")
        assert CHU032.check(tmp_path) == []

    def test_built_on_dependency_mention_passes(self, tmp_path: Path) -> None:
        # A bare dependency mention names an architectural fact, not a
        # go-read-another-file pointer.
        _stage(
            tmp_path, _LIB_SRC,
            '"""Built on :mod:`chumicro_sockets` (TCP + TLS)."""\n',
        )
        assert CHU032.check(tmp_path) == []

    def test_fake_naming_real_type_passes(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "libraries/foo/src/chumicro_foo/testing.py",
            '"""Stand-in for :class:`chumicro_sockets.testing.FakeSocket`."""\n',
        )
        assert CHU032.check(tmp_path) == []


class TestSuppression:
    """``# noqa: CHU032`` and the noqa carve-out mute the rule."""

    def test_noqa_suppresses(self, tmp_path: Path) -> None:
        _stage(
            tmp_path, _LIB_SRC,
            "# follows the pattern in X  # noqa: CHU032 - kept on purpose\n",
        )
        assert CHU032.check(tmp_path) == []

    def test_text_on_noqa_line_exempt(self, tmp_path: Path) -> None:
        # A CHU027-style suppression legitimately names its duplicate's
        # home; the noqa-line carve-out keeps it clean even though the
        # phrase appears after the directive.
        _stage(
            tmp_path, _LIB_SRC,
            "x = 1  # noqa: CHU027 - follows the pattern in the sibling _wire.py\n",
        )
        assert CHU032.check(tmp_path) == []


class TestScope:
    """Only ``src`` trees under libraries / workbench scan; tests excluded."""

    def test_workbench_src_scanned(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "workbench/bar/src/chumicro_bar/mod.py",
            "# follows the pattern in the deploy transport\n",
        )
        assert len(CHU032.check(tmp_path)) == 1

    def test_tests_dir_not_scanned(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "libraries/foo/tests/test_mod.py",
            "# follows the pattern in X\n",
        )
        assert CHU032.check(tmp_path) == []

    def test_docs_dir_not_scanned(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "libraries/foo/docs/guide.md",
            "follows the pattern in X\n",
        )
        assert CHU032.check(tmp_path) == []


class TestSelfExempt:
    """The rule's own source / tests carry the flagged phrases and are exempt."""

    def test_rule_source_exempt(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "workbench/checks/src/chumicro_checks/rules/chu032.py",
            "# follows the pattern in X\n",
        )
        assert CHU032.check(tmp_path) == []

    def test_rule_tests_exempt(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "workbench/checks/tests/test_chu032.py",
            "# follows the pattern in X\n",
        )
        assert CHU032.check(tmp_path) == []


class TestRuleMetadata:
    def test_code(self) -> None:
        assert CHU032.code == "CHU032"

    def test_description_present(self) -> None:
        assert "cross-reference" in CHU032.description.lower()
