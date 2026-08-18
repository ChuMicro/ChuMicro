"""Generate the host-root site published at https://chumicro.github.io/.

GitHub serves one root site per account, named after the account, and
every repository under it publishes at a path below that root.  The
ChuMicro documentation lives at ``/ChuMicro/`` and keeps that address;
this generator builds the page that sits above it and points into it.

Three things only exist at the root of a host.  ``robots.txt`` is read
there and nowhere else, so a project path cannot advertise a sitemap.
Search engines verify ownership per site, and a root property covers
every path below it.  IndexNow accepts submissions for a whole host
when its key file answers at the root, which is what makes a submission
for a ``/ChuMicro/`` page succeed.

Usage (from repository root)::

    python scripts/generate_site_root.py            # build into .site-root/
    python scripts/generate_site_root.py --check    # build into a temp dir

The docs-deploy workflow builds this and pushes it to the site
repository; preflight builds it so a broken page fails locally first.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from string import Template

from generate_landing_page import _discover_packages
from repo_layout import ROOT
from shared import TEMPLATES_DIR

#: The host this site occupies.  No trailing slash: callers add one.
HOST = "https://chumicro.github.io"

#: The hub's own pages, split out so ``sitemap.xml`` can be an index.
PAGES_SITEMAP = "sitemap-pages.xml"

#: Where the built site lands.  Gitignored: the site repository is the
#: place it gets committed, the same way ``gh-pages`` holds the docs.
SITE_DIR = ROOT / ".site-root"

#: Site-verification material, shared with the project-path landing
#: page.  One source of truth: a token that changes changes both sites.
VERIFICATION_DIR = ROOT / "support" / "docs" / "site-verification"

#: Public projects the hub links to, in the order they render.  A
#: private repository does not belong on a public index, so this list
#: is curated rather than read from the organization.
PROJECTS = (
    {
        "name": "ChuMicro",
        "path": "ChuMicro",
        "tagline": (
            "Python libraries for microcontrollers that never freeze your "
            "program, plus the host tools that deploy them.  One codebase "
            "runs on CircuitPython, MicroPython, and CPython."
        ),
        "repo": "https://github.com/ChuMicro/ChuMicro",
    },
)


def _verification_meta() -> str:
    """Return the site-verification meta tags for the root property.

    Both engines recheck their tag after verifying, so a tag stays in
    the page for as long as its property is verified.  The tokens are
    the same ones the project-path page carries: one property per
    engine covers the host and every path below it.

    Returns:
        HTML meta tags, one per line with trailing newline, or ``""``.
    """
    tags = []
    for filename, meta_name in (
        ("google-meta-tag.txt", "google-site-verification"),
        ("bing-meta-tag.txt", "msvalidate.01"),
    ):
        token_file = VERIFICATION_DIR / filename
        if not token_file.is_file():
            continue
        token = token_file.read_text().strip()
        if token:
            tags.append(f'  <meta name="{meta_name}" content="{token}">')
    return "\n".join(tags) + "\n" if tags else ""


def _structured_data() -> str:
    """Return the hub's JSON-LD block.

    The root describes the organization and names the sites below it,
    which is what tells an answer engine that ``/ChuMicro/`` and this
    page belong to the same publisher.

    Returns:
        A ``<script type="application/ld+json">`` block with a trailing
        newline.
    """
    graph = [
        {
            "@type": "Organization",
            "@id": f"{HOST}/#organization",
            "name": "ChuMicro",
            "url": f"{HOST}/",
            "description": (
                "Open-source Python libraries and host tools for "
                "microcontrollers running CircuitPython, MicroPython, and "
                "CPython."
            ),
            "logo": (
                "https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/"
                "support/docs/chumicro.png"
            ),
            "sameAs": [
                "https://github.com/ChuMicro",
                "https://pypi.org/search/?q=chumicro",
            ],
        },
        {
            "@type": "WebSite",
            "@id": f"{HOST}/#website",
            "url": f"{HOST}/",
            "name": "ChuMicro",
            "publisher": {"@id": f"{HOST}/#organization"},
            "inLanguage": "en",
            "hasPart": [
                {
                    "@type": "WebSite",
                    "@id": f"{HOST}/{project['path']}/#website",
                    "url": f"{HOST}/{project['path']}/",
                    "name": project["name"],
                }
                for project in PROJECTS
            ],
        },
    ]
    payload = json.dumps({"@context": "https://schema.org", "@graph": graph}, indent=2)
    body = "\n".join(f"    {line}" for line in payload.splitlines())
    return f'  <script type="application/ld+json">\n{body}\n  </script>\n'


def _render_projects() -> str:
    """Return the projects section: one card per public project."""
    cards = []
    for project in PROJECTS:
        docs_url = f"{HOST}/{project['path']}/"
        cards.append(
            '      <article class="card">\n'
            f'        <h3><a href="{docs_url}">{project["name"]}</a></h3>\n'
            f'        <p>{project["tagline"]}</p>\n'
            '        <p class="links">\n'
            f'          <a href="{docs_url}">Documentation</a>\n'
            f'          <a href="{docs_url}guides/">Guides</a>\n'
            f'          <a href="{project["repo"]}">Source</a>\n'
            "        </p>\n"
            "      </article>"
        )
    return "\n".join(cards)


def _render_package_links() -> str:
    """Return the deep-link lists that point at each package's docs.

    The strongest address on a host is its root, so the hub links
    straight into the pages that answer a search rather than making a
    reader take two hops to reach them.
    """
    libraries, workbench = _discover_packages()
    blocks = []
    for heading, description, packages in (
        (
            "Libraries",
            "Run on the board.  Install one on its own or take the bundle.",
            libraries,
        ),
        (
            "Host tools",
            "Run on your computer: deploy code, watch a board, flash firmware.",
            workbench,
        ),
    ):
        if not packages:
            continue
        items = "\n".join(
            f'        <li><a href="{HOST}/ChuMicro/{package["name"]}/stable/">'
            f'{package["package"]}</a> {package["description"]}</li>'
            for package in packages
        )
        blocks.append(
            '    <section class="section">\n'
            f'      <h2 class="section-heading">{heading}</h2>\n'
            f'      <p class="section-description">{description}</p>\n'
            f"      <ul class=\"package-list\">\n{items}\n      </ul>\n"
            "    </section>"
        )
    return "\n\n".join(blocks)


def root_index_html() -> str:
    """Return the hub page HTML."""
    template_text = (TEMPLATES_DIR / "site_root.html.template").read_text()
    return Template(template_text).substitute(
        verification=_verification_meta(),
        structured_data=_structured_data(),
        projects=_render_projects(),
        packages=_render_package_links(),
    )


def root_robots_txt() -> str:
    """Return robots.txt for the whole host.

    Only the root serves this file, so it is the one place a crawler
    can be told where the host's sitemap index lives.
    """
    return "\n".join([
        "User-agent: *",
        "Allow: /",
        "",
        # The index reaches every sitemap on the host, so naming the
        # children here as well would only repeat what it already says.
        f"Sitemap: {HOST}/sitemap.xml",
        "",
    ])


def root_pages_sitemap() -> str:
    """Return the sitemap covering the hub's own pages.

    Only the hub page lives at the host root today.  It sits in its own
    file rather than in the index so the index stays what its name says
    it is: a list of sitemaps.
    """
    entry = f"  <url>\n    <loc>{HOST}/</loc>\n  </url>"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entry}\n"
        "</urlset>\n"
    )


def root_sitemap() -> str:
    """Return the host's sitemap index: every sitemap on the host.

    An index rather than a list of URLs, because a sitemap at the host
    root is the only one whose scope is the whole host.  Submitting it
    once to a search engine covers every project below it, including
    ones added later: a new project adds a line here instead of a new
    submission someone has to remember to make.
    """
    children = [f"{HOST}/{PAGES_SITEMAP}"]
    children.extend(f"{HOST}/{project['path']}/sitemap.xml" for project in PROJECTS)
    entries = "\n".join(
        f"  <sitemap>\n    <loc>{child}</loc>\n  </sitemap>" for child in children
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n"
        "</sitemapindex>\n"
    )


def root_llms_txt() -> str:
    """Return an llms.txt index of the host.

    The hub's copy stays short and hands off to each project's own
    file, which carries the package list a model actually wants.
    """
    lines = [
        "# ChuMicro",
        "",
        "> Open-source Python libraries and host tools for microcontrollers.  "
        "One codebase runs on CircuitPython, MicroPython, and CPython.",
        "",
        "## Projects",
        "",
    ]
    lines.extend(
        f"- [{project['name']}]({HOST}/{project['path']}/): {project['tagline']}"
        for project in PROJECTS
    )
    lines.extend([
        "",
        "## Optional",
        "",
        f"- [ChuMicro library and tool index]({HOST}/ChuMicro/llms.txt): every "
        "package with a one-line description and its documentation address.",
        "- [Source on GitHub](https://github.com/ChuMicro): every public "
        "repository.",
        "",
    ])
    return "\n".join(lines)


def root_readme() -> str:
    """Return the site repository's README.

    The repository holds build output, so its README says where the
    source is and what breaks if someone edits the tree by hand.
    """
    project_lines = "\n".join(
        f"- [{project['name']}]({HOST}/{project['path']}/), built from "
        f"[{project['repo'].removeprefix('https://github.com/')}]({project['repo']})"
        for project in PROJECTS
    )
    return f"""# chumicro.github.io

The page at {HOST}/ and the files that describe this host to search
engines: `robots.txt`, `sitemap.xml`, `llms.txt`, the ownership tokens
both engines fetch, and the IndexNow key.

## Generated, not written

Every file here is built by `scripts/generate_site_root.py` in
[ChuMicro/ChuMicro](https://github.com/ChuMicro/ChuMicro) and pushed by
its documentation workflow.  An edit made here is overwritten by the
next deploy, so change the generator instead.

## What publishes below this page

{project_lines}

Each project repository serves its own path on this host and keeps its
own documentation.  Never add a folder here named after one of them:
the project's site and the folder would claim the same address.
"""


def _copy_verification_files(destination: Path) -> list[str]:
    """Copy the files each engine fetches verbatim, and the IndexNow key.

    Args:
        destination: Directory the site is being built into.

    Returns:
        The filenames written, sorted.
    """
    written = []
    for source in sorted(VERIFICATION_DIR.glob("*.html")) + sorted(
        VERIFICATION_DIR.glob("*.xml")
    ):
        shutil.copyfile(source, destination / source.name)
        written.append(source.name)

    key_file = VERIFICATION_DIR / "indexnow-key.txt"
    if key_file.is_file():
        key = key_file.read_text().strip()
        if key:
            # IndexNow authorizes a whole host when the key answers at
            # its root, which is what lets a /ChuMicro/ URL be submitted.
            (destination / f"{key}.txt").write_text(key)
            written.append(f"{key}.txt")
    return sorted(written)


def build(destination: Path) -> list[str]:
    """Build the whole root site into *destination*.

    Args:
        destination: Directory to write into.  Created if absent; any
            file already there with a generated name is overwritten.

    Returns:
        Every filename written, sorted.
    """
    destination.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, content in (
        ("index.html", root_index_html()),
        ("robots.txt", root_robots_txt()),
        ("sitemap.xml", root_sitemap()),
        (PAGES_SITEMAP, root_pages_sitemap()),
        ("llms.txt", root_llms_txt()),
        ("README.md", root_readme()),
        # Pages runs Jekyll over a site repository unless told not to.
        # Nothing here needs it, and skipping it keeps the build honest
        # about serving exactly the bytes this generator wrote.
        (".nojekyll", ""),
    ):
        (destination / filename).write_text(content)
        written.append(filename)
    written.extend(_copy_verification_files(destination))
    return sorted(written)


def main(argv: list[str] | None = None) -> int:
    """Build the root site.

    Args:
        argv: Command-line arguments, or ``None`` to read ``sys.argv``.

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="build into a temporary directory instead of .site-root/",
    )
    args = parser.parse_args(argv)

    if args.check:
        with tempfile.TemporaryDirectory() as scratch:
            written = build(Path(scratch))
    else:
        written = build(SITE_DIR)
        print(f"Built {SITE_DIR.relative_to(ROOT)}/")
    for filename in written:
        print(f"  {filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
