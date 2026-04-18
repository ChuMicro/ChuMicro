"""Generate the docs landing page (index.html) for the gh-pages branch.

Auto-discovers all libraries under ``libraries/`` and produces an HTML
landing page with cards, install snippets, and release channel information.
The generated page follows the dark-mode design used across the site.

Usage (from repository root)::

    python scripts/generate_landing_page.py > /tmp/index.html

The docs-deploy workflow calls this to regenerate the page on every push.
"""
# ruff: noqa: E501 — embedded HTML/CSS in f-strings exceeds line limits.

from __future__ import annotations

import re

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

        # Detect whether the library's docs include a testing page.
        # A plain text search in mkdocs.yml is a pragmatic shortcut —
        # YAML parsing would be heavier for this single boolean check.
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
    # Convert the pip package name (chumicro-timing) to a Python import name
    # (chumicro_timing) for the mip install example.
    first_import = re.sub(r"-", "_", first_package)

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ChuMicro — Documentation</title>
  <link rel="icon" href="./assets/images/favicon.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #0e0f10;
      --card-bg: #1a1510;
      --text: #e6edf3;
      --muted: #8b949e;
      --accent: #e87518;
      --accent-hover: #f0a050;
      --border: #2a1e10;
      --tag-bg: #1e1208;
      --tag-text: #e8d296;
      --green-bg: #1e1208;
      --green-text: #ed9838;
      --orange-bg: #1e1208;
      --orange-text: #f0a050;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif;
      background: var(--bg); color: var(--text);
      font-size: 1rem; line-height: 1.75;
    }}
    .container {{ max-width: 860px; margin: 0 auto; padding: 2rem 1.5rem; }}

    /* Header */
    header {{ text-align: center; padding: 3rem 0 2rem; }}
    header h1 {{ font-size: 2em; font-weight: 700; margin-bottom: .5rem; }}
    header p {{ font-size: 1.1rem; color: var(--muted); max-width: 600px; margin: 0 auto; }}
    .badges {{ margin-top: 1rem; display: flex; gap: .5rem; justify-content: center; flex-wrap: wrap; }}
    .badge {{
      display: inline-block; font-size: .8rem; font-weight: 600;
      padding: .25rem .65rem; border-radius: 1rem;
    }}
    .badge-cream {{ background: var(--tag-bg); color: var(--tag-text); }}
    .badge-amber {{ background: var(--green-bg); color: var(--green-text); }}
    .badge-orange {{ background: var(--orange-bg); color: var(--orange-text); }}

    /* Library cards */
    .libraries {{ display: grid; gap: 1rem; margin: 2rem 0; }}
    .card {{
      background: var(--card-bg); border: 1px solid var(--border);
      border-radius: .75rem; padding: 1.25rem 1.5rem;
      transition: border-color .15s;
    }}
    .card:hover {{ border-color: var(--accent); }}
    .card h2 {{ font-size: 1.15rem; margin-bottom: .35rem; }}
    .card h2 a {{ color: var(--accent); text-decoration: none; }}
    .card h2 a:hover {{ text-decoration: underline; }}
    .card p {{ color: var(--muted); font-size: .95rem; margin-bottom: .75rem; }}
    .card-links {{ display: flex; gap: .5rem; font-size: .85rem; flex-wrap: wrap; }}
    .card-links a {{ color: var(--accent); text-decoration: none; }}
    .card-links a:hover {{ text-decoration: underline; }}
    .card-links .sep {{ color: var(--border); }}

    /* Install section */
    .install {{ margin: 2.5rem 0; }}
    .install h2 {{ font-size: 1.3rem; margin-bottom: 1rem; }}
    .install-block {{ margin-bottom: 1rem; }}
    .install-block:last-child {{ margin-bottom: 0; }}
    .install-block h3 {{ font-size: .9rem; color: var(--muted); margin-bottom: .4rem; font-weight: 600; }}
    pre {{
      background: var(--card-bg); border: 1px solid var(--border);
      border-radius: .5rem; padding: .75rem 1rem;
      font-size: .88rem; overflow-x: auto; color: var(--text);
      font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
      line-height: 1.65; white-space: pre-wrap; word-break: break-all;
    }}

    /* Channels */
    .channels {{
      background: var(--card-bg); border: 1px solid var(--border);
      border-radius: .75rem; padding: 1.25rem 1.5rem; margin: 2rem 0;
    }}
    .channels h2 {{ font-size: 1.1rem; margin-bottom: .5rem; }}
    .channels table {{ width: 100%; font-size: .9rem; border-collapse: collapse; }}
    .channels th, .channels td {{ text-align: left; padding: .5rem .6rem; }}
    .channels th {{ color: var(--muted); font-weight: 600; border-bottom: 1px solid var(--border); }}
    .channels td {{ border-bottom: 1px solid var(--border); }}
    .channels a {{ color: var(--accent); text-decoration: none; }}
    .channels a:hover {{ text-decoration: underline; }}
    code {{ font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace; font-size: .88em; }}

    /* Footer */
    footer {{ text-align: center; padding: 2rem 0 3rem; color: var(--muted); font-size: .9rem; }}
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
        <span class="badge badge-cream">CircuitPython</span>
        <span class="badge badge-amber">MicroPython</span>
        <span class="badge badge-orange">CPython</span>
      </div>
    </header>

    <div class="libraries">
{cards}
    </div>

    <div class="install">
      <h2>Install</h2>
      <div class="install-block">
        <h3>pip (CPython)</h3>
        <pre>pip install {first_package}</pre>
      </div>
      <div class="install-block">
        <h3>circup (CircuitPython)</h3>
        <pre>circup bundle-add ChuMicro/ChuMicro-Bundle
circup install {first_package}</pre>
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
          <tr><th>Channel</th><th>Bundle</th><th>Description</th></tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Stable</strong></td>
            <td><a href="https://github.com/ChuMicro/ChuMicro-Bundle">ChuMicro-Bundle</a></td>
            <td>Released, tested versions &mdash; recommended for production</td>
          </tr>
          <tr>
            <td><strong>Experimental</strong></td>
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
