"""Tests for site_host.py, the one place the canonical host is named.

A wrong answer here is written into every canonical tag, sitemap
entry, and structured-data block on the site, so the tests pin the
shape of each URL rather than trusting the constants to be read
correctly at each call site.
"""

import pytest
import site_host


@pytest.fixture
def custom_domain(monkeypatch):
    """Configure a custom domain for the duration of one test."""
    monkeypatch.setattr(site_host, "CUSTOM_DOMAIN", "example.test")


def test_pages_host_is_used_until_a_domain_is_configured(monkeypatch):
    """An unset custom domain leaves the site on its github.io address."""
    monkeypatch.setattr(site_host, "CUSTOM_DOMAIN", "")
    assert site_host.host_name() == "chumicro.github.io"
    assert site_host.host_url() == "https://chumicro.github.io"


def test_custom_domain_takes_over_every_url(custom_domain):
    """Setting the domain has to move the project root along with the host."""
    assert site_host.host_name() == "example.test"
    assert site_host.host_url() == "https://example.test"
    assert site_host.site_root() == "https://example.test/ChuMicro"


def test_urls_carry_no_trailing_slash():
    """Callers append their own path, so a trailing slash would double up."""
    assert not site_host.host_url().endswith("/")
    assert not site_host.site_root().endswith("/")


def test_site_root_sits_below_the_host():
    """The project site is a path on the host, never a host of its own."""
    assert site_host.site_root().startswith(f"{site_host.host_url()}/")


def test_assets_url_follows_the_host(custom_domain):
    """Images publish on whatever host the site is currently using."""
    from site_chrome import assets_url

    assert assets_url() == "https://example.test/assets"


def test_topbar_links_to_the_source_and_the_docs(custom_domain):
    """The bar is why GitHub is reachable without scrolling."""
    from site_chrome import render_topbar

    bar = render_topbar()
    assert 'href="https://github.com/ChuMicro"' in bar
    assert 'href="https://example.test/ChuMicro/"' in bar
    assert 'href="https://example.test/ChuMicro/guides/"' in bar


def test_both_pages_carry_the_same_bar(custom_domain, monkeypatch):
    """One source for the bar is what keeps the two pages consistent."""
    import generate_landing_page
    import generate_site_root
    from site_chrome import render_topbar

    bar = render_topbar()
    monkeypatch.setattr(generate_landing_page, "discover_doc_dirs", list)
    assert bar in generate_site_root.root_index_html()
    assert bar in generate_landing_page.generate()
