"""Tests for the LeakRule pattern-walker abstraction."""

from __future__ import annotations

import re
from pathlib import Path

from chumicro_checks.rules._leak_rule import LeakRule, everywhere


def _make_file(repo_root: Path, relative: str, content: str) -> Path:
    target = repo_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


class TestSilentNoOp:
    def test_empty_scan_roots(self, tmp_path: Path) -> None:
        rule = LeakRule(
            code="CHU999",
            description="test",
            scan_roots_for=lambda _root: [],
            patterns=(),
            suffixes=(".py",),
        )
        assert rule.check(tmp_path) == []

    def test_non_existent_scan_roots(self, tmp_path: Path) -> None:
        rule = LeakRule(
            code="CHU999",
            description="test",
            scan_roots_for=lambda root: [root / "missing"],
            patterns=((re.compile(r"forbidden"), "x", everywhere),),
            suffixes=(".py",),
        )
        assert rule.check(tmp_path) == []


class TestPatternMatching:
    def test_single_match_emits_finding(self, tmp_path: Path) -> None:
        target = _make_file(tmp_path, "src/x.py", "forbidden token here\n")
        rule = LeakRule(
            code="CHU999",
            description="test",
            scan_roots_for=lambda root: [root / "src"],
            patterns=((re.compile(r"forbidden"), "found it", everywhere),),
            suffixes=(".py",),
        )
        findings = rule.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].path == target
        assert findings[0].line == 1
        assert findings[0].code == "CHU999"
        assert findings[0].message == "found it"

    def test_multiple_lines_each_emit(self, tmp_path: Path) -> None:
        _make_file(tmp_path, "src/x.py", "forbidden\nclean\nforbidden\n")
        rule = LeakRule(
            code="CHU999",
            description="test",
            scan_roots_for=lambda root: [root / "src"],
            patterns=((re.compile(r"forbidden"), "x", everywhere),),
            suffixes=(".py",),
        )
        findings = rule.check(tmp_path)
        assert [finding.line for finding in findings] == [1, 3]

    def test_first_matching_pattern_wins_per_line(self, tmp_path: Path) -> None:
        _make_file(tmp_path, "src/x.py", "alpha beta\n")
        rule = LeakRule(
            code="CHU999",
            description="test",
            scan_roots_for=lambda root: [root / "src"],
            patterns=(
                (re.compile(r"alpha"), "first", everywhere),
                (re.compile(r"beta"), "second", everywhere),
            ),
            suffixes=(".py",),
        )
        findings = rule.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].message == "first"


class TestScopePredicate:
    def test_predicate_false_skips_pattern(self, tmp_path: Path) -> None:
        _make_file(tmp_path, "src/exempt/x.py", "forbidden\n")
        _make_file(tmp_path, "src/applied/x.py", "forbidden\n")

        def applies(filepath: Path) -> bool:
            return "exempt" not in filepath.as_posix()

        rule = LeakRule(
            code="CHU999",
            description="test",
            scan_roots_for=lambda root: [root / "src"],
            patterns=((re.compile(r"forbidden"), "x", applies),),
            suffixes=(".py",),
        )
        findings = rule.check(tmp_path)
        assert len(findings) == 1
        assert "applied" in findings[0].path.as_posix()

    def test_per_pattern_predicates_independent(self, tmp_path: Path) -> None:
        _make_file(tmp_path, "src/a/x.py", "alpha beta\n")
        _make_file(tmp_path, "src/b/x.py", "alpha beta\n")
        rule = LeakRule(
            code="CHU999",
            description="test",
            scan_roots_for=lambda root: [root / "src"],
            patterns=(
                (re.compile(r"alpha"), "a-only", lambda filepath: "/a/" in filepath.as_posix()),
                (re.compile(r"beta"), "b-only", lambda filepath: "/b/" in filepath.as_posix()),
            ),
            suffixes=(".py",),
        )
        findings = rule.check(tmp_path)
        messages = sorted(finding.message for finding in findings)
        assert messages == ["a-only", "b-only"]


class TestSuppression:
    def test_noqa_suppresses_line(self, tmp_path: Path) -> None:
        _make_file(tmp_path, "src/x.py", "forbidden  # noqa: CHU999\n")
        rule = LeakRule(
            code="CHU999",
            description="test",
            scan_roots_for=lambda root: [root / "src"],
            patterns=((re.compile(r"forbidden"), "x", everywhere),),
            suffixes=(".py",),
        )
        assert rule.check(tmp_path) == []

    def test_noqa_marker_does_not_self_flag(self, tmp_path: Path) -> None:
        # If the rule's pattern matched the literal "CHU999" anywhere on
        # the line, a suppression marker would self-flag.  strip_noqa
        # before pattern matching prevents this.
        _make_file(tmp_path, "src/x.py", "important text  # noqa: CHU999\n")
        rule = LeakRule(
            code="CHU999",
            description="test",
            scan_roots_for=lambda root: [root / "src"],
            patterns=((re.compile(r"CHU\d{3}"), "x", everywhere),),
            suffixes=(".py",),
        )
        assert rule.check(tmp_path) == []

    def test_html_noqa_suppresses_in_markdown(self, tmp_path: Path) -> None:
        _make_file(tmp_path, "src/x.md", "forbidden <!-- noqa: CHU999 -->\n")
        rule = LeakRule(
            code="CHU999",
            description="test",
            scan_roots_for=lambda root: [root / "src"],
            patterns=((re.compile(r"forbidden"), "x", everywhere),),
            suffixes=(".md",),
        )
        assert rule.check(tmp_path) == []


class TestMultiRoot:
    def test_overlapping_roots_dedupe(self, tmp_path: Path) -> None:
        _make_file(tmp_path, "outer/inner/x.py", "forbidden\n")
        rule = LeakRule(
            code="CHU999",
            description="test",
            scan_roots_for=lambda root: [root / "outer", root / "outer" / "inner"],
            patterns=((re.compile(r"forbidden"), "x", everywhere),),
            suffixes=(".py",),
        )
        findings = rule.check(tmp_path)
        # The same file is reachable from both roots. Emit only once.
        assert len(findings) == 1


class TestSuffixFiltering:
    def test_only_listed_suffixes_walked(self, tmp_path: Path) -> None:
        _make_file(tmp_path, "src/a.py", "forbidden\n")
        _make_file(tmp_path, "src/b.txt", "forbidden\n")
        rule = LeakRule(
            code="CHU999",
            description="test",
            scan_roots_for=lambda root: [root / "src"],
            patterns=((re.compile(r"forbidden"), "x", everywhere),),
            suffixes=(".py",),
        )
        findings = rule.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].path.suffix == ".py"


class TestEverywhereHelper:
    def test_returns_true_for_any_path(self) -> None:
        assert everywhere(Path("anywhere/x.py")) is True
        assert everywhere(Path("/")) is True
