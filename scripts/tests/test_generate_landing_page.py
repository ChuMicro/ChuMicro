"""Tests for generate_landing_page.py — HTML landing page generation."""

from generate_landing_page import _library_card, _read_description, generate
from workspace import ROOT


class TestReadDescription:
    """Tests for _read_description."""

    def test_reads_from_pyproject(self):
        """Reads the description field from a real pyproject.toml."""
        pyproject_file = ROOT / "libraries" / "timing" / "pyproject.toml"
        description = _read_description(pyproject_file)
        assert description
        assert "**" not in description

    def test_returns_empty_for_missing_field(self, tmp_path):
        """Returns empty string when description is absent."""
        toml_file = tmp_path / "pyproject.toml"
        toml_file.write_text("[project]\nname = 'test'\n")
        assert _read_description(toml_file) == ""


class TestLibraryCard:
    """Tests for _library_card."""

    def test_basic_card(self):
        """Card contains the library name and description."""
        library = {
            "name": "timing",
            "package": "chumicro-timing",
            "description": "Millisecond tick helpers",
            "has_testing": False,
        }
        html = _library_card(library)
        assert "chumicro-timing" in html
        assert "Millisecond tick helpers" in html
        assert 'href="timing/stable/"' in html

    def test_card_with_testing(self):
        """Card with testing page includes the testing link."""
        library = {
            "name": "timing",
            "package": "chumicro-timing",
            "description": "Test",
            "has_testing": True,
        }
        html = _library_card(library)
        assert "Testing" in html
        assert "testing/" in html

    def test_card_without_testing(self):
        """Card without testing page omits the testing link."""
        library = {
            "name": "timing",
            "package": "chumicro-timing",
            "description": "Test",
            "has_testing": False,
        }
        html = _library_card(library)
        # Should not contain the testing-specific href.
        assert 'href="timing/stable/testing/"' not in html


class TestGenerate:
    """Tests for the full page generation (uses real workspace)."""

    def test_returns_html(self):
        """Generated page is valid HTML."""
        html = generate()
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_contains_library_cards(self):
        """Generated page includes library cards."""
        html = generate()
        assert "chumicro-timing" in html
        assert "chumicro-runner" in html

    def test_contains_install_instructions(self):
        """Generated page includes install instructions for all platforms."""
        html = generate()
        assert "pip install" in html
        assert "circup" in html
        assert "mip install" in html

    def test_contains_release_channels(self):
        """Generated page includes release channel information."""
        html = generate()
        assert "Stable" in html
        assert "Experimental" in html
        assert "ChuMicro-Bundle" in html

