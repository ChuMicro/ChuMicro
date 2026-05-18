"""Tests for CHU017 — coverage-claim honesty."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu017 import CHU017


def _stage(repo_root: Path, relative: str, content: str) -> Path:
    target = repo_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


class TestSilentNoOp:
    def test_empty_repo(self, tmp_path: Path) -> None:
        assert CHU017.check(tmp_path) == []

    def test_doc_without_percentage(self, tmp_path: Path) -> None:
        _stage(tmp_path, "docs/x.md", "Coverage is enforced by a gate.\n")
        assert CHU017.check(tmp_path) == []

    def test_out_of_scope_tree_ignored(self, tmp_path: Path) -> None:
        # plans/next-up + workstreams + library READMEs are out of scope.
        _stage(
            tmp_path,
            "plans/next-up.md",
            "Hit 94% coverage of all shipped code.\n",
        )
        assert CHU017.check(tmp_path) == []


class TestFlags:
    def test_affirmative_whole_codebase_claim(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "docs/contributing/testing.md",
            "Our suite gives 94% coverage of all shipped code.\n",
        )
        findings = CHU017.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU017"

    def test_fully_covered_claim_in_adr(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "plans/decisions/0099-x.md",
            "Every library is fully covered at 94 %.\n",
        )
        findings = CHU017.check(tmp_path)
        assert len(findings) == 1

    def test_agents_md_in_scope(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "AGENTS.md",
            "The 100% coverage of the codebase is the safety bar.\n",
        )
        assert len(CHU017.check(tmp_path)) == 1


class TestExemptions:
    """The corrected / meta statements of the contract must pass."""

    def test_negated_claim_not_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "docs/x.md",
            "It is 94 % of reachable lines, not 94 % of shipped code.\n",
        )
        assert CHU017.check(tmp_path) == []

    def test_cpython_reachable_qualifier_not_flagged(
        self, tmp_path: Path,
    ) -> None:
        _stage(
            tmp_path,
            "AGENTS.md",
            "94 % is a CPython-reachable figure, not 94 % of shipped "
            "code; cite it only with that scope.\n",
        )
        assert CHU017.check(tmp_path) == []

    def test_post_exclusion_qualifier_not_flagged(
        self, tmp_path: Path,
    ) -> None:
        _stage(
            tmp_path,
            "plans/decisions/0025-x.md",
            "It is a post-exclusion number: 94 % of the codebase "
            "reachable under CPython.\n",
        )
        assert CHU017.check(tmp_path) == []

    def test_meta_rule_statement_not_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "plans/decisions/0025-x.md",
            "Any doc that cites 94 % as covering all code must carry "
            "this scope, or be wrong.\n",
        )
        assert CHU017.check(tmp_path) == []


class TestSuppression:
    def test_noqa_on_line(self, tmp_path: Path) -> None:
        # Markdown noqa form is `<!-- noqa: CHU017 -->`; the why is
        # the surrounding prose (shared _noqa helper anchors on -->).
        _stage(
            tmp_path,
            "docs/x.md",
            "Marketing page, scope caveated below.  We hit 94% coverage "
            "of all shipped code.  <!-- noqa: CHU017 -->\n",
        )
        assert CHU017.check(tmp_path) == []


class TestAgainstRealRepo:
    """The real coverage-contract docs must stay honest.

    Critically: the corrected AGENTS.md / ADR-0025 text negates the
    bad framing and carries the CPython-reachable qualifier — this
    guards that the rule does not regress into flagging the very
    statement of the honest contract.
    """

    def test_repo_coverage_docs_are_clean(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        assert (repo_root / "AGENTS.md").is_file()
        assert CHU017.check(repo_root) == []
