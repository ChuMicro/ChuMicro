"""Tests for generate_landing_page.py — HTML landing page generation.

The discovery-touching tests run against a synthetic workspace
materialized under ``tmp_path``: the ``synthetic_doc_dirs`` fixture
builds two fake libraries and one fake workbench package and
monkeypatches ``generate_landing_page.discover_doc_dirs`` to return
those paths.  No test reads the real on-disk state of any real
package; renaming or reshuffling production packages cannot
silently break or silently pass these tests.
"""

from pathlib import Path

import generate_landing_page
import pytest
from generate_landing_page import (
    LIBRARY_ORDER,
    SITE_ROOT,
    WORKBENCH_ORDER,
    _curated_sort,
    _discover_packages,
    _library_card,
    _render_section,
    generate,
    generate_llms_txt,
    generate_sitemap,
    site_urls,
)


@pytest.fixture
def synthetic_doc_dirs(tmp_path: Path, monkeypatch):
    """Build synthetic library + workbench packages under ``tmp_path``
    and monkeypatch ``discover_doc_dirs`` to return them.

    Each synthetic package carries a ``pyproject.toml`` (with a
    description) and an ``mkdocs.yml`` so ``_package_metadata`` can
    read both without falling back to the real workspace.
    """
    layout = [
        ("libraries", "lib_a", "Synthetic library A description.", True),
        ("libraries", "lib_b", "Synthetic library B description.", False),
        ("workbench", "tool_x", "Synthetic workbench tool description.", True),
    ]
    package_dirs: list[Path] = []
    for parent, name, description, with_testing in layout:
        package_dir = tmp_path / parent / name
        package_dir.mkdir(parents=True)
        (package_dir / "pyproject.toml").write_text(
            "[project]\n"
            f'name = "chumicro-{name}"\n'
            f'description = "{description}"\n',
        )
        mkdocs_lines = ["nav:\n", "  - Home: index.md\n"]
        if with_testing:
            mkdocs_lines.append("  - Testing: testing.md\n")
        (package_dir / "mkdocs.yml").write_text("".join(mkdocs_lines))
        package_dirs.append(package_dir)

    monkeypatch.setattr(
        generate_landing_page, "discover_doc_dirs", lambda: package_dirs,
    )
    # The URL builders read the real guides nav unless pointed elsewhere.
    # These tests describe packages, so point them at nothing.
    monkeypatch.setattr(
        generate_landing_page, "GUIDES_CONFIG", tmp_path / "no-guides.yml",
    )

    return package_dirs


def _sample_library() -> dict:
    """Return a library-shaped metadata dict for card tests."""
    return {
        "name": "lib_a",
        "package": "chumicro-lib_a",
        "description": "Synthetic library A description.",
        "has_testing": False,
        "source_subdir": "libraries",
    }


def _sample_workbench() -> dict:
    """Return a workbench-shaped metadata dict for card tests."""
    return {
        "name": "tool_x",
        "package": "chumicro-tool_x",
        "description": "Synthetic workbench tool description.",
        "has_testing": False,
        "source_subdir": "workbench",
    }


class TestLibraryCard:
    """Tests for _library_card."""

    def test_basic_card(self):
        """Card contains the library name, description, and libraries source link."""
        html = _library_card(_sample_library())
        assert "chumicro-lib_a" in html
        assert "Synthetic library A description." in html
        assert 'href="lib_a/stable/"' in html
        assert "tree/main/libraries/lib_a" in html

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
        assert 'href="lib_a/stable/testing/"' not in html

    def test_workbench_card_source_link(self):
        """Workbench cards point the Source link at ``workbench/<name>``."""
        html = _library_card(_sample_workbench())
        assert "tree/main/workbench/tool_x" in html
        assert "tree/main/libraries/tool_x" not in html


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
        assert "chumicro-lib_a" in html


class TestDiscoverPackages:
    """Tests for _discover_packages against synthetic doc dirs."""

    def test_returns_two_lists(self, synthetic_doc_dirs):
        """Discovery returns a (libraries, workbench) tuple of lists."""
        libraries, workbench = _discover_packages()
        assert isinstance(libraries, list)
        assert isinstance(workbench, list)

    def test_categorizes_by_parent_directory(self, synthetic_doc_dirs):
        """Libraries route to the libraries list, workbench to workbench."""
        libraries, workbench = _discover_packages()
        library_names = {entry["name"] for entry in libraries}
        workbench_names = {entry["name"] for entry in workbench}
        assert library_names == {"lib_a", "lib_b"}
        assert workbench_names == {"tool_x"}

    def test_each_entry_has_source_subdir(self, synthetic_doc_dirs):
        """Every metadata dict carries the source subdirectory."""
        libraries, workbench = _discover_packages()
        for entry in libraries:
            assert entry["source_subdir"] == "libraries"
        for entry in workbench:
            assert entry["source_subdir"] == "workbench"

    def test_has_testing_reflects_mkdocs_nav(self, synthetic_doc_dirs):
        """``has_testing`` is True iff mkdocs.yml mentions ``testing.md``."""
        libraries, workbench = _discover_packages()
        by_name = {
            entry["name"]: entry for entry in (*libraries, *workbench)
        }
        assert by_name["lib_a"]["has_testing"] is True
        assert by_name["lib_b"]["has_testing"] is False
        assert by_name["tool_x"]["has_testing"] is True

    def test_parked_library_not_advertised(self, synthetic_doc_dirs):
        """A parked library drops off the landing page (Decision 0107): it
        ships to neither PyPI nor the bundle, so advertising it would point
        readers at an install that doesn't exist yet."""
        (synthetic_doc_dirs[0] / "PARKED").write_text("zero adopters\n")
        libraries, _workbench = _discover_packages()
        library_names = {entry["name"] for entry in libraries}
        assert "lib_a" not in library_names
        assert "lib_b" in library_names


class TestCuratedSort:
    """Tests for the curated landing-page card order."""

    def test_curated_names_lead_unknown_names_follow_alphabetically(self):
        """Curated names keep tuple order; unlisted names sort after them."""
        cards = [
            {"name": "zeta"},
            {"name": "compat"},
            {"name": "timing"},
            {"name": "alpha"},
        ]
        ordered = _curated_sort(cards, ("timing", "compat"))
        assert [card["name"] for card in ordered] == [
            "timing", "compat", "alpha", "zeta",
        ]

    def test_shipped_orders_lead_with_the_readme_front_doors(self):
        """The first card (and install snippet) is timing for libraries and
        workspace for workbench, matching the root README's teaching order."""
        assert LIBRARY_ORDER[0] == "timing"
        assert WORKBENCH_ORDER[0] == "workspace"


class TestGenerate:
    """Tests for the full page generation against synthetic doc dirs."""

    def test_returns_html(self, synthetic_doc_dirs):
        """Generated page is valid HTML."""
        html = generate()
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_contains_synthetic_library_cards(self, synthetic_doc_dirs):
        """Generated page includes a card for every synthetic library."""
        html = generate()
        assert "chumicro-lib_a" in html
        assert "chumicro-lib_b" in html

    def test_contains_install_instructions(self, synthetic_doc_dirs):
        """Generated page includes install instructions for all platforms."""
        html = generate()
        assert "pip install" in html
        assert "circup" in html
        assert "mip install" in html

    def test_contains_release_channels(self, synthetic_doc_dirs):
        """Generated page includes release channel information."""
        html = generate()
        assert "Stable" in html
        assert "Experimental" in html
        assert "ChuMicro-Bundle" in html

    def test_libraries_and_workbench_are_separate_sections(
        self, synthetic_doc_dirs,
    ):
        """Libraries and workbench render in distinct ``<section>`` blocks."""
        html = generate()
        assert ">Libraries</h2>" in html
        assert ">Workbench</h2>" in html
        # Workbench section carries the synthetic workbench card.
        assert "chumicro-tool_x" in html
        # Workbench source link points at workbench/, not libraries/.
        assert "tree/main/workbench/tool_x" in html

    def test_libraries_section_precedes_workbench(self, synthetic_doc_dirs):
        """Libraries render before Workbench on the page."""
        html = generate()
        libraries_position = html.index(">Libraries</h2>")
        workbench_position = html.index(">Workbench</h2>")
        assert libraries_position < workbench_position


class TestGenerateSitemap:
    """Tests for generate_sitemap."""

    def test_lists_the_site_root_and_every_package(self, synthetic_doc_dirs):
        sitemap = generate_sitemap()
        assert f"<loc>{SITE_ROOT}/</loc>" in sitemap
        for name in ("lib_a", "lib_b", "tool_x"):
            assert f"<loc>{SITE_ROOT}/{name}/stable/</loc>" in sitemap

    def test_points_at_the_channel_url_not_a_release_number(
        self, synthetic_doc_dirs,
    ):
        """The sitemap advertises the address that survives releases."""
        sitemap = generate_sitemap()
        assert sitemap.count("/stable/") == len(synthetic_doc_dirs)

    def test_parked_library_stays_out(self, synthetic_doc_dirs, monkeypatch):
        monkeypatch.setattr(
            generate_landing_page,
            "is_parked",
            lambda package_dir: package_dir.name == "lib_b",
        )
        sitemap = generate_sitemap()
        assert "lib_a/stable/" in sitemap
        assert "lib_b" not in sitemap

    def test_is_wellformed_xml(self, synthetic_doc_dirs):
        from xml.etree import ElementTree

        root = ElementTree.fromstring(generate_sitemap())
        locations = [
            element.text for element in
            root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
        ]
        assert len(locations) == len(synthetic_doc_dirs) + 1


class TestVerificationMeta:
    """The Search Console token reaches the landing page's head."""

    def test_token_file_becomes_a_meta_tag(
        self, synthetic_doc_dirs, tmp_path, monkeypatch,
    ):
        search_console = tmp_path / "search-console"
        search_console.mkdir()
        (search_console / "google-meta-tag.txt").write_text("token-abc\n")
        monkeypatch.setattr(
            generate_landing_page, "VERIFICATION_DIR", search_console,
        )
        assert (
            '<meta name="google-site-verification" content="token-abc">'
            in generate()
        )

    def test_no_token_leaves_the_head_alone(
        self, synthetic_doc_dirs, tmp_path, monkeypatch,
    ):
        monkeypatch.setattr(
            generate_landing_page, "VERIFICATION_DIR", tmp_path / "absent",
        )
        assert "google-site-verification" not in generate()

    def test_empty_token_file_leaves_the_head_alone(
        self, synthetic_doc_dirs, tmp_path, monkeypatch,
    ):
        search_console = tmp_path / "search-console"
        search_console.mkdir()
        (search_console / "google-meta-tag.txt").write_text("\n")
        monkeypatch.setattr(
            generate_landing_page, "VERIFICATION_DIR", search_console,
        )
        assert "google-site-verification" not in generate()


class TestBingVerificationMeta:
    """Bing's token rides in the same head, under its own tag name."""

    def test_bing_token_becomes_msvalidate(
        self, synthetic_doc_dirs, tmp_path, monkeypatch,
    ):
        verification = tmp_path / "site-verification"
        verification.mkdir()
        (verification / "bing-meta-tag.txt").write_text("bing-token\n")
        monkeypatch.setattr(
            generate_landing_page, "VERIFICATION_DIR", verification,
        )
        assert '<meta name="msvalidate.01" content="bing-token">' in generate()

    def test_both_engines_can_be_verified_at_once(
        self, synthetic_doc_dirs, tmp_path, monkeypatch,
    ):
        verification = tmp_path / "site-verification"
        verification.mkdir()
        (verification / "google-meta-tag.txt").write_text("g-token\n")
        (verification / "bing-meta-tag.txt").write_text("b-token\n")
        monkeypatch.setattr(
            generate_landing_page, "VERIFICATION_DIR", verification,
        )
        html = generate()
        assert 'content="g-token"' in html
        assert 'content="b-token"' in html


class TestGenerateLlmsTxt:
    """Tests for generate_llms_txt."""

    def test_names_every_package_with_its_stable_url(self, synthetic_doc_dirs):
        llms = generate_llms_txt()
        for name in ("lib_a", "lib_b", "tool_x"):
            assert f"{SITE_ROOT}/{name}/stable/" in llms

    def test_separates_libraries_from_host_tools(self, synthetic_doc_dirs):
        llms = generate_llms_txt()
        assert llms.index("## Libraries") < llms.index("## Host tools")
        assert llms.index("lib_a") < llms.index("## Host tools") < llms.index("tool_x")

    def test_opens_with_the_title_and_a_summary_blockquote(self, synthetic_doc_dirs):
        lines = generate_llms_txt().splitlines()
        assert lines[0] == "# ChuMicro"
        assert lines[2].startswith("> ")

    def test_carries_each_package_description(self, synthetic_doc_dirs):
        assert "Synthetic library A description." in generate_llms_txt()


class TestSiteUrls:
    """The sitemap and the IndexNow ping work from one list."""

    def test_site_root_leads(self, synthetic_doc_dirs):
        assert site_urls()[0] == f"{SITE_ROOT}/"

    def test_one_url_per_package(self, synthetic_doc_dirs):
        assert len(site_urls()) == len(synthetic_doc_dirs) + 1

    def test_sitemap_states_the_same_urls(self, synthetic_doc_dirs):
        sitemap = generate_sitemap()
        for url in site_urls():
            assert f"<loc>{url}</loc>" in sitemap


class TestGuidesUrls:
    """The guides site's nav decides which of its pages are advertised."""

    def _config(self, tmp_path, body: str) -> Path:
        config = tmp_path / "mkdocs.yml"
        config.write_text(body)
        return config

    def test_section_root_leads(self, tmp_path, monkeypatch):
        monkeypatch.setattr(generate_landing_page, "GUIDES_CONFIG", self._config(
            tmp_path, "nav:\n  - Guides: index.md\n  - Questions: faq.md\n",
        ))
        assert generate_landing_page.guides_urls()[0] == f"{SITE_ROOT}/guides/"

    def test_index_pages_publish_as_their_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr(generate_landing_page, "GUIDES_CONFIG", self._config(
            tmp_path,
            "nav:\n  - Guides: index.md\n"
            "  - Troubleshooting:\n      - Start: troubleshooting/README.md\n",
        ))
        urls = generate_landing_page.guides_urls()
        assert f"{SITE_ROOT}/guides/troubleshooting/" in urls
        assert f"{SITE_ROOT}/guides/index/" not in urls

    def test_nested_sections_are_flattened(self, tmp_path, monkeypatch):
        monkeypatch.setattr(generate_landing_page, "GUIDES_CONFIG", self._config(
            tmp_path,
            "nav:\n  - Troubleshooting:\n"
            "      - Board: troubleshooting/board-not-found.md\n"
            "      - WiFi: troubleshooting/wifi-wont-connect.md\n",
        ))
        urls = generate_landing_page.guides_urls()
        assert f"{SITE_ROOT}/guides/troubleshooting/board-not-found/" in urls
        assert f"{SITE_ROOT}/guides/troubleshooting/wifi-wont-connect/" in urls

    def test_absent_site_advertises_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            generate_landing_page, "GUIDES_CONFIG", tmp_path / "absent.yml",
        )
        assert generate_landing_page.guides_urls() == []

    def test_sitemap_carries_the_guides(self, synthetic_doc_dirs, tmp_path, monkeypatch):
        monkeypatch.setattr(generate_landing_page, "GUIDES_CONFIG", self._config(
            tmp_path, "nav:\n  - Questions: faq.md\n",
        ))
        assert f"<loc>{SITE_ROOT}/guides/faq/</loc>" in generate_sitemap()
