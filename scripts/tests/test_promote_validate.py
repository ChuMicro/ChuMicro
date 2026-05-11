"""Tests for promote_validate.py — experimental-tag promotion validator."""

from __future__ import annotations

from pathlib import Path

import promote_validate
import pytest
from promote_validate import PromoteValidationError


@pytest.fixture
def fake_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point promote_validate at a temporary root with empty libraries/+workbench/."""
    (tmp_path / "libraries").mkdir()
    (tmp_path / "workbench").mkdir()
    monkeypatch.setattr(promote_validate, "ROOT", tmp_path)
    return tmp_path


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


class TestMain:
    """Tests for the CLI entry point."""

    def test_emits_all_outputs(
        self, fake_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A valid tag + present package emits all expected key=value lines."""
        (fake_root / "libraries" / "timing").mkdir()
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

        result = promote_validate.main([
            "--tag", "chumicro-timing-v1.0.0-experimental",
            "--skip-release-check",
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
    ) -> None:
        """When GITHUB_OUTPUT is set, key=value lines go to that file."""
        (fake_root / "libraries" / "timing").mkdir()

        github_output = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))

        result = promote_validate.main([
            "--tag", "chumicro-timing-v1.0.0-experimental",
            "--skip-release-check",
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
            "--skip-release-check",
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
            "--skip-release-check",
        ])

        assert result == 1
        captured = capsys.readouterr()
        assert "No package found" in captured.err

    def test_uses_tag_env_var(
        self, fake_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """$TAG environment variable is the default tag source."""
        (fake_root / "libraries" / "timing").mkdir()
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        monkeypatch.setenv("TAG", "chumicro-timing-v2.0.0-experimental")

        result = promote_validate.main(["--skip-release-check"])

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
