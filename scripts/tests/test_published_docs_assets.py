"""Every image in a published docs tree has to resolve once published.

A repo-relative path like ``../../support/docs/chumicro_tip.png``
renders on GitHub, where the reader is browsing the repository, and
404s on the documentation site, where ``support/`` is not published.
Thirteen contributing pages shipped a broken image that way, and the
only thing that noticed was a person looking at the page.
"""

import re
from pathlib import Path

import pytest
from repo_layout import ROOT

#: Markdown trees that publish to the documentation site.
PUBLISHED_DOCS = (
    ROOT / "docs",
    *sorted(ROOT.glob("libraries/*/docs")),
    *sorted(ROOT.glob("workbench/*/docs")),
)

#: ``<img src="...">`` and ``![alt](...)`` in one pass.
IMAGE_PATTERN = re.compile(r'<img[^>]*src="([^"]+)"|!\[[^\]]*\]\(([^)]+)\)')


def _image_sources() -> list[tuple[Path, str]]:
    """Return every image reference in the published docs trees."""
    found = []
    for tree in PUBLISHED_DOCS:
        if not tree.is_dir():
            continue
        for page in sorted(tree.rglob("*.md")):
            for match in IMAGE_PATTERN.finditer(page.read_text()):
                source = match.group(1) or match.group(2)
                found.append((page, source.strip()))
    return found


def test_the_scan_finds_the_pages_it_is_meant_to_guard():
    """A pattern that matched nothing would pass every assertion below."""
    assert len(_image_sources()) > 0


@pytest.mark.parametrize(
    ("page", "source"),
    _image_sources(),
    ids=lambda value: value.name if isinstance(value, Path) else value,
)
def test_image_resolves_once_published(page: Path, source: str):
    """An image reaches outside its own docs tree only as an absolute URL.

    Anything else is resolved relative to the published page, and a
    path climbing out of the tree lands on an address the site does
    not serve.
    """
    if source.startswith(("http://", "https://", "data:", "/")):
        return

    resolved = (page.parent / source).resolve()
    tree = next(t for t in PUBLISHED_DOCS if t in page.parents or t == page.parent)
    assert tree in resolved.parents, (
        f"{page.relative_to(ROOT)} points at {source}, which resolves outside "
        f"{tree.relative_to(ROOT)} and will 404 on the documentation site.  "
        "Use an absolute https URL for artwork published at the site root."
    )
