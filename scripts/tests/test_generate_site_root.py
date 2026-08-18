"""Tests for generate_site_root.py, the host-root site.

The root site exists for three things a project path cannot do:
serve robots.txt, hold a host-wide ownership token, and answer the
IndexNow key lookup.  Each of those is a file at an exact address, so
the tests here assert addresses and contents rather than layout.

Package-touching tests run against a synthetic workspace under
``tmp_path``, the same shape ``test_generate_landing_page.py`` uses,
so renaming a real package cannot silently break or pass them.
"""

from pathlib import Path
from xml.etree import ElementTree

import generate_landing_page
import generate_site_root
import pytest
from generate_site_root import (
    HOST,
    PAGES_SITEMAP,
    PROJECTS,
    _render_package_links,
    _structured_data,
    _verification_meta,
    build,
    root_index_html,
    root_llms_txt,
    root_pages_sitemap,
    root_robots_txt,
    root_sitemap,
)


@pytest.fixture
def synthetic_packages(tmp_path: Path, monkeypatch):
    """Build synthetic library + workbench packages and point discovery at them."""
    layout = [
        ("libraries", "lib_a", "Synthetic library A description."),
        ("workbench", "tool_x", "Synthetic workbench tool description."),
    ]
    package_dirs: list[Path] = []
    for parent, name, description in layout:
        package_dir = tmp_path / parent / name
        package_dir.mkdir(parents=True)
        (package_dir / "pyproject.toml").write_text(
            "[project]\n"
            f'name = "chumicro-{name}"\n'
            f'description = "{description}"\n',
        )
        (package_dir / "mkdocs.yml").write_text("nav:\n  - Home: index.md\n")
        package_dirs.append(package_dir)

    monkeypatch.setattr(
        generate_landing_page, "discover_doc_dirs", lambda: package_dirs,
    )
    return package_dirs


@pytest.fixture
def verification_dir(tmp_path: Path, monkeypatch):
    """Point the generator at a synthetic site-verification directory."""
    directory = tmp_path / "site-verification"
    directory.mkdir()
    (directory / "google-meta-tag.txt").write_text("GOOGLE_TOKEN\n")
    (directory / "bing-meta-tag.txt").write_text("BING_TOKEN\n")
    (directory / "BingSiteAuth.xml").write_text("<users><user>BING_TOKEN</user></users>\n")
    (directory / "googletoken.html").write_text("google-site-verification: googletoken.html\n")
    (directory / "indexnow-key.txt").write_text("abc123\n")
    monkeypatch.setattr(generate_site_root, "VERIFICATION_DIR", directory)
    return directory


def test_robots_names_the_sitemap_index():
    """The index reaches every child, so naming them too would repeat it."""
    robots = root_robots_txt()
    assert f"Sitemap: {HOST}/sitemap.xml" in robots
    assert robots.count("Sitemap:") == 1
    assert "Allow: /" in robots


def test_sitemap_is_an_index_over_every_sitemap_on_the_host():
    """One submission at the root has to reach every project below it."""
    sitemap = root_sitemap()
    assert "<sitemapindex" in sitemap
    assert f"<loc>{HOST}/{PAGES_SITEMAP}</loc>" in sitemap
    for project in PROJECTS:
        assert f"<loc>{HOST}/{project['path']}/sitemap.xml</loc>" in sitemap


def test_sitemap_index_parses_as_xml():
    """A malformed index would fail silently in a webmaster console."""
    root = ElementTree.fromstring(root_sitemap())
    assert root.tag.endswith("sitemapindex")
    assert len(root) == 1 + len(PROJECTS)


def test_pages_sitemap_carries_the_hub_url():
    """The index lists sitemaps, so the hub's own URL needs a file of its own."""
    pages = root_pages_sitemap()
    assert pages.count("<loc>") == 1
    assert f"<loc>{HOST}/</loc>" in pages


def test_index_canonicalizes_to_the_host_root(synthetic_packages, verification_dir):
    """A hub that canonicalized elsewhere would hand away the strongest URL."""
    html = root_index_html()
    assert f'<link rel="canonical" href="{HOST}/">' in html
    assert f'<meta property="og:url" content="{HOST}/">' in html


def test_index_carries_both_verification_tags(synthetic_packages, verification_dir):
    """Verifying the root property covers every path below it."""
    html = root_index_html()
    assert '<meta name="google-site-verification" content="GOOGLE_TOKEN">' in html
    assert '<meta name="msvalidate.01" content="BING_TOKEN">' in html


def test_verification_meta_is_empty_without_tokens(tmp_path, monkeypatch):
    """A workspace without tokens builds a page rather than failing."""
    monkeypatch.setattr(generate_site_root, "VERIFICATION_DIR", tmp_path / "absent")
    assert _verification_meta() == ""


def test_package_links_point_at_stable_documentation(synthetic_packages):
    """The hub links straight into the pages that answer a search."""
    links = _render_package_links()
    assert f'href="{HOST}/ChuMicro/lib_a/stable/"' in links
    assert f'href="{HOST}/ChuMicro/tool_x/stable/"' in links
    assert "Synthetic library A description." in links


def test_structured_data_names_the_projects_below_the_root():
    """``hasPart`` is what ties /ChuMicro/ to this page's publisher."""
    block = _structured_data()
    assert '"@type": "Organization"' in block
    assert f'"{HOST}/ChuMicro/"' in block
    assert block.startswith('  <script type="application/ld+json">')


def test_llms_hands_off_to_each_project_index():
    """The root copy stays short: the package list lives per project."""
    llms = root_llms_txt()
    assert f"{HOST}/ChuMicro/llms.txt" in llms
    for project in PROJECTS:
        assert f"{HOST}/{project['path']}/" in llms


def test_build_writes_the_key_file_at_the_host_root(
    tmp_path, synthetic_packages, verification_dir,
):
    """IndexNow authorizes a whole host when the key answers at its root."""
    destination = tmp_path / "site"
    written = build(destination)

    assert "abc123.txt" in written
    assert (destination / "abc123.txt").read_text() == "abc123"


def test_build_copies_the_files_engines_fetch_verbatim(
    tmp_path, synthetic_packages, verification_dir,
):
    """Both engines offer a file upload as well as a meta tag."""
    destination = tmp_path / "site"
    written = build(destination)

    assert "BingSiteAuth.xml" in written
    assert "googletoken.html" in written
    assert (destination / "BingSiteAuth.xml").read_text().strip().endswith("</users>")


def test_build_writes_every_root_file(tmp_path, synthetic_packages, verification_dir):
    """The four generated files plus whatever verification supplies."""
    destination = tmp_path / "site"
    written = build(destination)

    assert {
        "index.html", "robots.txt", "sitemap.xml", PAGES_SITEMAP, "llms.txt",
    } <= set(written)


def test_no_project_path_collides_with_a_generated_file():
    """A folder named after a project repository would shadow its site."""
    generated = {"index.html", "robots.txt", "sitemap.xml", PAGES_SITEMAP, "llms.txt"}
    for project in PROJECTS:
        assert project["path"] not in generated


def test_build_writes_no_cname_without_a_custom_domain(
    tmp_path, synthetic_packages, verification_dir, monkeypatch,
):
    """A CNAME naming nothing would take the site off its github.io address."""
    monkeypatch.setattr(generate_site_root, "CUSTOM_DOMAIN", "")
    assert "CNAME" not in build(tmp_path / "site")


def test_build_writes_the_cname_for_a_custom_domain(
    tmp_path, synthetic_packages, verification_dir, monkeypatch,
):
    """The publish rebuilds the tree, so the generator has to own this file.

    A CNAME added to the site repository by hand, or written there by
    GitHub when someone sets the domain in the web interface, would be
    deleted by the next publish and take the domain down with it.
    """
    monkeypatch.setattr(generate_site_root, "CUSTOM_DOMAIN", "example.test")
    destination = tmp_path / "site"

    assert "CNAME" in build(destination)
    assert (destination / "CNAME").read_text() == "example.test\n"
