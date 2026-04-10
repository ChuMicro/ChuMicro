"""Tests for check_api.py — version parsing and bump-level detection."""

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

