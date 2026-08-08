"""Tests for render_dep_graph.py — dependency-graph SVG generation + check mode."""

from __future__ import annotations

from render_dep_graph import (
    DI_DEPS,
    NODES,
    WORKBENCH_DI_DEPS,
    WORKBENCH_DIR,
    WORKBENCH_NODES,
    discover_strict_deps,
    edge_endpoints,
    main,
    render_svg,
    render_workbench_svg,
)


class TestDiscoverStrictDeps:
    """The auto-discover walker reads each library's pyproject.toml."""

    def test_returns_one_entry_per_library(self):
        """Every library directory gets an entry, even if its dep list is empty."""
        deps = discover_strict_deps()
        assert "timing" in deps
        assert "compat" in deps
        assert "sockets" in deps

    def test_no_chumicro_deps_for_leaf_libraries(self):
        """Libraries with no chumicro deps return an empty list."""
        deps = discover_strict_deps()
        assert deps["timing"] == []
        assert deps["compat"] == []
        assert deps["msgpack"] == []
        assert deps["sockets"] == []

    def test_picks_up_chumicro_prefixed_deps(self):
        """A library with `chumicro-foo` in dependencies surfaces `foo`."""
        deps = discover_strict_deps()
        assert "timing" in deps["runner"]
        assert "msgpack" in deps["config"]
        assert "msgpack" in deps["kvstore"]

    def test_strips_chumicro_prefix_from_dep_names(self):
        """Returned names are the library name without the `chumicro-` prefix."""
        deps = discover_strict_deps()
        for source, targets in deps.items():
            for target in targets:
                assert not target.startswith("chumicro-"), (
                    f"{source} -> {target} should be stripped of `chumicro-` prefix"
                )

    def test_skips_non_chumicro_dependencies(self):
        """Third-party deps in pyproject (none currently) wouldn't surface."""
        # Indirect: every library that has deps has *only* chumicro-prefixed ones.
        deps = discover_strict_deps()
        assert "msgpack" not in deps["timing"]

    def test_strips_pep508_version_specifiers(self):
        """``chumicro-deploy>=0.1.0`` should surface as just ``deploy``."""
        # chumicro-pytest-device pins chumicro-deploy with a version specifier.
        deps = discover_strict_deps(WORKBENCH_DIR)
        assert deps["pytest-device"] == ["deploy", "workspace"], (
            f"version specifier leaked: {deps['pytest-device']!r}"
        )


class TestWorkbenchGraph:
    """Workbench dep graph is rendered from workbench/*/pyproject.toml."""

    def test_workbench_strict_deps_picked_up(self):
        deps = discover_strict_deps(WORKBENCH_DIR)
        assert "deploy" in deps["workspace"]
        assert "deploy" in deps["pytest-device"]
        assert deps["repl"] == []
        assert deps["deploy"] == []

    def test_workbench_svg_includes_every_node(self):
        deps = discover_strict_deps(WORKBENCH_DIR)
        svg = render_workbench_svg(deps, WORKBENCH_DI_DEPS)
        for package_name in WORKBENCH_NODES:
            assert f"chumicro-{package_name}" in svg, (
                f"workbench package {package_name} missing from rendered SVG"
            )

    def test_workbench_svg_marks_checks_as_standalone(self):
        deps = discover_strict_deps(WORKBENCH_DIR)
        svg = render_workbench_svg(deps, WORKBENCH_DI_DEPS)
        assert 'class="node standalone"' in svg
        assert ">chumicro-checks<" in svg

    def test_workbench_svg_renders_di_arrow_for_workspace_repl(self):
        """workspace → repl is a soft / lazy-import edge."""
        deps = discover_strict_deps(WORKBENCH_DIR)
        svg = render_workbench_svg(deps, WORKBENCH_DI_DEPS)
        # One DI arrow + one legend example = 2.
        assert svg.count('class="edge-di"') == 2


class TestEdgeEndpoints:
    """Edge geometry connects bottom-of-source to top-of-destination."""

    def test_drops_from_source_bottom_to_dest_top(self):
        """When source is above destination, edge starts at source bottom."""
        # runner is in the middle row, timing in the foundation row.
        sx, sy, dx, dy = edge_endpoints("runner", "timing")
        runner_x, runner_y = NODES["runner"]
        timing_x, timing_y = NODES["timing"]
        # Y-axis: source bottom edge.
        assert sy == runner_y + 36  # NODE_H
        # Y-axis: destination top edge.
        assert dy == timing_y
        # X-axis: both at box centers.
        assert sx == runner_x + 65  # NODE_W / 2
        assert dx == timing_x + 65


class TestRenderSvg:
    """The SVG output contains every library box and every declared edge."""

    def test_includes_every_node(self):
        deps = discover_strict_deps()
        svg = render_svg(deps, DI_DEPS)
        for library_name in NODES:
            assert f"chumicro-{library_name}" in svg, (
                f"library {library_name} missing from rendered SVG"
            )

    def test_includes_one_edge_per_strict_dep(self):
        """One ``class="edge-strict"`` per actual dep edge, plus one for the
        legend's example line — total = deps + 1.
        """
        deps = discover_strict_deps()
        svg = render_svg(deps, DI_DEPS)
        strict_edge_count = svg.count('class="edge-strict"')
        expected = sum(len(targets) for targets in deps.values()) + 1  # +1 legend
        assert strict_edge_count == expected

    def test_includes_one_edge_per_di_dep(self):
        """One ``class="edge-di"`` per actual DI edge, plus one for the
        legend's example line — total = di edges + 1.
        """
        deps = discover_strict_deps()
        svg = render_svg(deps, DI_DEPS)
        di_edge_count = svg.count('class="edge-di"')
        expected = sum(len(targets) for targets in DI_DEPS.values()) + 1  # +1 legend
        assert di_edge_count == expected

    def test_renders_legend_section(self):
        deps = discover_strict_deps()
        svg = render_svg(deps, DI_DEPS)
        assert "Legend" in svg
        assert "strict dependency" in svg
        assert "typical wiring" in svg

    def test_marks_standalone_libraries(self):
        """A library with no edges gets the standalone CSS class."""
        deps = discover_strict_deps()
        svg = render_svg(deps, DI_DEPS)
        # Each standalone library appears in a `node standalone` group.
        for standalone_name in ("compat",):
            assert 'class="node standalone"' in svg
            assert f">chumicro-{standalone_name}<" in svg


class TestCheckMode:
    """`--check` exits 1 if the committed SVG is out of date."""

    def test_check_passes_when_committed_svg_matches(self, capsys):
        """The committed SVG should be in sync with the current pyprojects."""
        result = main(["--check"])
        assert result == 0
        captured = capsys.readouterr()
        assert "matches the current pyproject deps" in captured.out

    def test_check_fails_when_svg_is_missing(self, monkeypatch, tmp_path, capsys):
        """If the committed SVG file doesn't exist, --check reports it."""
        import render_dep_graph

        missing_path = tmp_path / "missing.svg"
        monkeypatch.setattr(render_dep_graph, "SVG_OUT", missing_path)
        result = main(["--check"])
        assert result == 1
        captured = capsys.readouterr()
        assert "missing" in captured.err

    def test_check_fails_when_svg_diverges(self, monkeypatch, tmp_path, capsys):
        """If the SVG on disk differs from what would be rendered, --check fails."""
        import render_dep_graph

        stale_path = tmp_path / "stale.svg"
        stale_path.write_text("<svg>this is stale</svg>")
        monkeypatch.setattr(render_dep_graph, "SVG_OUT", stale_path)
        result = main(["--check"])
        assert result == 1
        captured = capsys.readouterr()
        assert "out of date" in captured.err


class TestRegenerateMode:
    """Bare `python scripts/render_dep_graph.py` (no flags) regenerates."""

    def test_regenerate_writes_svg(self, monkeypatch, tmp_path):
        import render_dep_graph

        out_path = tmp_path / "subdir" / "graph.svg"
        monkeypatch.setattr(render_dep_graph, "SVG_OUT", out_path)
        result = main([])
        assert result == 0
        assert out_path.is_file()
        assert out_path.read_text().startswith("<svg")
