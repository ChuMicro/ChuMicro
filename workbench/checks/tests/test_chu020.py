"""Tests for CHU020: closed AI-tic phrase set."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu020 import CHU020


def _stage(repo_root: Path, relative: str, content: str) -> Path:
    target = repo_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


class TestSilentNoOp:
    def test_empty_repo(self, tmp_path: Path) -> None:
        assert CHU020.check(tmp_path) == []

    def test_clean_prose(self, tmp_path: Path) -> None:
        _stage(tmp_path, "AGENTS.md", "We use the runner pattern.\n")
        assert CHU020.check(tmp_path) == []


class TestAdjectiveBans:
    def test_comprehensive_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "docs/x.md", "This is a comprehensive solution.\n")
        findings = CHU020.check(tmp_path)
        assert len(findings) == 1
        assert "comprehensive" in findings[0].message

    def test_robust_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "docs/x.md", "A robust handler.\n")
        findings = CHU020.check(tmp_path)
        assert len(findings) == 1
        assert "robust" in findings[0].message

    def test_seamlessly_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "docs/x.md", "It seamlessly integrates.\n")
        assert len(CHU020.check(tmp_path)) == 1

    def test_cutting_edge_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "docs/x.md", "Cutting-edge framework.\n")
        assert len(CHU020.check(tmp_path)) == 1

    def test_best_in_class_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "docs/x.md", "Best-in-class implementation.\n")
        assert len(CHU020.check(tmp_path)) == 1


class TestSentenceOpenerBans:
    def test_it_is_worth_noting_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "docs/x.md", "It is worth noting that we use Y.\n")
        findings = CHU020.check(tmp_path)
        assert len(findings) == 1
        assert "sentence opener" in findings[0].message

    def test_it_should_be_noted_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "docs/x.md",
            "Background.  It should be noted that handlers reset on boot.\n",
        )
        assert len(CHU020.check(tmp_path)) == 1

    def test_lets_dive_into_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "docs/x.md", "Let's dive into the transport layer.\n")
        assert len(CHU020.check(tmp_path)) == 1

    def test_lets_explore_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "docs/x.md", "Let's explore the API surface.\n")
        assert len(CHU020.check(tmp_path)) == 1

    def test_in_this_section_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "docs/x.md",
            "In this section, we will walk through setup.\n",
        )
        assert len(CHU020.check(tmp_path)) == 1


class TestQuotedDataExemption:
    """Phrases inside paired quote/backtick delimiters are data, exempt."""

    def test_backticked_adjective_not_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "AGENTS.md", "Avoid the word `comprehensive`.\n")
        assert CHU020.check(tmp_path) == []

    def test_double_quoted_phrase_not_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "AGENTS.md",
            'The ban: "It is worth noting that" is forbidden.\n',
        )
        assert CHU020.check(tmp_path) == []

    def test_bolded_quoted_phrase_not_flagged(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "AGENTS.md",
            'Specific ban: **"comprehensive" / "robust"** are out.\n',
        )
        assert CHU020.check(tmp_path) == []

    def test_unquoted_in_same_sentence_flagged(
        self, tmp_path: Path,
    ) -> None:
        # Mixed line: a backticked example AND an unquoted usage on the
        # same line.  The backticked one is exempt, the unquoted one is
        # the AI-tic the rule catches.
        _stage(
            tmp_path,
            "AGENTS.md",
            "We say `robust` is banned, but the handler is robust.\n",
        )
        findings = CHU020.check(tmp_path)
        assert len(findings) == 1

    def test_genuine_single_quoted_phrase_still_exempt(
        self, tmp_path: Path,
    ) -> None:
        # A word actually wrapped in single quotes is data, exempt.
        _stage(tmp_path, "AGENTS.md", "Avoid the word 'comprehensive'.\n")
        assert CHU020.check(tmp_path) == []


class TestContractionsAreNotQuotes:
    """Contraction / possessive apostrophes must not fake a quote pair."""

    def test_contraction_flanked_adjective_still_fires(
        self, tmp_path: Path,
    ) -> None:
        # ``It's`` and ``isn't`` bracket the adjective with apostrophes,
        # but those are contractions, not quotes: the adjective fires.
        _stage(
            tmp_path,
            "docs/x.md",
            "It's a comprehensive guide, isn't it.\n",
        )
        findings = CHU020.check(tmp_path)
        assert len(findings) == 1
        assert "comprehensive" in findings[0].message

    def test_possessive_flanked_adjective_still_fires(
        self, tmp_path: Path,
    ) -> None:
        _stage(
            tmp_path,
            "docs/x.md",
            "Don't call it robust unless the user's tests prove it.\n",
        )
        findings = CHU020.check(tmp_path)
        assert len(findings) == 1
        assert "robust" in findings[0].message


class TestScope:
    def test_next_up_out_of_scope(self, tmp_path: Path) -> None:
        # next-up / workstreams are churny journal prose, not contract.
        _stage(tmp_path, "plans/next-up.md", "Build a robust system.\n")
        assert CHU020.check(tmp_path) == []

    def test_library_readme_out_of_scope(self, tmp_path: Path) -> None:
        _stage(tmp_path, "libraries/foo/README.md", "Robust client.\n")
        assert CHU020.check(tmp_path) == []

    def test_agents_md_in_scope(self, tmp_path: Path) -> None:
        _stage(tmp_path, "AGENTS.md", "The handler is robust.\n")
        assert len(CHU020.check(tmp_path)) == 1

    def test_decisions_in_scope(self, tmp_path: Path) -> None:
        _stage(tmp_path, "plans/decisions/0042-x.md", "Robust design.\n")
        assert len(CHU020.check(tmp_path)) == 1

    def test_docs_in_scope(self, tmp_path: Path) -> None:
        _stage(tmp_path, "docs/contributing/style.md", "Robust style.\n")
        assert len(CHU020.check(tmp_path)) == 1


class TestSuppression:
    def test_noqa_suppresses(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            "docs/x.md",
            "Background.  The handler is robust.  <!-- noqa: CHU020 -->\n",
        )
        assert CHU020.check(tmp_path) == []


class TestCaseInsensitive:
    def test_capitalized_adjective_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, "docs/x.md", "Comprehensive handler.\n")
        assert len(CHU020.check(tmp_path)) == 1


class TestRuleMetadata:
    def test_code(self) -> None:
        assert CHU020.code == "CHU020"

    def test_description_present(self) -> None:
        assert "AI-tic" in CHU020.description
