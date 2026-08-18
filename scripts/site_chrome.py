"""Chrome shared by the two hand-built pages on the site.

The hub at the host root and the documentation landing page under
``/ChuMicro/`` are generated separately, and a reader moves between
them in one click.  The navigation and the artwork live here so the
two cannot drift into looking like different projects.

The per-package documentation sites are themed by Zensical and carry
their own navigation, so they are not involved.
"""

from __future__ import annotations

from string import Template

from shared import TEMPLATES_DIR
from site_host import host_url

#: Where published images live, relative to the site root.  A folder
#: here can never be named after a project repository, which would
#: claim an address GitHub already serves a site at.
ASSETS_PREFIX = "assets"


def assets_url() -> str:
    """Return the base URL for published images, with no trailing slash."""
    return f"{host_url()}/{ASSETS_PREFIX}"


def render_topbar() -> str:
    """Return the shared navigation bar, styles included.

    The markup carries its own ``<style>`` block rather than relying on
    each page's stylesheet, so adding the bar to a page is one
    substitution and the two copies cannot fall out of step.  It reads
    the colour variables both pages define.

    Returns:
        HTML for the navigation bar.
    """
    template_text = (TEMPLATES_DIR / "topbar.html.template").read_text()
    return Template(template_text).substitute(
        host=host_url(),
        assets=assets_url(),
    )
