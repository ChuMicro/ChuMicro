"""Render the chumicro library dependency graph to an SVG artifact.

Source of truth for the rendered graph at
``support/docs/dependency-graph.svg``.  Pure-Python; no external deps.

Two edge kinds:

* **Strict deps** (solid arrows) — exactly the chumicro-prefixed entries
  in each ``libraries/<name>/pyproject.toml``'s ``[project].dependencies``.
  Auto-discovered at script invocation; if a library's pyproject changes,
  re-running this script picks the change up.
* **DI / typical-wiring deps** (dashed arrows) — relationships expressed
  through constructor injection rather than ``import``.  These don't show
  up in pyproject but are real (apps wire them up at runtime); the user
  who pulls a library in should know they exist.  Hand-curated below.

Run::

    python scripts/render_dep_graph.py            # regenerate the SVG
    python scripts/render_dep_graph.py --check    # verify the committed SVG
                                                  # matches what the current
                                                  # pyproject deps would render

Preflight runs ``--check`` so a contributor who changes a library's
``[project].dependencies`` without re-rendering the SVG sees the failure
in CI rather than discovering it months later when the docs go stale.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIBRARIES_DIR = REPO_ROOT / "libraries"
SVG_OUT = REPO_ROOT / "support" / "docs" / "dependency-graph.svg"

# Hand-curated DI / typical-wiring relationships.  Each library on the
# left is shaped to register with / receive an instance of the library
# on the right at runtime, but doesn't `import` it.  Apps wire them up.
DI_DEPS: dict[str, list[str]] = {
    "wifi": ["runner"],
    "ntp": ["runner", "timing"],
    "requests": ["runner"],
    "http_server": ["runner"],
    "mqtt": ["runner"],
    "websockets": ["runner"],
}

# Hand-curated node positions for an orthogonal three-tier layout.
# Foundation row at the bottom, building blocks in the middle, services
# at the top.  Standalone libraries (no edges) cluster on the side.
NODES: dict[str, tuple[int, int]] = {
    # Top row — services (y=60).
    "wifi":        (40,   60),
    "ntp":         (220,  60),
    "requests":    (400,  60),
    "http_server": (580,  60),
    "mqtt":        (760,  60),
    "websockets":  (940,  60),
    # Middle row — building blocks (y=300).
    "config":      (100,  300),
    "kvstore":     (300,  300),
    "runner":      (520,  300),
    # Bottom row — foundation primitives (y=540).
    "msgpack":     (140,  540),
    "timing":      (480,  540),
    "sockets":     (840,  540),
    # Standalone cluster (top-left of foundation row, no edges).
    "compat":      (40,   640),
    "logging":     (220,  640),
    "events":      (400,  640),
}

NODE_W, NODE_H = 130, 36
CANVAS_W, CANVAS_H = 1120, 720


def discover_strict_deps() -> dict[str, list[str]]:
    """Walk libraries/*/pyproject.toml and return chumicro-prefixed deps."""
    deps: dict[str, list[str]] = {}
    for library_dir in sorted(LIBRARIES_DIR.iterdir()):
        if not library_dir.is_dir():
            continue
        pyproject = library_dir / "pyproject.toml"
        if not pyproject.is_file():
            continue
        text = pyproject.read_text()
        # Strip from `dependencies = [` to the closing `]`.
        marker = "dependencies = ["
        start = text.find(marker)
        if start == -1:
            deps[library_dir.name] = []
            continue
        end = text.find("]", start)
        block = text[start + len(marker) : end]
        chumicro_deps = []
        for raw_line in block.splitlines():
            line = raw_line.strip().strip(",").strip('"').strip("'")
            if line.startswith("chumicro-"):
                chumicro_deps.append(line.removeprefix("chumicro-"))
        deps[library_dir.name] = chumicro_deps
    return deps


def edge_endpoints(
    source: str, destination: str
) -> tuple[float, float, float, float]:
    """Return (sx, sy, dx, dy) where the edge starts at the source's bottom
    edge and ends at the destination's top edge.  Both anchored to box
    centers in the perpendicular axis.
    """
    source_x, source_y = NODES[source]
    destination_x, destination_y = NODES[destination]
    source_cx = source_x + NODE_W / 2
    destination_cx = destination_x + NODE_W / 2
    if source_y < destination_y:
        # Source is above destination — line drops from source bottom
        # to destination top.
        return source_cx, source_y + NODE_H, destination_cx, destination_y
    # Source is below destination (rare here) — flip.
    return source_cx, source_y, destination_cx, destination_y + NODE_H


def render_node(name: str, kind: str = "default") -> str:
    """Box + label for one library."""
    box_x, box_y = NODES[name]
    return (
        f'  <g class="node {kind}">\n'
        f'    <rect x="{box_x}" y="{box_y}" width="{NODE_W}" height="{NODE_H}" '
        f'rx="6" ry="6" />\n'
        f'    <text x="{box_x + NODE_W / 2}" y="{box_y + NODE_H / 2 + 5}" '
        f'text-anchor="middle">chumicro-{name}</text>\n'
        f'  </g>'
    )


def render_edge(source: str, destination: str, dashed: bool) -> str:
    """One arrow from source's bottom to destination's top."""
    sx, sy, dx, dy = edge_endpoints(source, destination)
    css_class = "edge-di" if dashed else "edge-strict"
    return (
        f'  <line x1="{sx}" y1="{sy}" x2="{dx}" y2="{dy}" '
        f'class="{css_class}" marker-end="url(#arrow-{"di" if dashed else "strict"})" />'
    )


def render_svg(strict: dict[str, list[str]], di: dict[str, list[str]]) -> str:
    """Assemble the full SVG document."""
    edges_strict = [
        render_edge(source, destination, dashed=False)
        for source, targets in strict.items()
        for destination in targets
        if source in NODES and destination in NODES
    ]
    edges_di = [
        render_edge(source, destination, dashed=True)
        for source, targets in di.items()
        for destination in targets
        if source in NODES and destination in NODES
    ]

    standalone = {"compat", "logging", "events"}
    nodes_kind = []
    for name in NODES:
        if name in standalone:
            nodes_kind.append(render_node(name, kind="standalone"))
        else:
            nodes_kind.append(render_node(name))

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {CANVAS_W} {CANVAS_H}" '
        f'width="{CANVAS_W}" height="{CANVAS_H}" '
        f'font-family="system-ui, -apple-system, Helvetica, Arial, sans-serif" '
        f'font-size="13">',
        '  <defs>',
        '    <marker id="arrow-strict" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">',
        '      <path d="M 0 0 L 10 5 L 0 10 z" fill="#3b6db5" />',
        '    </marker>',
        '    <marker id="arrow-di" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">',
        '      <path d="M 0 0 L 10 5 L 0 10 z" fill="#999" />',
        '    </marker>',
        '    <style>',
        '      .node rect { fill: #ffffff; stroke: #1f2937; stroke-width: 1.5; }',
        '      .node text { fill: #1f2937; font-weight: 500; }',
        '      .node.standalone rect { fill: #f3f4f6; stroke: #9ca3af; stroke-dasharray: 3 2; }',
        '      .node.standalone text { fill: #6b7280; }',
        '      .edge-strict { stroke: #3b6db5; stroke-width: 1.5; fill: none; }',
        '      .edge-di { stroke: #999; stroke-width: 1.2; stroke-dasharray: 5 4; fill: none; }',
        '      .legend-label { fill: #1f2937; font-size: 12px; }',
        '      .legend-title { fill: #1f2937; font-size: 13px; font-weight: 600; }',
        '      .row-label { fill: #6b7280; font-size: 11px; font-weight: 600; '
        'text-transform: uppercase; letter-spacing: 0.5px; }',
        '    </style>',
        '  </defs>',
        '',
        '  <!-- Row labels -->',
        '  <text x="20" y="50" class="row-label">Services</text>',
        '  <text x="20" y="290" class="row-label">Building blocks</text>',
        '  <text x="20" y="530" class="row-label">Foundation</text>',
        '  <text x="20" y="630" class="row-label">Standalone</text>',
        '',
        '  <!-- Strict-dep arrows (pyproject.toml dependencies) -->',
        '  <g>',
        *edges_strict,
        '  </g>',
        '',
        '  <!-- DI / typical-wiring arrows (constructor injection) -->',
        '  <g>',
        *edges_di,
        '  </g>',
        '',
        '  <!-- Library boxes -->',
        '  <g>',
        *nodes_kind,
        '  </g>',
        '',
        '  <!-- Legend -->',
        '  <g transform="translate(740, 620)">',
        '    <text class="legend-title" x="0" y="0">Legend</text>',
        '    <line x1="0" y1="20" x2="40" y2="20" class="edge-strict" '
        'marker-end="url(#arrow-strict)" />',
        '    <text x="50" y="24" class="legend-label">strict dependency '
        '(pyproject.toml)</text>',
        '    <line x1="0" y1="44" x2="40" y2="44" class="edge-di" '
        'marker-end="url(#arrow-di)" />',
        '    <text x="50" y="48" class="legend-label">'
        'typical wiring (constructor injection)</text>',
        '  </g>',
        '',
        '</svg>',
    ]
    return "\n".join(parts) + "\n"


def _display_path(path: Path) -> str:
    """Format a path for human-readable error / status messages.

    Falls back to the absolute path when *path* isn't under the repo
    root (e.g. when tests monkey-patch ``SVG_OUT`` to a tmp_path).
    """
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render or verify the chumicro library dependency graph SVG.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Verify mode: re-render in memory, compare against the committed "
            "SVG, exit 1 if they differ.  Runs in preflight so a contributor "
            "who changes a library's [project].dependencies without re-rendering "
            "sees the failure in CI."
        ),
    )
    args = parser.parse_args(argv)

    strict = discover_strict_deps()
    rendered = render_svg(strict, DI_DEPS)

    if args.check:
        if not SVG_OUT.is_file():
            print(
                f"ERROR: {_display_path(SVG_OUT)} is missing.  "
                f"Run `python scripts/render_dep_graph.py` to generate it.",
                file=sys.stderr,
            )
            return 1
        committed = SVG_OUT.read_text()
        if committed != rendered:
            print(
                f"ERROR: {_display_path(SVG_OUT)} is out of date.  "
                f"A library's pyproject.toml deps changed but the rendered "
                f"SVG was not regenerated.  Run "
                f"`python scripts/render_dep_graph.py` and commit the result.",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {_display_path(SVG_OUT)} matches the current pyproject deps.")
        return 0

    SVG_OUT.parent.mkdir(parents=True, exist_ok=True)
    SVG_OUT.write_text(rendered)
    print(f"wrote {_display_path(SVG_OUT)}")
    print()
    print("Strict deps (auto-discovered from pyproject.toml):")
    for source, targets in sorted(strict.items()):
        if targets:
            print(f"  chumicro-{source} -> {', '.join('chumicro-' + name for name in targets)}")
    print()
    print("DI / typical-wiring deps (hand-curated):")
    for source, targets in sorted(DI_DEPS.items()):
        print(f"  chumicro-{source} -> {', '.join('chumicro-' + name for name in targets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
