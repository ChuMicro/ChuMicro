"""Tests for promote_validate.py — experimental-tag promotion validator."""

from __future__ import annotations

import subprocess
from pathlib import Path

import promote_validate
import pytest
from promote_validate import PromoteValidationError


def _stub_tag_tree_docs(
    monkeypatch: pytest.MonkeyPatch, *, docs_specs: set[str],
) -> None:
    """Fake run_git so ``cat-file -e <spec>`` succeeds only for *docs_specs*.

    ``has_docs`` reads the experimental TAG's tree, not the working tree,
    so tests control it by the exact ``<tag>:<dir>/mkdocs.yml`` spec.
    """
    def fake_run_git(*arguments, **_kwargs):
        assert arguments[:2] == ("cat-file", "-e")
        code = 0 if arguments[2] in docs_specs else 1
        return subprocess.CompletedProcess(arguments, code)

    monkeypatch.setattr(promote_validate, "run_git", fake_run_git)


@pytest.fixture
def fake_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point promote_validate at a temp root with empty publishable roots."""
    (tmp_path / "libraries").mkdir()
    (tmp_path / "workbench").mkdir()
    (tmp_path / "support").mkdir()
    monkeypatch.setattr(promote_validate, "ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def no_stable_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub release_tags to empty so the monotonicity guard is inert.

    Tests that drive main() end to end would otherwise query the real
    repository's tags, coupling outcomes to whatever stable releases
    exist on the day the test runs.
    """
    monkeypatch.setattr(promote_validate, "release_tags", lambda *_a, **_k: [])


def _stub_stable_tags(monkeypatch: pytest.MonkeyPatch, tags: list[str]) -> None:
    """Make release_tags return *tags* for any package."""
    monkeypatch.setattr(promote_validate, "release_tags", lambda *_a, **_k: tags)


_PARSED_1_1_0 = {
    "library_name": "timing",
    "version": "1.1.0",
    "stable_tag": "chumicro-timing-v1.1.0",
    "source_zip": "chumicro-timing-v1.1.0-source.zip",
}


class TestParseTag:
    """Tests for _parse_tag."""

    def test_parses_canonical_tag(self) -> None:
        """A well-formed experimental tag parses cleanly."""
        parsed = promote_validate._parse_tag("chumicro-timing-v1.2.3-experimental")

        assert parsed == {
            "library_name": "timing",
            "version": "1.2.3",
            "stable_tag": "chumicro-timing-v1.2.3",
            "source_zip": "chumicro-timing-v1.2.3-source.zip",
        }

    def test_parses_hyphenated_library_name(self) -> None:
        """Library names containing hyphens parse correctly."""
        parsed = promote_validate._parse_tag(
            "chumicro-http-server-v0.1.0-experimental",
        )

        assert parsed["library_name"] == "http-server"
        assert parsed["version"] == "0.1.0"

    def test_rejects_stable_tag(self) -> None:
        """A stable tag (no -experimental suffix) raises."""
        with pytest.raises(PromoteValidationError, match="Expected an experimental tag"):
            promote_validate._parse_tag("chumicro-timing-v1.2.3")

    def test_rejects_non_semver_version(self) -> None:
        """A tag without major.minor.patch raises."""
        with pytest.raises(PromoteValidationError):
            promote_validate._parse_tag("chumicro-timing-v1.2-experimental")

    def test_rejects_empty_tag(self) -> None:
        """An empty tag raises."""
        with pytest.raises(PromoteValidationError):
            promote_validate._parse_tag("")


class TestLocatePackage:
    """Tests for _locate_package."""

    def test_finds_library(self, fake_root: Path) -> None:
        """Packages under libraries/ are returned with kind=library."""
        (fake_root / "libraries" / "timing").mkdir()

        result = promote_validate._locate_package("timing")

        assert result == {
            "library_dir": "libraries/timing",
            "package_kind": "library",
        }

    def test_finds_workbench(self, fake_root: Path) -> None:
        """Packages under workbench/ are returned with kind=workbench."""
        (fake_root / "workbench" / "deploy").mkdir()

        result = promote_validate._locate_package("deploy")

        assert result == {
            "library_dir": "workbench/deploy",
            "package_kind": "workbench",
        }

    def test_finds_support(self, fake_root: Path) -> None:
        """Packages under support/ are returned with kind=support
        (Decision 0111: PyPI-only, the bundle/channel/mip jobs skip them)."""
        (fake_root / "support" / "test_harness").mkdir()

        result = promote_validate._locate_package("test_harness")

        assert result == {
            "library_dir": "support/test_harness",
            "package_kind": "support",
        }

    def test_raises_when_missing(self, fake_root: Path) -> None:
        """A package that doesn't exist raises."""
        with pytest.raises(PromoteValidationError, match="No package found"):
            promote_validate._locate_package("nonexistent")


class TestCheckPreconditions:
    """Tests for _check_preconditions."""

    def test_passes_when_all_conditions_met(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Experimental tag present + stable tag absent + archive present → no raise."""
        monkeypatch.setattr(
            promote_validate, "_tag_exists",
            lambda tag: tag == "chumicro-timing-v1.0.0-experimental",
        )
        monkeypatch.setattr(
            promote_validate, "_release_has_source_archive",
            lambda _tag, _zip: True,
        )

        parsed = {
            "library_name": "timing",
            "version": "1.0.0",
            "stable_tag": "chumicro-timing-v1.0.0",
            "source_zip": "chumicro-timing-v1.0.0-source.zip",
        }
        promote_validate._check_preconditions(
            "chumicro-timing-v1.0.0-experimental", parsed,
        )

    def test_raises_when_experimental_tag_missing(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Missing experimental tag raises."""
        monkeypatch.setattr(promote_validate, "_tag_exists", lambda _: False)

        parsed = {
            "library_name": "timing", "version": "1.0.0",
            "stable_tag": "chumicro-timing-v1.0.0",
            "source_zip": "chumicro-timing-v1.0.0-source.zip",
        }
        with pytest.raises(PromoteValidationError, match="Experimental tag .* does not exist"):
            promote_validate._check_preconditions(
                "chumicro-timing-v1.0.0-experimental", parsed,
            )

    def test_raises_when_stable_tag_already_exists(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Existing stable tag raises."""
        monkeypatch.setattr(promote_validate, "_tag_exists", lambda _: True)

        parsed = {
            "library_name": "timing", "version": "1.0.0",
            "stable_tag": "chumicro-timing-v1.0.0",
            "source_zip": "chumicro-timing-v1.0.0-source.zip",
        }
        with pytest.raises(PromoteValidationError, match="Stable tag .* already exists"):
            promote_validate._check_preconditions(
                "chumicro-timing-v1.0.0-experimental", parsed,
            )

    def test_raises_when_archive_missing(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Missing source archive raises."""
        monkeypatch.setattr(
            promote_validate, "_tag_exists",
            lambda tag: tag == "chumicro-timing-v1.0.0-experimental",
        )
        monkeypatch.setattr(
            promote_validate, "_release_has_source_archive",
            lambda _tag, _zip: False,
        )

        parsed = {
            "library_name": "timing", "version": "1.0.0",
            "stable_tag": "chumicro-timing-v1.0.0",
            "source_zip": "chumicro-timing-v1.0.0-source.zip",
        }
        with pytest.raises(PromoteValidationError, match="Source archive"):
            promote_validate._check_preconditions(
                "chumicro-timing-v1.0.0-experimental", parsed,
            )

    def test_resume_passes_when_stable_tag_exists(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """resume=True inverts the stable-tag check: an existing stable tag passes."""
        monkeypatch.setattr(promote_validate, "_tag_exists", lambda _tag: True)
        monkeypatch.setattr(
            promote_validate, "_release_has_source_archive", lambda *_a: True,
        )

        parsed = {
            "library_name": "timing", "version": "1.0.0",
            "stable_tag": "chumicro-timing-v1.0.0",
            "source_zip": "chumicro-timing-v1.0.0-source.zip",
        }
        promote_validate._check_preconditions(
            "chumicro-timing-v1.0.0-experimental", parsed, resume=True,
        )

    def test_resume_raises_when_stable_tag_missing(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """resume=True with no stable tag raises: nothing to resume."""
        monkeypatch.setattr(
            promote_validate, "_tag_exists",
            lambda tag: tag.endswith("-experimental"),
        )
        monkeypatch.setattr(
            promote_validate, "_release_has_source_archive", lambda *_a: True,
        )

        parsed = {
            "library_name": "timing", "version": "1.0.0",
            "stable_tag": "chumicro-timing-v1.0.0",
            "source_zip": "chumicro-timing-v1.0.0-source.zip",
        }
        with pytest.raises(PromoteValidationError, match="resume requires stable tag"):
            promote_validate._check_preconditions(
                "chumicro-timing-v1.0.0-experimental", parsed, resume=True,
            )


class TestCheckMonotonicity:
    """Tests for _check_monotonicity — the version-downgrade guard."""

    def test_newer_version_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Promoting a version above the newest stable release passes."""
        _stub_stable_tags(monkeypatch, ["chumicro-timing-v1.0.0"])

        promote_validate._check_monotonicity(
            _PARSED_1_1_0, allow_downgrade=False, resume=False,
        )

    def test_equal_version_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Promoting the same version as the newest stable release raises."""
        _stub_stable_tags(monkeypatch, ["chumicro-timing-v1.1.0"])

        with pytest.raises(PromoteValidationError, match="not newer than"):
            promote_validate._check_monotonicity(
                _PARSED_1_1_0, allow_downgrade=False, resume=False,
            )

    def test_older_version_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Promoting a version below the newest stable release raises."""
        _stub_stable_tags(monkeypatch, ["chumicro-timing-v1.2.0"])

        with pytest.raises(PromoteValidationError, match="not newer than"):
            promote_validate._check_monotonicity(
                _PARSED_1_1_0, allow_downgrade=False, resume=False,
            )

    def test_allow_downgrade_suppresses_guard(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
    ) -> None:
        """allow_downgrade lets an older version through with a visible notice."""
        _stub_stable_tags(monkeypatch, ["chumicro-timing-v1.2.0"])

        promote_validate._check_monotonicity(
            _PARSED_1_1_0, allow_downgrade=True, resume=False,
        )

        assert "allow_downgrade set" in capsys.readouterr().out

    def test_versions_compare_numerically(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """1.10.0 beats 1.9.0; string comparison would invert this."""
        _stub_stable_tags(monkeypatch, ["chumicro-timing-v1.9.0"])

        parsed = {
            "library_name": "timing", "version": "1.10.0",
            "stable_tag": "chumicro-timing-v1.10.0",
            "source_zip": "chumicro-timing-v1.10.0-source.zip",
        }
        promote_validate._check_monotonicity(
            parsed, allow_downgrade=False, resume=False,
        )

    def test_no_stable_tags_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A first stable promotion has nothing to compare against."""
        _stub_stable_tags(monkeypatch, [])

        promote_validate._check_monotonicity(
            _PARSED_1_1_0, allow_downgrade=False, resume=False,
        )

    def test_resume_excludes_own_stable_tag(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """resume must not reject the promotion against its own existing tag."""
        _stub_stable_tags(
            monkeypatch, ["chumicro-timing-v1.1.0", "chumicro-timing-v1.0.0"],
        )

        promote_validate._check_monotonicity(
            _PARSED_1_1_0, allow_downgrade=False, resume=True,
        )

    def test_resume_fails_when_newer_stable_exists(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Resuming after a newer stable release shipped would downgrade: raise."""
        _stub_stable_tags(
            monkeypatch, ["chumicro-timing-v1.2.0", "chumicro-timing-v1.1.0"],
        )

        with pytest.raises(PromoteValidationError, match="not newer than"):
            promote_validate._check_monotonicity(
                _PARSED_1_1_0, allow_downgrade=False, resume=True,
            )

    def test_resume_with_allow_downgrade_composes(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
    ) -> None:
        """allow_downgrade is the deliberate override for a superseded resume.

        A promotion that died after its tag write and was then overtaken
        by a newer stable release can only finish its remaining legs this
        way; the flags must compose rather than exclude each other.
        """
        _stub_stable_tags(
            monkeypatch, ["chumicro-timing-v1.2.0", "chumicro-timing-v1.1.0"],
        )

        promote_validate._check_monotonicity(
            _PARSED_1_1_0, allow_downgrade=True, resume=True,
        )

        assert "allow_downgrade set" in capsys.readouterr().out


class TestMain:
    """Tests for the CLI entry point."""

    def test_emits_all_outputs(
        self, fake_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        no_stable_tags: None,
    ) -> None:
        """A valid tag + present package emits all expected key=value lines."""
        (fake_root / "libraries" / "timing").mkdir()
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        monkeypatch.setattr(
            promote_validate, "_tag_exists",
            lambda tag: tag.endswith("-experimental"),
        )
        monkeypatch.setattr(
            promote_validate, "_release_has_source_archive", lambda *_a: True,
        )

        result = promote_validate.main([
            "--tag", "chumicro-timing-v1.0.0-experimental",
        ])

        assert result == 0
        captured = capsys.readouterr()
        for key in (
            "library_name=timing",
            "version=1.0.0",
            "stable_tag=chumicro-timing-v1.0.0",
            "source_zip=chumicro-timing-v1.0.0-source.zip",
            "library_dir=libraries/timing",
            "package_kind=library",
        ):
            assert key in captured.out

    def test_writes_to_github_output_when_set(
        self, fake_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        no_stable_tags: None,
    ) -> None:
        """When GITHUB_OUTPUT is set, key=value lines go to that file."""
        (fake_root / "libraries" / "timing").mkdir()

        github_output = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
        monkeypatch.setattr(
            promote_validate, "_tag_exists",
            lambda tag: tag.endswith("-experimental"),
        )
        monkeypatch.setattr(
            promote_validate, "_release_has_source_archive", lambda *_a: True,
        )

        result = promote_validate.main([
            "--tag", "chumicro-timing-v1.0.0-experimental",
        ])

        assert result == 0
        assert "library_name=timing" in github_output.read_text()

    def test_returns_nonzero_on_malformed_tag(
        self, fake_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A stable tag (missing -experimental suffix) exits 1."""
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

        result = promote_validate.main([
            "--tag", "chumicro-timing-v1.0.0",
        ])

        assert result == 1
        captured = capsys.readouterr()
        assert "::error::" in captured.err

    def test_returns_nonzero_on_missing_package(
        self, fake_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A tag for a non-existent package exits 1."""
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

        result = promote_validate.main([
            "--tag", "chumicro-nonexistent-v1.0.0-experimental",
        ])

        assert result == 1
        captured = capsys.readouterr()
        assert "No package found" in captured.err

    def test_uses_tag_env_var(
        self, fake_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        no_stable_tags: None,
    ) -> None:
        """$TAG environment variable is the default tag source."""
        (fake_root / "libraries" / "timing").mkdir()
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        monkeypatch.setenv("TAG", "chumicro-timing-v2.0.0-experimental")
        monkeypatch.setattr(
            promote_validate, "_tag_exists",
            lambda tag: tag.endswith("-experimental"),
        )
        monkeypatch.setattr(
            promote_validate, "_release_has_source_archive", lambda *_a: True,
        )

        result = promote_validate.main([])

        assert result == 0
        assert "version=2.0.0" in capsys.readouterr().out

    def test_returns_nonzero_when_no_tag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
    ) -> None:
        """Missing both --tag and $TAG exits 1."""
        monkeypatch.delenv("TAG", raising=False)
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

        result = promote_validate.main([])

        assert result == 1
        assert "No tag provided" in capsys.readouterr().err

    def test_resume_with_allow_downgrade_recovers_superseded_promotion(
        self, fake_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Both flags together finish a resumed promotion a newer stable overtook."""
        (fake_root / "libraries" / "timing").mkdir()
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        _stub_stable_tags(
            monkeypatch, ["chumicro-timing-v1.2.0", "chumicro-timing-v1.0.0"],
        )
        _stub_tag_tree_docs(monkeypatch, docs_specs=set())
        monkeypatch.setattr(promote_validate, "_tag_exists", lambda _tag: True)
        monkeypatch.setattr(
            promote_validate, "_release_has_source_archive", lambda *_a: True,
        )

        result = promote_validate.main([
            "--tag", "chumicro-timing-v1.0.0-experimental",
            "--resume", "--allow-downgrade",
        ])

        assert result == 0
        assert "allow_downgrade set" in capsys.readouterr().out

    def test_resume_env_var_inverts_stable_tag_check(
        self, fake_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        no_stable_tags: None,
    ) -> None:
        """$RESUME=true lets a promotion with an existing stable tag through."""
        (fake_root / "libraries" / "timing").mkdir()
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        monkeypatch.setenv("RESUME", "true")
        monkeypatch.delenv("ALLOW_DOWNGRADE", raising=False)
        monkeypatch.setattr(promote_validate, "_tag_exists", lambda _tag: True)
        monkeypatch.setattr(
            promote_validate, "_release_has_source_archive", lambda *_a: True,
        )

        result = promote_validate.main([
            "--tag", "chumicro-timing-v1.0.0-experimental",
        ])

        assert result == 0

    def test_emits_has_docs_true_for_package_with_docs(
        self, fake_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        no_stable_tags: None,
    ) -> None:
        """mkdocs.yml present in the TAG's tree emits has_docs=true."""
        (fake_root / "libraries" / "timing").mkdir()
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        _stub_tag_tree_docs(monkeypatch, docs_specs={
            "chumicro-timing-v1.0.0-experimental:libraries/timing/mkdocs.yml",
        })
        monkeypatch.setattr(
            promote_validate, "_tag_exists",
            lambda tag: tag.endswith("-experimental"),
        )
        monkeypatch.setattr(
            promote_validate, "_release_has_source_archive", lambda *_a: True,
        )

        result = promote_validate.main([
            "--tag", "chumicro-timing-v1.0.0-experimental",
        ])

        assert result == 0
        assert "has_docs=true" in capsys.readouterr().out

    def test_emits_has_docs_false_for_package_without_docs(
        self, fake_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        no_stable_tags: None,
    ) -> None:
        """No mkdocs.yml in the TAG's tree emits has_docs=false, even if main has one."""
        package_dir = fake_root / "workbench" / "pytest-device"
        package_dir.mkdir()
        (package_dir / "mkdocs.yml").write_text("site_name: added-after-tag\n")
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        _stub_tag_tree_docs(monkeypatch, docs_specs=set())
        monkeypatch.setattr(
            promote_validate, "_tag_exists",
            lambda tag: tag.endswith("-experimental"),
        )
        monkeypatch.setattr(
            promote_validate, "_release_has_source_archive", lambda *_a: True,
        )

        result = promote_validate.main([
            "--tag", "chumicro-pytest-device-v1.0.0-experimental",
        ])

        assert result == 0
        assert "has_docs=false" in capsys.readouterr().out
