"""Generate the docs landing page (index.html) for the gh-pages branch.

Auto-discovers all libraries under ``libraries/`` and produces an HTML
landing page with cards, install snippets, and release channel info.
The generated page follows the dark-mode design used across the site.

Usage (from repo root)::

    python scripts/generate_landing_page.py > /tmp/index.html

The docs-deploy workflow calls this to regenerate the page on every push.
"""
# ruff: noqa: E501 — embedded HTML/CSS in f-strings exceeds line limits.

from __future__ import annotations

import re

from discovery import ROOT


def _strip_markdown_links(text: str) -> str:
    """Convert ``[text](url)`` to just ``text``."""
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)


def _discover_libraries() -> list[dict]:
    """Return metadata dicts for each library with a mkdocs.yml."""
    libraries_dir = ROOT / "libraries"
    if not libraries_dir.is_dir():
        return []

    libs = []
    for child in sorted(libraries_dir.iterdir()):
        if not child.is_dir() or not (child / "mkdocs.yml").exists():
            continue
        name = child.name
        readme = child / "README.md"
        description = ""
        if readme.exists():
            text = readme.read_text()
            # Extract the first "real" paragraph line from the README.
            # Skip headings (#), blank lines, and table rows (|) — some
            # READMEs have a metadata or badge table near the top.
            for line in text.splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and not stripped.startswith("|"):
                    description = _strip_markdown_links(stripped)
                    break

        # Detect whether the library's docs include a testing page.
        # A plain text search in mkdocs.yml is a pragmatic shortcut —
        # YAML parsing would be heavier for this single boolean check.
        mkdocs_text = (child / "mkdocs.yml").read_text()
        has_testing = "testing.md" in mkdocs_text

        libs.append({
            "name": name,
            "pkg": f"chumicro-{name}",
            "description": description,
            "has_testing": has_testing,
        })
    return libs


def _library_card(lib: dict) -> str:
    """Return the HTML for a single library card."""
    name = lib["name"]
    pkg = lib["pkg"]
    desc = lib["description"]

    links = [
        f'<a href="{name}/stable/guide/">Guide</a>',
        f'<a href="{name}/stable/api/">API</a>',
    ]
    if lib["has_testing"]:
        links.append(f'<a href="{name}/stable/testing/">Testing</a>')
    links.append(f'<a href="{name}/experimental/">Experimental</a>')
    links.append(
        f'<a href="https://github.com/ChuMicro/ChuMicro/tree/develop/libraries/{name}">Source</a>'
    )

    sep = '\n          <span class="sep">&middot;</span>\n          '
    card_links = sep.join(links)

    return f"""\
      <div class="card">
        <h2><a href="{name}/stable/">{pkg}</a></h2>
        <p>{desc}</p>
        <div class="card-links">
          {card_links}
        </div>
      </div>"""


def generate() -> str:
    """Return the full landing page HTML."""
    libs = _discover_libraries()
    cards = "\n\n".join(_library_card(lib) for lib in libs)

    # Use the first library name for install examples
    first_pkg = libs[0]["pkg"] if libs else "chumicro-timing"
    first_import = re.sub(r"-", "_", first_pkg)

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ChuMicro — Documentation</title>
  <style>
    :root {{
      --bg: #1e1e2e;
      --card-bg: #27273a;
      --text: #e6edf3;
      --muted: #8b949e;
      --accent: #9d7cd8;
      --accent-hover: #b4a0e0;
      --border: #3a3a52;
      --tag-bg: #1e1e3a;
      --tag-text: #7aa2f7;
      --green-bg: #0d2818;
      --green-text: #3fb950;
      --purple-bg: #2a1f4e;
      --purple-text: #b4a0e0;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif;
      background: var(--bg); color: var(--text);
      line-height: 1.6;
    }}
    .container {{ max-width: 860px; margin: 0 auto; padding: 2rem 1.5rem; }}

    /* Header */
    header {{ text-align: center; padding: 3rem 0 2rem; }}
    header h1 {{ font-size: 2rem; font-weight: 700; margin-bottom: .5rem; }}
    header p {{ font-size: 1.1rem; color: var(--muted); max-width: 600px; margin: 0 auto; }}
    .badges {{ margin-top: 1rem; display: flex; gap: .5rem; justify-content: center; flex-wrap: wrap; }}
    .badge {{
      display: inline-block; font-size: .75rem; font-weight: 600;
      padding: .2rem .6rem; border-radius: 1rem;
    }}
    .badge-blue {{ background: var(--tag-bg); color: var(--tag-text); }}
    .badge-green {{ background: var(--green-bg); color: var(--green-text); }}
    .badge-purple {{ background: var(--purple-bg); color: var(--purple-text); }}

    /* Library cards */
    .libraries {{ display: grid; gap: 1rem; margin: 2rem 0; }}
    .card {{
      background: var(--card-bg); border: 1px solid var(--border);
      border-radius: .75rem; padding: 1.25rem 1.5rem;
      transition: border-color .15s;
    }}
    .card:hover {{ border-color: var(--accent); }}
    .card h2 {{ font-size: 1.1rem; margin-bottom: .35rem; }}
    .card h2 a {{ color: var(--accent); text-decoration: none; }}
    .card h2 a:hover {{ text-decoration: underline; }}
    .card p {{ color: var(--muted); font-size: .9rem; margin-bottom: .75rem; }}
    .card-links {{ display: flex; gap: .5rem; font-size: .8rem; flex-wrap: wrap; }}
    .card-links a {{ color: var(--accent); text-decoration: none; }}
    .card-links a:hover {{ text-decoration: underline; }}
    .card-links .sep {{ color: var(--border); }}

    /* Install section */
    .install {{ margin: 2.5rem 0; }}
    .install h2 {{ font-size: 1.2rem; margin-bottom: 1rem; }}
    .install-block {{ margin-bottom: 1rem; }}
    .install-block:last-child {{ margin-bottom: 0; }}
    .install-block h3 {{ font-size: .85rem; color: var(--muted); margin-bottom: .4rem; font-weight: 600; }}
    pre {{
      background: var(--card-bg); border: 1px solid var(--border);
      border-radius: .5rem; padding: .75rem 1rem;
      font-size: .8rem; overflow-x: auto; color: var(--text);
      font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
      white-space: pre-wrap; word-break: break-all;
    }}

    /* Channels */
    .channels {{
      background: var(--card-bg); border: 1px solid var(--border);
      border-radius: .75rem; padding: 1.25rem 1.5rem; margin: 2rem 0;
    }}
    .channels h2 {{ font-size: 1rem; margin-bottom: .5rem; }}
    .channels table {{ width: 100%; font-size: .85rem; border-collapse: collapse; }}
    .channels th, .channels td {{ text-align: left; padding: .4rem .5rem; }}
    .channels th {{ color: var(--muted); font-weight: 600; border-bottom: 1px solid var(--border); }}
    .channels td {{ border-bottom: 1px solid var(--border); }}
    .channels a {{ color: var(--accent); text-decoration: none; }}
    .channels a:hover {{ text-decoration: underline; }}
    code {{ font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace; font-size: .85em; }}

    /* Footer */
    footer {{ text-align: center; padding: 2rem 0 3rem; color: var(--muted); font-size: .85rem; }}
    footer a {{ color: var(--accent); text-decoration: none; }}
    footer a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>ChuMicro</h1>
      <p>Cross-runtime Python libraries for CircuitPython, MicroPython, and CPython &mdash; built for ESP32, RP2040, and other microcontrollers.</p>
      <div class="badges">
        <span class="badge badge-blue">CircuitPython</span>
        <span class="badge badge-green">MicroPython</span>
        <span class="badge badge-purple">CPython</span>
      </div>
    </header>

    <div class="libraries">
{cards}
    </div>

    <div class="install">
      <h2>Install</h2>
      <div class="install-block">
        <h3>pip (CPython)</h3>
        <pre>pip install {first_pkg}</pre>
      </div>
      <div class="install-block">
        <h3>circup (CircuitPython)</h3>
        <pre>circup bundle-add ChuMicro/ChuMicro-Bundle
circup install {first_pkg}</pre>
      </div>
      <div class="install-block">
        <h3>mip (MicroPython)</h3>
        <pre>mpremote mip install github:ChuMicro/ChuMicro-Bundle/{first_import}</pre>
      </div>
    </div>

    <div class="channels">
      <h2>Release channels</h2>
      <table>
        <thead>
          <tr><th>Channel</th><th>Branch</th><th>Bundle</th><th>Description</th></tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Stable</strong></td>
            <td><code>main</code></td>
            <td><a href="https://github.com/ChuMicro/ChuMicro-Bundle">ChuMicro-Bundle</a></td>
            <td>Released, tested versions &mdash; recommended for production</td>
          </tr>
          <tr>
            <td><strong>Experimental</strong></td>
            <td><code>develop</code></td>
            <td><a href="https://github.com/ChuMicro/ChuMicro-Bundle-Experimental">ChuMicro-Bundle-Experimental</a></td>
            <td>Pre-release &mdash; latest features, may contain breaking changes</td>
          </tr>
        </tbody>
      </table>
      <p style="margin-top:.75rem;font-size:.85rem;color:var(--muted);">
        Each library has a version selector in its docs header. Use it to switch between stable, experimental, and pinned versions.
      </p>
    </div>

    <footer>
      <a href="https://github.com/ChuMicro/ChuMicro">Source on GitHub</a>
      &nbsp;&middot;&nbsp;
      <a href="https://pypi.org/search/?q=chumicro">PyPI</a>
      &nbsp;&middot;&nbsp;
      <a href="https://github.com/ChuMicro/ChuMicro-Bundle">Bundle</a>
      &nbsp;&middot;&nbsp;
      <a href="https://github.com/ChuMicro/ChuMicro-Bundle-Experimental">Experimental Bundle</a>
      <br>
      MIT License &middot; Built with <a href="https://zensical.org">Zensical</a> + <a href="https://github.com/jimporter/mike">mike</a>
    </footer>
  </div>
</body>
</html>
"""


if __name__ == "__main__":
    print(generate(), end="")
