"""Render chumicro dependency graphs to SVG artifacts.

Two graphs are produced from this single script:

* ``support/docs/dependency-graph.svg``: device libraries under
  ``libraries/<name>/``.
* ``support/docs/workbench-dependency-graph.svg``: host-side tools under
  ``workbench/<name>/``.

Both pure-Python, no external deps.

Two edge kinds (same convention in each graph):

* **Strict deps** (solid arrows): exactly the chumicro-prefixed entries
  in each package's ``pyproject.toml`` ``[project].dependencies``.
  Auto-discovered at script invocation; if a package's pyproject changes,
  re-running this script picks the change up.
* **DI / typical-wiring deps** (dashed arrows): relationships expressed
  through constructor injection or lazy runtime import rather than a
  declared dep.  Hand-curated below, so the user who pulls a package in
  should know they exist.

Run::

    python scripts/render_dep_graph.py            # regenerate both SVGs
    python scripts/render_dep_graph.py --check    # verify both committed
                                                  # SVGs match what the
                                                  # current pyprojects render

Preflight runs ``--check`` so a contributor who changes a package's
``[project].dependencies`` without re-rendering sees the failure in CI
rather than discovering it months later when the docs go stale.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIBRARIES_DIR = REPO_ROOT / "libraries"
WORKBENCH_DIR = REPO_ROOT / "workbench"
SVG_OUT = REPO_ROOT / "support" / "docs" / "dependency-graph.svg"
WORKBENCH_SVG_OUT = REPO_ROOT / "support" / "docs" / "workbench-dependency-graph.svg"

# Hand-curated DI / typical-wiring relationships.  Each library on the
# left registers with / receives an instance of the library on the right
# at runtime, but doesn't `import` it.  Apps wire them up.
DI_DEPS: dict[str, list[str]] = {
    "wifi": ["runner"],
    "ntp": ["runner", "timing"],
    "requests": ["runner"],
    "http_server": ["runner"],
    "mqtt": ["runner"],
    "websockets": ["runner"],
}

# Workbench DI / soft-dep relationships.  ``chumicro-workspace`` imports
# ``chumicro_repl`` lazily inside CLI functions and prints an install hint
# if the import fails.  A real runtime relationship but not a declared
# pyproject dep.
WORKBENCH_DI_DEPS: dict[str, list[str]] = {
    "workspace": ["repl"],
}

# Hand-curated node positions for an orthogonal three-tier layout.
# Foundation row at the bottom, building blocks in the middle, services
# at the top.  Standalone libraries (no edges) cluster on the side.
NODES: dict[str, tuple[int, int]] = {
    # Top row: services (y=60).
    "wifi":        (40,   60),
    "ntp":         (220,  60),
    "requests":    (400,  60),
    "http_server": (580,  60),
    "mqtt":        (760,  60),
    "websockets":  (940,  60),
    # Middle row: building blocks (y=300).
    "config":      (100,  300),
    "kvstore":     (300,  300),
    "runner":      (520,  300),
    # Bottom row: foundation primitives (y=540).
    "msgpack":     (140,  540),
    "timing":      (480,  540),
    "sockets":     (840,  540),
    # Standalone cluster (top-left of foundation row, no edges).
    "compat":      (40,   640),
}

# Workbench layout: composers on top, primitives below, lint-only
# ``checks`` package off to the side as a standalone node.
WORKBENCH_NODES: dict[str, tuple[int, int]] = {
    # Top row: composers (y=60).
    "workspace":     (40,   60),
    "pytest-device": (240,  60),
    # Bottom row: primitives (y=240).
    "deploy":        (40,   240),
    "repl":          (240,  240),
    # Standalone (no edges): workspace-internal lint rules.
    "checks":        (470,  240),
}

WORKBENCH_STANDALONE = {"checks"}

NODE_W, NODE_H = 130, 36
WORKBENCH_NODE_W = 170  # fits "chumicro-pytest-device" comfortably
CANVAS_W, CANVAS_H = 1120, 720
WORKBENCH_CANVAS_W, WORKBENCH_CANVAS_H = 700, 380


def discover_strict_deps(source_dir: Path = LIBRARIES_DIR) -> dict[str, list[str]]:
    """Walk ``source_dir/*/pyproject.toml`` and return chumicro-prefixed deps.

    Defaults to the libraries tree to preserve the original call shape; pass
    ``WORKBENCH_DIR`` for the host-side tools.
    """
    deps: dict[str, list[str]] = {}
    for package_dir in sorted(source_dir.iterdir()):
        if not package_dir.is_dir():
            continue
        pyproject = package_dir / "pyproject.toml"
        if not pyproject.is_file():
            continue
        text = pyproject.read_text()
        # Strip from `dependencies = [` to the closing `]`.
        marker = "dependencies = ["
        start = text.find(marker)
        if start == -1:
            deps[package_dir.name] = []
            continue
        end = text.find("]", start)
        block = text[start + len(marker) : end]
        chumicro_deps = []
        for raw_line in block.splitlines():
            line = raw_line.strip().strip(",").strip('"').strip("'")
            if not line.startswith("chumicro-"):
                continue
            # Strip PEP 508 version specifiers + environment markers so
            # "chumicro-deploy>=0.1.0" becomes "deploy".
            name = line.removeprefix("chumicro-")
            for separator in (">=", "<=", "==", "!=", "~=", ">", "<", ";", " ", "["):
                if separator in name:
                    name = name.split(separator, 1)[0]
            chumicro_deps.append(name)
        deps[package_dir.name] = chumicro_deps
    return deps


def edge_endpoints(
    source: str,
    destination: str,
    nodes: dict[str, tuple[int, int]] = NODES,
    node_w: int = NODE_W,
    node_h: int = NODE_H,
) -> tuple[float, float, float, float]:
    """Return (sx, sy, dx, dy) where the edge starts at the source's bottom
    edge and ends at the destination's top edge.  Both anchored to box
    centers in the perpendicular axis.
    """
    source_x, source_y = nodes[source]
    destination_x, destination_y = nodes[destination]
    source_cx = source_x + node_w / 2
    destination_cx = destination_x + node_w / 2
    if source_y < destination_y:
        # Source is above destination: line drops from source bottom
        # to destination top.
        return source_cx, source_y + node_h, destination_cx, destination_y
    # Source is below destination (rare here): flip.
    return source_cx, source_y, destination_cx, destination_y + node_h


def render_node(
    name: str,
    kind: str = "default",
    nodes: dict[str, tuple[int, int]] = NODES,
    node_w: int = NODE_W,
    node_h: int = NODE_H,
) -> str:
    """Box + label for one package."""
    box_x, box_y = nodes[name]
    return (
        f'  <g class="node {kind}">\n'
        f'    <rect x="{box_x}" y="{box_y}" width="{node_w}" height="{node_h}" '
        f'rx="6" ry="6" />\n'
        f'    <text x="{box_x + node_w / 2}" y="{box_y + node_h / 2 + 5}" '
        f'text-anchor="middle">chumicro-{name}</text>\n'
        f'  </g>'
    )


def render_edge(
    source: str,
    destination: str,
    dashed: bool,
    nodes: dict[str, tuple[int, int]] = NODES,
    node_w: int = NODE_W,
    node_h: int = NODE_H,
) -> str:
    """One arrow from source's bottom to destination's top."""
    sx, sy, dx, dy = edge_endpoints(source, destination, nodes, node_w, node_h)
    css_class = "edge-di" if dashed else "edge-strict"
    return (
        f'  <line x1="{sx}" y1="{sy}" x2="{dx}" y2="{dy}" '
        f'class="{css_class}" marker-end="url(#arrow-{"di" if dashed else "strict"})" />'
    )


def render_svg(
    strict: dict[str, list[str]],
    di: dict[str, list[str]],
    nodes: dict[str, tuple[int, int]] = NODES,
    standalone: set[str] = frozenset({"compat"}),
    node_w: int = NODE_W,
    node_h: int = NODE_H,
    canvas_w: int = CANVAS_W,
    canvas_h: int = CANVAS_H,
    row_labels: list[tuple[str, int, int]] = (
        ("Services",        20,  50),
        ("Building blocks", 20, 290),
        ("Foundation",      20, 530),
        ("Standalone",      20, 630),
    ),
    legend_pos: tuple[int, int] = (740, 620),
) -> str:
    """Assemble the full SVG document."""
    edges_strict = [
        render_edge(source, destination, False, nodes, node_w, node_h)
        for source, targets in strict.items()
        for destination in targets
        if source in nodes and destination in nodes
    ]
    edges_di = [
        render_edge(source, destination, True, nodes, node_w, node_h)
        for source, targets in di.items()
        for destination in targets
        if source in nodes and destination in nodes
    ]

    nodes_kind = []
    for name in nodes:
        if name in standalone:
            nodes_kind.append(render_node(name, "standalone", nodes, node_w, node_h))
        else:
            nodes_kind.append(render_node(name, "default", nodes, node_w, node_h))

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {canvas_w} {canvas_h}" '
        f'width="{canvas_w}" height="{canvas_h}" '
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
        '  <!-- Background panel — keeps the graph readable on both light '
        'and dark GitHub themes (the SVG is rendered as a flat image and '
        'doesn\'t inherit the page background). -->',
        f'  <rect x="0" y="0" width="{canvas_w}" height="{canvas_h}" fill="#fafafa" />',
        '',
        '  <!-- Row labels -->',
        *[
            f'  <text x="{rx}" y="{ry}" class="row-label">{label}</text>'
            for label, rx, ry in row_labels
        ],
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
        '  <!-- Package boxes -->',
        '  <g>',
        *nodes_kind,
        '  </g>',
        '',
        '  <!-- Legend -->',
        f'  <g transform="translate({legend_pos[0]}, {legend_pos[1]})">',
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


def render_workbench_svg(
    strict: dict[str, list[str]],
    di: dict[str, list[str]] = WORKBENCH_DI_DEPS,
) -> str:
    """Workbench dependency graph: composers above, primitives below."""
    return render_svg(
        strict,
        di,
        nodes=WORKBENCH_NODES,
        standalone=WORKBENCH_STANDALONE,
        node_w=WORKBENCH_NODE_W,
        node_h=NODE_H,
        canvas_w=WORKBENCH_CANVAS_W,
        canvas_h=WORKBENCH_CANVAS_H,
        row_labels=(
            ("Composers",  20,  50),
            ("Primitives", 20, 230),
            ("Standalone", 410, 230),
        ),
        legend_pos=(30, 320),
    )


def _display_path(path: Path) -> str:
    """Format a path for human-readable error / status messages.

    Falls back to the absolute path when *path* isn't under the repo
    root (e.g. when tests monkey-patch ``SVG_OUT`` to a tmp_path).
    """
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _check_or_write(
    rendered: str, out_path: Path, *, check: bool, label: str
) -> int:
    """Either compare *rendered* against the committed SVG at *out_path*
    and return 0/1, or write it.  *label* is "library" / "workbench" for
    error messages."""
    if check:
        if not out_path.is_file():
            print(
                f"ERROR: {_display_path(out_path)} is missing.  "
                f"Run `python scripts/render_dep_graph.py` to generate it.",
                file=sys.stderr,
            )
            return 1
        if out_path.read_text() != rendered:
            print(
                f"ERROR: {_display_path(out_path)} is out of date.  "
                f"A {label} package's pyproject.toml deps changed but the "
                f"rendered SVG was not regenerated.  Run "
                f"`python scripts/render_dep_graph.py` and commit the result.",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {_display_path(out_path)} matches the current pyproject deps.")
        return 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered)
    print(f"wrote {_display_path(out_path)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render or verify the chumicro dependency graph SVGs.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Verify mode: re-render both graphs in memory, compare against "
            "the committed SVGs, exit 1 if either differs.  Runs in preflight "
            "so a contributor who changes a package's [project].dependencies "
            "without re-rendering sees the failure in CI."
        ),
    )
    args = parser.parse_args(argv)

    library_strict = discover_strict_deps()
    library_svg = render_svg(library_strict, DI_DEPS)

    workbench_strict = discover_strict_deps(WORKBENCH_DIR)
    workbench_svg = render_workbench_svg(workbench_strict, WORKBENCH_DI_DEPS)

    library_status = _check_or_write(
        library_svg, SVG_OUT, check=args.check, label="library"
    )
    workbench_status = _check_or_write(
        workbench_svg, WORKBENCH_SVG_OUT, check=args.check, label="workbench"
    )

    if args.check:
        return library_status or workbench_status

    print()
    print("Library strict deps (auto-discovered from pyproject.toml):")
    for source, targets in sorted(library_strict.items()):
        if targets:
            print(f"  chumicro-{source} -> {', '.join('chumicro-' + name for name in targets)}")
    print()
    print("Library DI / typical-wiring deps (hand-curated):")
    for source, targets in sorted(DI_DEPS.items()):
        print(f"  chumicro-{source} -> {', '.join('chumicro-' + name for name in targets)}")
    print()
    print("Workbench strict deps (auto-discovered from pyproject.toml):")
    for source, targets in sorted(workbench_strict.items()):
        if targets:
            print(f"  chumicro-{source} -> {', '.join('chumicro-' + name for name in targets)}")
    print()
    print("Workbench DI / soft-import deps (hand-curated):")
    for source, targets in sorted(WORKBENCH_DI_DEPS.items()):
        print(f"  chumicro-{source} -> {', '.join('chumicro-' + name for name in targets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
