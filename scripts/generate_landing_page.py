"""Generate the docs landing page (index.html) for the gh-pages branch.

Auto-discovers publishable packages (``libraries/`` + ``workbench/``)
and produces an HTML landing page with cards, install snippets, and
release channel information.  The page follows the dark-mode design
used across the site.

Libraries (device-side, cross-runtime) and workbench tools (host-only)
render as separate sections so readers can tell at a glance which
packages run on a device versus which run on the host.  Install
instructions and the bundle / release-channels block are scoped to
their relevant section: circup / mip and the CircuitPython bundle
only appear next to the library cards, since workbench packages ship
to PyPI only and are never bundled.

Usage (from repository root)::

    python scripts/generate_landing_page.py > /tmp/index.html

The docs-deploy workflow calls this to regenerate the page on every push.
"""

from __future__ import annotations

from pathlib import Path
from string import Template

from repo_layout import discover_doc_dirs, is_parked, read_pyproject_description
from shared import TEMPLATES_DIR

#: Landing-page card order: the root README's library-table order, so the
#: first card and the install snippet lead with the library the README
#: teaches first (timing) instead of the alphabetically-first package.
#: Names missing from the tuple sort after the curated set, alphabetically,
#: so a newly added library appears without editing this file.
LIBRARY_ORDER = (
    "timing", "runner", "wifi", "requests", "http_server", "mqtt",
    "websockets", "sockets", "ntp", "config", "kvstore", "msgpack",
    "compat",
)

#: Workbench card order: the root README's bench-tools order, front door
#: (workspace) first.  Same after-the-curated-set rule as LIBRARY_ORDER.
WORKBENCH_ORDER = ("workspace", "deploy", "repl", "pytest-device", "checks")


def _curated_sort(cards: list[dict], order: tuple[str, ...]) -> list[dict]:
    """Return *cards* sorted by position in *order*, unknown names last.

    Args:
        cards: Package metadata dicts carrying a ``name`` key.
        order: Curated package-name order.

    Returns:
        New list; curated names in tuple order, then the rest alphabetically.
    """
    def sort_key(card: dict) -> tuple[int, str]:
        name = card["name"]
        if name in order:
            return (order.index(name), name)
        return (len(order), name)
    return sorted(cards, key=sort_key)


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

    Categorization is by parent directory name: ``libraries/`` for
    device libraries, ``workbench/`` for host-only tools.  Any other
    parent (notably ``support/``) is skipped: support packages are
    not published and don't belong on the public landing page.

    Parked libraries (Decision 0107) are skipped too: the landing page
    advertises pip-installable, bundle-shipped packages, and a parked
    library ships to neither until it is un-parked.
    """
    libraries: list[dict] = []
    workbench: list[dict] = []
    for package_dir in discover_doc_dirs():
        if is_parked(package_dir):
            continue
        metadata = _package_metadata(package_dir)
        parent_name = package_dir.parent.name
        if parent_name == "libraries":
            libraries.append(metadata)
        elif parent_name == "workbench":
            workbench.append(metadata)
    return (
        _curated_sort(libraries, LIBRARY_ORDER),
        _curated_sort(workbench, WORKBENCH_ORDER),
    )


def _library_card(library: dict) -> str:
    """Return the HTML for a single package card.

    Links are ordered: Guide, API, Testing (if present), Experimental, Source.
    The testing link is only shown for packages whose ``mkdocs.yml``
    references a ``testing.md`` page.
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
    """Return a full ``<section>`` block, or the empty string when empty."""
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


def _render_library_install(first_library: dict) -> str:
    """Return the library-scoped Install block.

    Libraries are the only packages distributed via the CircuitPython
    bundle (circup) and mip.  Workbench packages ship to PyPI only,
    so this block only appears under the Libraries section.
    """
    package = first_library["package"]
    import_name = package.replace("-", "_")
    description = (
        "Library packages run on devices and ship through three channels:"
    )
    return f"""    <div class="install">
      <h2>Install: libraries</h2>
      <p class="section-description">{description}</p>
      <div class="install-block">
        <h3>pip (CPython, host-side use)</h3>
        <pre>pip install {package}</pre>
      </div>
      <div class="install-block">
        <h3>circup (CircuitPython)</h3>
        <pre>circup bundle-add ChuMicro/ChuMicro-Bundle
circup install {import_name}</pre>
      </div>
      <div class="install-block">
        <h3>mip (MicroPython)</h3>
        <pre>mpremote mip install github:ChuMicro/ChuMicro-Bundle/{import_name}</pre>
      </div>
    </div>"""


def _render_release_channels() -> str:
    """Return the Release Channels block.

    The bundle is the CircuitPython distribution path for library code;
    workbench packages are not bundled (they ship to PyPI only).  This
    block is library-scoped and renders adjacent to the library install
    block.
    """
    scope_note = (
        "The CircuitPython bundle is the distribution path for library "
        "code.  Workbench packages ship to PyPI only and don't appear in "
        "the bundle."
    )
    selector_note = (
        "Each library has a version selector in its docs header. Use it "
        "to switch between stable, experimental, and pinned versions."
    )
    return f"""    <div class="channels">
      <h2>Release channels: libraries</h2>
      <p class="section-description">{scope_note}</p>
      <table>
        <thead>
          <tr><th>Channel</th><th>Bundle</th><th>Description</th></tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Stable</strong></td>
            <td><a href="https://github.com/ChuMicro/ChuMicro-Bundle">ChuMicro-Bundle</a></td>
            <td>Released, tested versions, recommended for production</td>
          </tr>
          <tr>
            <td><strong>Experimental</strong></td>
            <td><a href="https://github.com/ChuMicro/ChuMicro-Bundle-Experimental">ChuMicro-Bundle-Experimental</a></td>
            <td>Pre-release: latest features, may contain breaking changes</td>
          </tr>
        </tbody>
      </table>
      <p style="margin-top:.75rem;font-size:.85rem;color:var(--muted);">
        {selector_note}
      </p>
    </div>"""


def _render_workbench_install(first_workbench: dict) -> str:
    """Return the workbench-scoped Install block.

    Workbench packages are host-only CPython tools: pip is the only
    install path.  Bundle / circup / mip do not apply.
    """
    package = first_workbench["package"]
    description = (
        "Workbench tools run on your laptop, not on a device.  "
        "CPython only:"
    )
    return f"""    <div class="install">
      <h2>Install: workbench</h2>
      <p class="section-description">{description}</p>
      <div class="install-block">
        <h3>pip (CPython)</h3>
        <pre>pip install {package}</pre>
      </div>
    </div>"""


def generate() -> str:
    """Return the full landing page HTML."""
    libraries, workbench = _discover_packages()

    blocks: list[str] = []
    if libraries:
        blocks.append(_render_section(
            "Libraries",
            "Cross-runtime Python libraries for CircuitPython, MicroPython, "
            "and CPython.",
            libraries,
        ))
        blocks.append(_render_library_install(libraries[0]))
        blocks.append(_render_release_channels())
    if workbench:
        blocks.append(_render_section(
            "Workbench",
            "Host-only CPython tools for deploying, probing, and flashing "
            "devices.",
            workbench,
        ))
        blocks.append(_render_workbench_install(workbench[0]))

    content = "\n\n".join(blocks)

    template_text = (TEMPLATES_DIR / "landing_page.html.template").read_text()
    return Template(template_text).substitute(content=content)


if __name__ == "__main__":
    print(generate(), end="")
