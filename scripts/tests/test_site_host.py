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
