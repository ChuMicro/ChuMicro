"""Tests for generate_landing_page.py — HTML landing page generation."""

from generate_landing_page import _library_card, _strip_markdown_links, generate


class TestStripMarkdownLinks:
    """Tests for _strip_markdown_links."""

    def test_simple_link(self):
        """Strips a simple markdown link."""
        assert _strip_markdown_links("[text](url)") == "text"

    def test_multiple_links(self):
        """Strips multiple links in one string."""
        result = _strip_markdown_links("[a](url1) and [b](url2)")
        assert result == "a and b"

    def test_no_links(self):
        """Plain text is returned unchanged."""
        assert _strip_markdown_links("plain text") == "plain text"

    def test_nested_brackets(self):
        """Handles text with brackets that aren't links."""
        assert _strip_markdown_links("no link here") == "no link here"

    def test_link_with_complex_url(self):
        """Handles URLs with special characters."""
        result = _strip_markdown_links("[text](https://example.com/path?q=1&r=2)")
        assert result == "text"


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

