"""Tests for CHU015 — module-docstring capability claims vs symbols."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu015 import CHU015, _offending_symbols

_SRC = "libraries/foo/src/chumicro_foo/client.py"


def _stage(repo_root: Path, relative: str, content: str) -> Path:
    target = repo_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


class TestSilentNoOp:
    def test_empty_repo(self, tmp_path: Path) -> None:
        assert CHU015.check(tmp_path) == []

    def test_no_libraries_dir(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "workbench/foo/src/foo.py",
            '"""POST is future work."""\n\n\ndef post():\n    pass\n',
        )
        # workbench is out of scope.
        assert CHU015.check(tmp_path) == []

    def test_no_module_docstring(self, tmp_path: Path) -> None:
        _stage(tmp_path, _SRC, "def post():\n    pass\n")
        assert CHU015.check(tmp_path) == []

    def test_docstring_without_not_yet_phrase(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            _SRC,
            '"""Ships GET and POST over HTTP."""\n\n\ndef post():\n    pass\n',
        )
        assert CHU015.check(tmp_path) == []


class TestFlags:
    def test_future_work_claim_for_shipped_symbol(
        self, tmp_path: Path,
    ) -> None:
        _stage(
            tmp_path,
            _SRC,
            '"""HTTP client.\n\n'
            "Ships GET.  TLS, POST, JSON, redirects are future work.\n"
            '"""\n\n\ndef get():\n    pass\n\n\ndef post():\n    pass\n',
        )
        findings = CHU015.check(tmp_path)
        assert len(findings) == 1
        assert "post" in findings[0].message
        assert findings[0].code == "CHU015"

    def test_not_yet_implemented_method(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            _SRC,
            '"""Client.\n\nThe reconnect path is not yet implemented.\n"""\n'
            "\n\nclass Client:\n    def reconnect(self):\n        pass\n",
        )
        findings = CHU015.check(tmp_path)
        assert len(findings) == 1
        assert "reconnect" in findings[0].message

    def test_finding_line_is_the_phrase_line(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            _SRC,
            '"""Title line.\n\n'  # line 1
            "Body line two.\n"  # line 3
            "POST is future work.\n"  # line 4
            '"""\n\n\ndef post():\n    pass\n',
        )
        findings = CHU015.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].line == 4


class TestFalsePositiveGuards:
    def test_clause_split_separates_entrypoint_from_planned(self) -> None:
        text = (
            "The from_config constructor is the entry point; raw socket "
            "injection is planned for later."
        )
        assert _offending_symbols(text, {"from_config"}) == set()

    def test_private_symbols_ignored(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            _SRC,
            '"""_post helper is future work."""\n\n\n'
            "def _post():\n    pass\n",
        )
        assert CHU015.check(tmp_path) == []

    def test_unrelated_future_work_not_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            _SRC,
            '"""Async support is future work."""\n\n\ndef get():\n    pass\n',
        )
        # No symbol named in the not-yet clause → clean.
        assert CHU015.check(tmp_path) == []


class TestSuppression:
    def test_noqa_on_phrase_line(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            _SRC,
            '"""Client.\n\n'
            "POST is future work.  # noqa: CHU015 — post() is a "
            "deliberate unrelated stub\n"
            '"""\n\n\ndef post():\n    pass\n',
        )
        assert CHU015.check(tmp_path) == []


class TestAgainstRealRepo:
    """Every library module docstring must match its shipped surface.

    Guards the regression mechanically — a re-introduced "future
    work" claim for a shipped symbol fails this test, not just review.
    """

    def test_repo_library_docstrings_are_clean(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        assert (repo_root / "libraries").is_dir()
        assert CHU015.check(repo_root) == []
