"""Tests for generate_landing_page.py — HTML landing page generation."""

from generate_landing_page import (
    _discover_packages,
    _library_card,
    _render_section,
    generate,
)


def _sample_library() -> dict:
    """Return a library-shaped metadata dict for card tests."""
    return {
        "name": "timing",
        "package": "chumicro-timing",
        "description": "Millisecond tick helpers",
        "has_testing": False,
        "source_subdir": "libraries",
    }


def _sample_workbench() -> dict:
    """Return a workbench-shaped metadata dict for card tests."""
    return {
        "name": "deploy",
        "package": "chumicro-deploy",
        "description": "Host-side device transports",
        "has_testing": False,
        "source_subdir": "workbench",
    }


class TestLibraryCard:
    """Tests for _library_card."""

    def test_basic_card(self):
        """Card contains the library name, description, and libraries source link."""
        html = _library_card(_sample_library())
        assert "chumicro-timing" in html
        assert "Millisecond tick helpers" in html
        assert 'href="timing/stable/"' in html
        assert "tree/main/libraries/timing" in html

    def test_card_with_testing(self):
        """Card with testing page includes the testing link."""
        library = _sample_library()
        library["has_testing"] = True
        html = _library_card(library)
        assert "Testing" in html
        assert "testing/" in html

    def test_card_without_testing(self):
        """Card without testing page omits the testing link."""
        html = _library_card(_sample_library())
        assert 'href="timing/stable/testing/"' not in html

    def test_workbench_card_source_link(self):
        """Workbench cards point the Source link at ``workbench/<name>``."""
        html = _library_card(_sample_workbench())
        assert "tree/main/workbench/deploy" in html
        assert "tree/main/libraries/deploy" not in html


class TestRenderSection:
    """Tests for _render_section."""

    def test_empty_cards_returns_empty_string(self):
        """A section with no cards renders as the empty string."""
        assert _render_section("Libraries", "desc", []) == ""

    def test_non_empty_section_includes_heading_and_description(self):
        """A populated section includes its heading and description."""
        html = _render_section(
            "Libraries", "Cross-runtime libraries.", [_sample_library()],
        )
        assert 'class="section-heading"' in html
        assert "Libraries</h2>" in html
        assert "Cross-runtime libraries." in html
        assert "chumicro-timing" in html


class TestDiscoverPackages:
    """Tests for _discover_packages."""

    def test_returns_two_lists(self):
        """Discovery returns a (libraries, workbench) tuple of lists."""
        libraries, workbench = _discover_packages()
        assert isinstance(libraries, list)
        assert isinstance(workbench, list)

    def test_libraries_include_timing(self):
        """Known device libraries are in the libraries list."""
        libraries, _ = _discover_packages()
        names = {library["name"] for library in libraries}
        assert "timing" in names

    def test_each_entry_has_source_subdir(self):
        """Every metadata dict carries the source subdirectory."""
        libraries, workbench = _discover_packages()
        for entry in libraries:
            assert entry["source_subdir"] == "libraries"
        for entry in workbench:
            assert entry["source_subdir"] == "workbench"


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

    def test_libraries_and_workbench_are_separate_sections(self):
        """Libraries and workbench render in distinct ``<section>`` blocks."""
        html = generate()
        # Both headings present.
        assert ">Libraries</h2>" in html
        assert ">Workbench</h2>" in html
        # Workbench section carries the deploy package card.
        assert "chumicro-deploy" in html
        # Workbench source link points at workbench/, not libraries/.
        assert "tree/main/workbench/deploy" in html

    def test_libraries_section_precedes_workbench(self):
        """Libraries render before Workbench on the page."""
        html = generate()
        libraries_position = html.index(">Libraries</h2>")
        workbench_position = html.index(">Workbench</h2>")
        assert libraries_position < workbench_position
