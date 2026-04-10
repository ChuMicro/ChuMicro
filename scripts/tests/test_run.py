"""Tests for run.py — CLI filter parsing."""

import pytest
from run import _parse_library_filters


class TestParseLibraryFilters:
    """Tests for _parse_library_filters."""

    def test_simple_library_test(self):
        """Parse 'library/test' format."""
        result = _parse_library_filters("timing/test_heartbeat")
        assert result == {"timing": [(None, "test_heartbeat")]}

    def test_library_file_test(self):
        """Parse 'library/file/test' format."""
        result = _parse_library_filters("timing/test_ticks/ticks_add")
        assert result == {"timing": [("test_ticks", "ticks_add")]}

    def test_comma_separated(self):
        """Parse comma-separated multi-library filters."""
        result = _parse_library_filters("timing/ticks_diff,runner/task_handle")
        assert "timing" in result
        assert "runner" in result
        assert result["timing"] == [(None, "ticks_diff")]
        assert result["runner"] == [(None, "task_handle")]

    def test_multiple_filters_same_library(self):
        """Multiple filters for the same library are grouped."""
        result = _parse_library_filters("timing/test_a,timing/test_b")
        assert result == {"timing": [(None, "test_a"), (None, "test_b")]}

    def test_mixed_scoped_and_file(self):
        """Mix of library/test and library/file/test in one expression."""
        result = _parse_library_filters("timing/ticks_add,timing/test_ticks/ticks_diff")
        assert result == {
            "timing": [(None, "ticks_add"), ("test_ticks", "ticks_diff")],
        }

    def test_no_library_prefix_fails(self):
        """Entry without a slash causes SystemExit."""
        with pytest.raises(SystemExit):
            _parse_library_filters("just_a_test_name")

    def test_too_many_slashes_fails(self):
        """Entry with more than 3 parts causes SystemExit."""
        with pytest.raises(SystemExit):
            _parse_library_filters("a/b/c/d")

    def test_whitespace_handling(self):
        """Whitespace around entries is stripped."""
        result = _parse_library_filters(" timing/test_a , runner/test_b ")
        assert "timing" in result
        assert "runner" in result

    def test_empty_entries_ignored(self):
        """Empty entries from extra commas are ignored."""
        result = _parse_library_filters("timing/test_a,,runner/test_b,")
        assert len(result) == 2

