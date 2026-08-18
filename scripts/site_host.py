"""The canonical host every generated URL is written against.

One module so the landing page, the host-root site, the sitemaps, the
IndexNow ping, and the CNAME file cannot disagree about where the
documentation lives.  Moving to a different host is an edit here plus
a sweep of the static files that spell the address out in prose.

GitHub Pages serves an account's site at ``<account>.github.io`` until
a custom domain is configured, and redirects that address to the
custom domain afterwards.  ``CUSTOM_DOMAIN`` is what configures it:
the host-root site publishes a ``CNAME`` file naming the domain, which
is the file GitHub reads.

Set ``CUSTOM_DOMAIN`` only once the domain's DNS records already
resolve to GitHub's servers.  GitHub starts redirecting as soon as it
accepts the domain, so a ``CNAME`` that lands first points every
visitor at a name that does not answer yet.
"""

from __future__ import annotations

#: The account's GitHub Pages host, used until a custom domain answers.
PAGES_HOST = "chumicro.github.io"

#: The custom domain, or an empty string while none is configured.
CUSTOM_DOMAIN = "chumicro.com"

#: The repository whose project site holds the library documentation.
PROJECT_PATH = "ChuMicro"


def host_name() -> str:
    """Return the bare hostname the site publishes under."""
    return CUSTOM_DOMAIN or PAGES_HOST


def host_url() -> str:
    """Return the host's root URL, with no trailing slash."""
    return f"https://{host_name()}"


def site_root() -> str:
    """Return the documentation site's root URL, with no trailing slash."""
    return f"{host_url()}/{PROJECT_PATH}"
