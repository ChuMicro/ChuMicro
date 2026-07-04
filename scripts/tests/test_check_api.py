"""Tests for check_api.py — version parsing, bump detection, and the
pre-publication warn-only breakage gate (Decision 0092)."""

import types
from pathlib import Path

import check_api
from check_api import _bump_level, _parse_version


class TestParseVersion:
    """Tests for _parse_version."""

    def test_simple_version(self):
        """Parse a standard three-part version."""
        assert _parse_version("1.2.3") == (1, 2, 3)

    def test_zero_version(self):
        """Parse a 0.x.x version."""
        assert _parse_version("0.1.0") == (0, 1, 0)

    def test_large_numbers(self):
        """Parse versions with multi-digit components."""
        assert _parse_version("12.34.56") == (12, 34, 56)

    def test_version_with_suffix(self):
        """Parse a version string that has trailing text (e.g. pre-release)."""
        assert _parse_version("1.2.3-rc1") == (1, 2, 3)

    def test_invalid_version_returns_none(self):
        """Non-version strings return None."""
        assert _parse_version("not-a-version") is None

    def test_empty_string_returns_none(self):
        """Empty string returns None."""
        assert _parse_version("") is None

    def test_partial_version_returns_none(self):
        """Two-part version returns None (requires three parts)."""
        assert _parse_version("1.2") is None


class TestBumpLevel:
    """Tests for _bump_level."""

    def test_major_bump(self):
        """Detect a major version bump."""
        assert _bump_level("1.0.0", "2.0.0") == "major"

    def test_minor_bump(self):
        """Detect a minor version bump."""
        assert _bump_level("1.2.0", "1.3.0") == "minor"

    def test_patch_bump(self):
        """Detect a patch version bump."""
        assert _bump_level("1.2.3", "1.2.4") == "patch"

    def test_no_change(self):
        """Same version returns None."""
        assert _bump_level("1.2.3", "1.2.3") is None

    def test_major_bump_from_zero(self):
        """0.x to 1.x is a major bump."""
        assert _bump_level("0.9.0", "1.0.0") == "major"

    def test_minor_bump_pre_1(self):
        """Minor bump within 0.x range."""
        assert _bump_level("0.1.0", "0.2.0") == "minor"

    def test_patch_bump_pre_1(self):
        """Patch bump within 0.x range."""
        assert _bump_level("0.1.0", "0.1.1") == "patch"

    def test_invalid_old_returns_none(self):
        """Invalid old version returns None."""
        assert _bump_level("invalid", "1.0.0") is None

    def test_invalid_new_returns_none(self):
        """Invalid new version returns None."""
        assert _bump_level("1.0.0", "invalid") is None

    def test_major_bump_resets_minor_and_patch(self):
        """Major bump with lower minor/patch is still major."""
        assert _bump_level("1.9.9", "2.0.0") == "major"

    def test_minor_bump_resets_patch(self):
        """Minor bump with lower patch is still minor."""
        assert _bump_level("1.2.9", "1.3.0") == "minor"


#: A representative griffe breakage line naming a removed symbol.
_BREAK = "chumicro_timing.Timer.start: parameter 'period' was removed"


def _insufficient_bump_result(monkeypatch, griffe_output=_BREAK):
    """Run ``_check_one_package`` under a breakage + under-bump scenario.

    Stubs the repo-layout lookups and the ``griffe check`` subprocess so
    the case is: last stable tag ``0.1.0``, current VERSION ``0.1.1``
    (a patch bump — insufficient for a break), griffe exits non-zero
    reporting a removed parameter.  Returns ``(ok, lines)``.
    """
    monkeypatch.setattr(
        check_api, "release_tags",
        lambda basename, stable_only=False: ["chumicro-timing-v0.1.0"],
    )
    monkeypatch.setattr(
        check_api, "find_package_dir",
        lambda package_root: Path("chumicro_timing"),
    )
    monkeypatch.setattr(
        check_api, "read_version",
        lambda package_root: "0.1.1",
    )
    monkeypatch.setattr(
        check_api.subprocess, "run",
        lambda *args, **kwargs: types.SimpleNamespace(
            returncode=1, stdout=griffe_output, stderr="",
        ),
    )
    return check_api._check_one_package("libraries", "timing")


class TestBreakageGate:
    """Pins the PUBLISHED-gated breakage-vs-bump reporting (Decisions 0020/0092)."""

    def test_warns_and_passes_before_publication(self, monkeypatch):
        """Pre-publication: an under-bumped break WARNs but still passes."""
        assert check_api.PUBLISHED is False
        ok, lines = _insufficient_bump_result(monkeypatch)
        text = "\n".join(lines)
        assert ok is True
        assert "WARNING:" in text
        assert "FAIL:" not in text
        # Names the break and the bump publication would require.
        assert _BREAK in text
        assert "minor bump" in text

    def test_hard_fails_when_published(self, monkeypatch):
        """Flipping PUBLISHED restores Decision 0020's hard fail."""
        monkeypatch.setattr(check_api, "PUBLISHED", True)
        ok, lines = _insufficient_bump_result(monkeypatch)
        text = "\n".join(lines)
        assert ok is False
        assert "FAIL:" in text
        assert "WARNING:" not in text
        assert _BREAK in text
