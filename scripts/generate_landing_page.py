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

from repo_layout import ROOT, discover_doc_dirs, is_parked, read_pyproject_description
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


#: Public root of the documentation site, used for canonical URLs and
#: the sitemap.  Every package's docs live one level below it.
SITE_ROOT = "https://chumicro.github.io/ChuMicro"

#: The guides site: repository prose (questions, troubleshooting, wiring)
#: published alongside the per-library documentation.  Its config names
#: which pages publish, so the URL list below reads that nav rather than
#: guessing from the docs tree.
GUIDES_CONFIG = ROOT / "guides" / "mkdocs.yml"

#: Where the guides site is published, relative to the site root.
GUIDES_PREFIX = "guides"


def guides_urls() -> list[str]:
    """Return every published guides URL, section root first.

    Reads the guides nav so a page that is not published does not turn
    up in the sitemap.  Returns an empty list when the site is absent.
    """
    if not GUIDES_CONFIG.is_file():
        return []
    import yaml  # noqa: PLC0415 - only the URL builders need a YAML parser

    nav = yaml.safe_load(GUIDES_CONFIG.read_text()).get("nav") or []
    pages: list[str] = []

    def collect(entry: object) -> None:
        if isinstance(entry, str):
            pages.append(entry)
        elif isinstance(entry, dict):
            for value in entry.values():
                collect(value)
        elif isinstance(entry, list):
            for value in entry:
                collect(value)

    collect(nav)

    urls = [f"{SITE_ROOT}/{GUIDES_PREFIX}/"]
    for page in pages:
        slug = page.removesuffix(".md")
        # mkdocs publishes index.md and README.md as their directory.
        if slug in ("index", "README"):
            continue
        if slug.endswith("/index") or slug.endswith("/README"):
            slug = slug.rsplit("/", 1)[0]
        urls.append(f"{SITE_ROOT}/{GUIDES_PREFIX}/{slug}/")
    return urls


#: Where site-verification material lives.  See its README: one token
#: file per search engine, plus any file published verbatim at the
#: docs-site root.
VERIFICATION_DIR = ROOT / "support" / "docs" / "site-verification"

#: Token file to meta-tag name, in the order the tags are emitted.
VERIFICATION_TAGS = (
    ("google-meta-tag.txt", "google-site-verification"),
    ("bing-meta-tag.txt", "msvalidate.01"),
)


def _verification_meta() -> str:
    """Return the site-verification meta tags, or an empty string.

    Both engines recheck their tag after verifying, so a tag stays in
    the page for as long as its property is verified.  A token file
    that is absent or blank contributes nothing.
    """
    tags = []
    for filename, meta_name in VERIFICATION_TAGS:
        token_file = VERIFICATION_DIR / filename
        if not token_file.is_file():
            continue
        token = token_file.read_text().strip()
        if token:
            tags.append(f'  <meta name="{meta_name}" content="{token}">\n')
    return "".join(tags)


def site_urls() -> list[str]:
    """Return every public documentation URL, site root first.

    One address per package, always the ``stable`` channel, because
    that is the URL that stays put across releases.  The sitemap and
    the IndexNow ping both work from this list, so a search engine
    reading either sees the same site.
    """
    libraries, workbench = _discover_packages()
    return [f"{SITE_ROOT}/"] + [
        f"{SITE_ROOT}/{package['name']}/stable/"
        for package in libraries + workbench
    ] + guides_urls()


def generate_llms_txt() -> str:
    """Return an llms.txt map of the documentation site.

    Answer engines and coding assistants read this file (the
    llmstxt.org convention) to learn what a project ships without
    crawling every page.  It carries the same package set as the
    landing page, in markdown a model can quote directly.
    """
    libraries, workbench = _discover_packages()
    lines = [
        "# ChuMicro",
        "",
        "> Python libraries for microcontrollers: WiFi, MQTT, HTTP client and "
        "server, WebSockets, sockets, network time, timers, settings, and "
        "storage that survives a reboot.  One codebase runs on CircuitPython, "
        "MicroPython, and CPython.",
        "",
        "Every library keeps the main loop running: slow network work happens "
        "a step at a time between ticks, so an LED keeps blinking while WiFi "
        "reconnects.  Each library installs on its own.",
        "",
        "Install `chumicro-mqtt` (any library follows the same shape):",
        "",
        "```bash",
        "circup bundle-add ChuMicro/ChuMicro-Bundle && circup install chumicro_mqtt",
        "mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_mqtt",
        "pip install chumicro-mqtt",
        "```",
        "",
        "## Libraries",
        "",
    ]
    lines.extend(
        f"- [{package['package']}]({SITE_ROOT}/{package['name']}/stable/): "
        f"{package['description']}"
        for package in libraries
    )
    lines.extend(["", "## Host tools", ""])
    lines.extend(
        f"- [{package['package']}]({SITE_ROOT}/{package['name']}/stable/): "
        f"{package['description']}"
        for package in workbench
    )
    lines.extend([
        "",
        "## Guides",
        "",
        f"- [Questions people ask]({SITE_ROOT}/{GUIDES_PREFIX}/faq/): why a board "
        "freezes on the network, whether the libraries use async, what they cost "
        "in flash, and how to test without hardware.",
        f"- [Troubleshooting]({SITE_ROOT}/{GUIDES_PREFIX}/troubleshooting/): fixes "
        "keyed to a symptom, including a board that will not appear, WiFi that "
        "will not connect, TLS failures, refused deploys, and running out of memory.",
        f"- [Wiring WiFi credentials]({SITE_ROOT}/{GUIDES_PREFIX}/"
        "wiring-wifi-credentials/): getting a network name and password onto a "
        "board without putting them in your code.",
        "",
        "## Optional",
        "",
        "- [Source and examples](https://github.com/ChuMicro/ChuMicro): the "
        "repository, with a runnable example per library.",
        "- [Bundle](https://github.com/ChuMicro/ChuMicro-Bundle): what circup "
        "and mip install from.",
        "",
    ])
    return "\n".join(lines)


def generate_sitemap() -> str:
    """Return a sitemap.xml listing the site root and every package.

    Search engines discover the per-package documentation through this
    file: the landing page links each package's ``stable/`` URL, and
    the sitemap states the same set in the form crawlers read directly.
    """
    urls = site_urls()
    entries = "\n".join(f"  <url>\n    <loc>{url}</loc>\n  </url>" for url in urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n"
        "</urlset>\n"
    )


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
    return Template(template_text).substitute(
        content=content, verification=_verification_meta(),
    )


if __name__ == "__main__":
    print(generate(), end="")
