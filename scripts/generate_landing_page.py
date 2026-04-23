"""Generate the docs landing page (index.html) for the gh-pages branch.

Auto-discovers publishable packages (``libraries/`` + ``workbench/``)
and produces an HTML landing page with cards, install snippets, and
release channel information.  The page follows the dark-mode design
used across the site.

Libraries (device-side, cross-runtime) and workbench tools (host-only)
render as separate sections so readers can tell at a glance which
packages run on a device versus which run on the host.

Usage (from repository root)::

    python scripts/generate_landing_page.py > /tmp/index.html

The docs-deploy workflow calls this to regenerate the page on every push.
"""

from __future__ import annotations

import re
from pathlib import Path
from string import Template

from shared import TEMPLATES_DIR
from workspace import discover_doc_dirs, read_pyproject_description


def _package_metadata(package_dir: Path) -> dict:
    """Return the dict consumed by :func:`_library_card`.

    The ``source_subdir`` key names the repo folder the GitHub source
    link should point at (``libraries`` for device libraries,
    ``workbench`` for host-only tools).
    """
    name = package_dir.name
    description = read_pyproject_description(package_dir)
    mkdocs_text = (package_dir / "mkdocs.yml").read_text()
    has_testing = "testing.md" in mkdocs_text
    return {
        "name": name,
        "package": f"chumicro-{name}",
        "description": description,
        "has_testing": has_testing,
        "source_subdir": package_dir.parent.name,
    }


def _discover_packages() -> tuple[list[dict], list[dict]]:
    """Return ``(libraries, workbench)`` metadata dict lists.

    Categorization is by parent directory name — ``libraries/`` for
    device libraries, ``workbench/`` for host-only tools.  Any other
    parent (notably ``support/``) is skipped: support packages are
    not published and don't belong on the public landing page.
    """
    libraries: list[dict] = []
    workbench: list[dict] = []
    for package_dir in discover_doc_dirs():
        metadata = _package_metadata(package_dir)
        parent_name = package_dir.parent.name
        if parent_name == "libraries":
            libraries.append(metadata)
        elif parent_name == "workbench":
            workbench.append(metadata)
    return libraries, workbench


def _library_card(library: dict) -> str:
    """Return the HTML for a single package card.

    Links are ordered: Guide → API → Testing (if present) → Experimental → Source.
    The testing link is only shown for packages whose ``mkdocs.yml``
    references a ``testing.md`` page.

    Args:
        library: Metadata dict with ``name``, ``package``, ``description``,
            ``has_testing``, and ``source_subdir`` keys.
    """
    name = library["name"]
    package = library["package"]
    description = library["description"]
    source_subdir = library["source_subdir"]

    links = [
        f'<a href="{name}/stable/guide/">Guide</a>',
        f'<a href="{name}/stable/api/">API</a>',
    ]
    if library["has_testing"]:
        links.append(f'<a href="{name}/stable/testing/">Testing</a>')
    links.append(f'<a href="{name}/experimental/">Experimental</a>')
    links.append(
        f'<a href="https://github.com/ChuMicro/ChuMicro/tree/main/{source_subdir}/{name}">Source</a>'
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


def _render_section(heading: str, description: str, cards: list[dict]) -> str:
    """Return a full ``<section>`` block, or the empty string when empty.

    Callers render one section per category; an empty card list
    produces no markup so the category vanishes from the page when
    nothing has been published yet.
    """
    if not cards:
        return ""
    cards_html = "\n\n".join(_library_card(card) for card in cards)
    return f"""    <section class="section">
      <h2 class="section-heading">{heading}</h2>
      <p class="section-description">{description}</p>
      <div class="libraries">
{cards_html}
      </div>
    </section>"""


def generate() -> str:
    """Return the full landing page HTML."""
    libraries, workbench = _discover_packages()

    library_section = _render_section(
        "Libraries",
        "Cross-runtime Python libraries for CircuitPython, MicroPython, "
        "and CPython.",
        libraries,
    )
    workbench_section = _render_section(
        "Workbench",
        "Host-only CPython tools for deploying, probing, and flashing "
        "devices.",
        workbench,
    )
    sections = "\n\n".join(
        block for block in (library_section, workbench_section) if block
    )

    # Use the first library's package for install examples (libraries
    # are the circup / mip path; workbench is pip-only).  Fall back to
    # a workbench package if the repo somehow has no libraries, then to
    # the historical default so the template never renders an empty
    # placeholder.
    example_source = libraries or workbench
    first_package = (
        example_source[0]["package"] if example_source else "chumicro-timing"
    )
    first_import = re.sub(r"-", "_", first_package)

    template_text = (TEMPLATES_DIR / "landing_page.html.template").read_text()
    return Template(template_text).substitute(
        sections=sections,
        first_package=first_package,
        first_import=first_import,
    )


if __name__ == "__main__":
    print(generate(), end="")
