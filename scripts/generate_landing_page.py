"""Generate the docs landing page (index.html) for the gh-pages branch.

Auto-discovers all libraries under ``libraries/`` and produces an HTML
landing page with cards, install snippets, and release channel information.
The generated page follows the dark-mode design used across the site.

Usage (from repository root)::

    python scripts/generate_landing_page.py > /tmp/index.html

The docs-deploy workflow calls this to regenerate the page on every push.
"""

from __future__ import annotations

import re
from string import Template

from shared import TEMPLATES_DIR
from workspace import ROOT, read_pyproject_description


def _discover_libraries() -> list[dict]:
    """Return metadata dicts for each library with a mkdocs.yml."""
    libraries_dir = ROOT / "libraries"
    if not libraries_dir.is_dir():
        return []

    libraries = []
    for child in sorted(libraries_dir.iterdir()):
        if not child.is_dir() or not (child / "mkdocs.yml").exists():
            continue
        name = child.name
        description = read_pyproject_description(child)

        mkdocs_text = (child / "mkdocs.yml").read_text()
        has_testing = "testing.md" in mkdocs_text

        libraries.append({
            "name": name,
            "package": f"chumicro-{name}",
            "description": description,
            "has_testing": has_testing,
        })
    return libraries


def _library_card(library: dict) -> str:
    """Return the HTML for a single library card.

    Links are ordered: Guide → API → Testing (if present) → Experimental → Source.
    The testing link is only shown for libraries whose ``mkdocs.yml``
    references a ``testing.md`` page.

    Args:
        library: Metadata dict with ``name``, ``package``, ``description``,
            and ``has_testing`` keys.
    """
    name = library["name"]
    package = library["package"]
    description = library["description"]

    links = [
        f'<a href="{name}/stable/guide/">Guide</a>',
        f'<a href="{name}/stable/api/">API</a>',
    ]
    if library["has_testing"]:
        links.append(f'<a href="{name}/stable/testing/">Testing</a>')
    links.append(f'<a href="{name}/experimental/">Experimental</a>')
    links.append(
        f'<a href="https://github.com/ChuMicro/ChuMicro/tree/main/libraries/{name}">Source</a>'
    )

    separator = '\n          <span class="sep">&middot;</span>\n          '
    card_links = separator.join(links)

    return f"""\
      <div class="card">
        <h2><a href="{name}/stable/">{package}</a></h2>
        <p>{description}</p>
        <div class="card-links">
          {card_links}
        </div>
      </div>"""


def generate() -> str:
    """Return the full landing page HTML."""
    libraries = _discover_libraries()
    cards = "\n\n".join(_library_card(library) for library in libraries)

    # Use the first library name for install examples
    first_package = libraries[0]["package"] if libraries else "chumicro-timing"
    first_import = re.sub(r"-", "_", first_package)

    template_text = (TEMPLATES_DIR / "landing_page.html.template").read_text()
    return Template(template_text).substitute(
        cards=cards,
        first_package=first_package,
        first_import=first_import,
    )


if __name__ == "__main__":
    print(generate(), end="")
