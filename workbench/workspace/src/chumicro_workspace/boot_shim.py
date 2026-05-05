"""Boot-shim deploy pattern per Decision 0029 §3.

The boot shim layer is a fixed set of files written onto the
device alongside the project's app code:

* ``/code.py`` (CP) or ``/main.py`` (MP) — two-line bootstrapper
  that imports :mod:`workspace_runtime` and calls ``boot()``.
* ``/active.py`` — names the active project
  (``PROJECT_NAME = "<dotted-name>"``).  Nested projects use the
  dotted form (``"upstairs.bedroom_sensor"``) so
  ``projects.<PROJECT_NAME>.app`` resolves directly via Python's
  import machinery.
* ``/lib/workspace_runtime/__init__.py`` — the on-device boot
  module shipped as a payload from this package.
* ``/lib/projects/__init__.py`` + one ``__init__.py`` per
  namespace level under the project — package markers that let
  ``projects.<seg1>.<seg2>...<project>.app`` resolve.

The project's own files land at
``/lib/projects/<seg1>/<seg2>/.../<project>/`` (rather than the top-of-filesystem
layout the simpler :func:`project_directory_source` produces).  Single-project
shape only: the ``multi_project_boot_source`` / ``switch_source`` flow
from the original Phase 4a sketch was retired in Slice 7 of the
nested-projects-and-examples workstream — multi-project staging blew the
flash budget on Decision 0015 minimum boards and the "instant switch"
pitch wasn't worth the cost.  See ``plans/next-up.md`` for the
follow-on workstream that replaces it with scoped diff-deploy.

Two pieces:

* :func:`load_workspace_runtime_payload` reads the on-device
  module out of the package's ``_payloads/`` directory.  Pure
  filesystem read — no network, no codegen.
* :func:`project_boot_source` produces a ``WithRuntimeConfig``-
  wrapped :class:`FileMapSource` that bundles the shim layer +
  the project's files at the right paths + the merged runtime-
  config msgpack.

The CLI ``deploy --boot-shim`` flag opts into this pattern;
default deploys still use the flat
:func:`project_directory_source` layout.  Opt-in because the boot
shim is workspace-runtime convention — workspaces / templates
that don't follow it (third-party templates per Decision 0032)
keep working unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from chumicro_deploy.runtime_marker import file_targets_runtime

from chumicro_workspace.deploy_source import (
    GENERATED_DIRNAME,
    WithRuntimeConfig,
    find_project_config,
)

if TYPE_CHECKING:  # pragma: no cover — type-only
    from chumicro_workspace.workspace import WorkspaceLayout

#: On-device path of the boot module the shim imports.  Decision
#: 0029 §3's contract — every workspace template's ``code.py``
#: ends up calling :func:`workspace_runtime.boot`.
BOOT_MODULE_DEVICE_PATH = "/lib/workspace_runtime/__init__.py"

#: On-device path of the ``projects/`` namespace marker.  Empty file
#: that just makes ``projects`` an importable package on CP / MP.
PROJECTS_PACKAGE_INIT_DEVICE_PATH = "/lib/projects/__init__.py"

#: One-line ``code.py`` (CP) / ``main.py`` (MP) shim.  Contents
#: are stable across deploys — Decision 0029 §3 calls this out
#: explicitly: ``code.py — shipped by template; do not edit``.
SHIM_ENTRYPOINT_SOURCE = (
    "# Shipped by chumicro-workspace; do not edit.\n"
    "import workspace_runtime\n"
    "workspace_runtime.boot()\n"
)

#: Directory under :mod:`chumicro_workspace`'s package
#: tree where on-device payloads live.  Resolved at import time
#: so ``importlib.resources``-style access stays simple — we read
#: payload files directly from the wheel.
_PAYLOADS_DIR = Path(__file__).resolve().parent / "_payloads"

#: Filenames under ``projects/<name>/`` that are workspace-tooling
#: inputs, not runtime payload — same exclusions
#: :func:`project_directory_source` applies.
_PROJECT_HOST_ONLY_NAMES: frozenset[str] = frozenset(
    {"config.toml", "config.yml", "config.yaml"},
)

#: Cache directory + workspace-tooling-reserved names skipped on
#: the project walk.  Mirrors
#: ``chumicro_deploy.DirectorySource.DEFAULT_EXCLUDED`` so the
#: behavior matches what users see with the simpler source.
_DEFAULT_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {"__pycache__", ".DS_Store", ".git", ".pytest_cache", ".mypy_cache",
     GENERATED_DIRNAME},
)


# ---------------------------------------------------------------------------
# Nested-name helpers
# ---------------------------------------------------------------------------


def _dotted_project_name(project_name: str) -> str:
    """Return *project_name* in dotted form.

    Accepts dotted (``"upstairs.bedroom_sensor"``) or slash
    (``"upstairs/bedroom_sensor"``) input.  The dotted form is
    written into ``/active.py`` because ``workspace_runtime.boot``
    constructs ``projects.<PROJECT_NAME>.app`` via string concatenation.
    """
    return project_name.replace("/", ".")


def _project_segments(project_name: str) -> tuple[str, ...]:
    """Split *project_name* on ``.`` / ``/`` into per-namespace segments."""
    return tuple(_dotted_project_name(project_name).split("."))


def _device_project_dir(project_name: str) -> str:
    """Return the on-device dir prefix for *project_name*'s payload files.

    Single-segment ``"weather"`` → ``"/lib/projects/weather"``;
    nested ``"garage/sensors/door_open"`` →
    ``"/lib/projects/garage/sensors/door_open"``.
    """
    return "/lib/projects/" + "/".join(_project_segments(project_name))


def _namespace_init_paths(project_name: str) -> list[str]:
    """Return ``__init__.py`` device paths for every level above the project.

    Includes the project's own ``/lib/projects/<...>/<project>/__init__.py``
    leaf; excludes ``/lib/projects/__init__.py`` (caller adds it via
    :data:`PROJECTS_PACKAGE_INIT_DEVICE_PATH`).  Single-segment names
    return one path; an N-segment dotted name returns N paths.
    """
    segments = _project_segments(project_name)
    return [
        "/lib/projects/" + "/".join(segments[:depth]) + "/__init__.py"
        for depth in range(1, len(segments) + 1)
    ]


# ---------------------------------------------------------------------------
# Static file helpers
# ---------------------------------------------------------------------------


def load_workspace_runtime_payload() -> bytes:
    """Return the bytes of the on-device ``workspace_runtime`` module.

    Reads ``_payloads/workspace_runtime/__init__.py`` from this
    package's source tree.  The file is shipped in the wheel under
    the same path so installed users get the same bytes as
    in-repo developers.

    Raises:
        FileNotFoundError: When the payload is missing — indicates
            a broken install, not user error.
    """
    payload_path = _PAYLOADS_DIR / "workspace_runtime" / "__init__.py"
    if not payload_path.is_file():
        raise FileNotFoundError(
            "workspace_runtime payload missing at "
            f"{payload_path} — chumicro-workspace install "
            "may be broken; reinstall the package.",
        )
    return payload_path.read_bytes()


def build_active_py(project_name: str) -> str:
    """Return the ``active.py`` body that names *project_name*.

    Single-line module; ``workspace_runtime.boot()`` reads
    ``PROJECT_NAME`` from it.  Header comment guards the file
    against well-meaning user edits — the host overwrites
    ``active.py`` on every deploy.

    *project_name* is normalised to dotted form before being written
    so nested-project names (passed in either dotted or slash form)
    end up as the import-shaped ``"upstairs.bedroom_sensor"`` that
    :func:`workspace_runtime.boot` concatenates into
    ``projects.<PROJECT_NAME>.app``.
    """
    dotted = _dotted_project_name(project_name)
    return (
        "# Shipped by chumicro-workspace; rewritten on each deploy.\n"
        f"PROJECT_NAME = \"{dotted}\"\n"
    )


def boot_shim_files(
    *,
    project_name: str,
    entrypoint_filename: str = "code.py",
) -> dict[str, bytes]:
    """Return the static "shim layer" file map.

    Includes the entrypoint shim (``code.py`` / ``main.py``),
    ``active.py``, the on-device ``workspace_runtime`` module,
    the ``projects/`` package init, and one empty ``__init__.py`` for
    every namespace level beneath ``projects/`` down to and including
    the project's own directory.  The project's own files are NOT
    included here — :func:`project_boot_source` adds them.

    Args:
        project_name: Active project name (bare, slash, or dotted form).
            Written into ``active.py`` and used to construct the
            namespace ``__init__.py`` paths.
        entrypoint_filename: ``"code.py"`` for CircuitPython,
            ``"main.py"`` for MicroPython.

    Returns:
        Path → bytes map ready to merge into a deploy file map.
    """
    files: dict[str, bytes] = {
        f"/{entrypoint_filename}": SHIM_ENTRYPOINT_SOURCE.encode("utf-8"),
        "/active.py": build_active_py(project_name).encode("utf-8"),
        BOOT_MODULE_DEVICE_PATH: load_workspace_runtime_payload(),
        PROJECTS_PACKAGE_INIT_DEVICE_PATH: b"",
    }
    for init_path in _namespace_init_paths(project_name):
        files[init_path] = b""
    return files


def _walk_project_files(
    project_dir: Path,
    *,
    project_name: str,
    extra_excluded: Iterable[str] = (),
    target_runtime: str | None = None,
) -> dict[str, bytes]:
    """Walk *project_dir* and return ``/lib/projects/<...>/<name>/...`` → bytes.

    Skips ``config.{toml,yml,yaml}`` (host-only), ``_generated/``
    (deploy artifacts), and the usual cache / dotfile noise.
    *extra_excluded* augments the skip set.  *project_name* drives the
    on-device prefix via :func:`_device_project_dir` so nested project
    names produce nested paths.

    Decision 0044 — when *target_runtime* is set, ``.py`` files
    carrying a ``__chumicro_runtimes__`` marker for a different
    runtime are dropped before they reach the device.
    """
    excluded = _DEFAULT_EXCLUDED_DIRS | set(extra_excluded)
    device_prefix = _device_project_dir(project_name)
    collected: dict[str, bytes] = {}
    for source_path in sorted(project_dir.rglob("*")):
        if not source_path.is_file():
            continue
        relative = source_path.relative_to(project_dir)
        parts = relative.parts
        if any(part in excluded for part in parts):
            continue
        if relative.name in _PROJECT_HOST_ONLY_NAMES:
            continue
        if source_path.suffix == ".py" and not file_targets_runtime(
            source_path, target_runtime=target_runtime,
        ):
            continue
        device_relative = "/".join(parts)
        device_path = f"{device_prefix}/{device_relative}"
        collected[device_path] = source_path.read_bytes()
    return collected


class _BootShimSource:
    """``FileSource``-shaped wrapper for the boot-shim deploy layout.

    Internal — :func:`project_boot_source` returns the public
    :class:`WithRuntimeConfig` wrapper around an instance.  Kept
    private because the boot-shim layout is convention, and the
    convention's externally-facing surface is the helper function.
    """

    def __init__(
        self,
        *,
        project_dir: Path,
        project_name: str,
        entrypoint_filename: str,
        extra_excluded: Iterable[str] = (),
        target_runtime: str | None = None,
    ) -> None:
        self._project_dir = project_dir
        self._project_name = project_name
        self._entrypoint_filename = entrypoint_filename
        self._extra_excluded = tuple(extra_excluded)
        self._target_runtime = target_runtime

    def files(self) -> dict[str, bytes]:
        """Combine shim layer + project files at their on-device paths."""
        files = boot_shim_files(
            project_name=self._project_name,
            entrypoint_filename=self._entrypoint_filename,
        )
        files.update(
            _walk_project_files(
                self._project_dir,
                project_name=self._project_name,
                extra_excluded=self._extra_excluded,
                target_runtime=self._target_runtime,
            ),
        )
        return files

    def entrypoint(self) -> str:
        """Return the on-device entrypoint path the runtime executes."""
        return f"/{self._entrypoint_filename}"


def project_boot_source(
    project_dir: Path,
    *,
    workspace: WorkspaceLayout,
    project_name: str | None = None,
    entrypoint_filename: str = "code.py",
    workspace_yaml: Path | None = None,
    extra_excluded: Iterable[str] = (),
    target_runtime: str | None = None,
) -> WithRuntimeConfig:
    """Build a deploy-ready ``FileSource`` using the boot-shim layout.

    Bundles the static shim layer (entrypoint + ``active.py`` +
    ``workspace_runtime`` payload + namespace ``__init__.py`` markers)
    with the project's own files (under
    ``/lib/projects/<...>/<project>/``) and the merged runtime-config
    msgpack (via :class:`WithRuntimeConfig`).

    Args:
        project_dir: Filesystem path to the project directory.  May be
            nested (``projects/garage/sensors/door_open/``); the
            on-device layout follows the same nesting.
        workspace: Resolved :class:`WorkspaceLayout`.  Used to
            locate ``workspace.yml`` defaults when *workspace_yaml* is
            ``None``.
        project_name: Bare, slash, or dotted name for the active project.
            Required for nested layouts (the directory's basename
            alone loses the namespace prefix).  Defaults to
            ``project_dir.name`` for flat layouts.
        entrypoint_filename: ``"code.py"`` for CP, ``"main.py"``
            for MP.  Decides the host-side filename for the shim
            stub written at the device root.
        workspace_yaml: Override ``workspace_yaml`` path.
        extra_excluded: Additional filename / directory names to
            skip on the project walk.
        target_runtime: Decision 0044 — when set, ``.py`` files in
            the project directory whose ``__chumicro_runtimes__`` marker
            excludes this runtime are dropped.  ``None`` (the default)
            preserves the prior behavior; the workspace ``deploy``
            CLI fills this in from the device's runtime.

    Raises:
        FileNotFoundError: When *project_dir* contains no
            recognized config file.
    """
    if workspace_yaml is None:
        workspace_yaml = workspace.workspace_yaml
    resolved_name = project_name if project_name is not None else project_dir.name

    inner = _BootShimSource(
        project_dir=project_dir,
        project_name=resolved_name,
        entrypoint_filename=entrypoint_filename,
        extra_excluded=extra_excluded,
        target_runtime=target_runtime,
    )
    return WithRuntimeConfig(
        inner,
        workspace_yaml=workspace_yaml,
        project_config=find_project_config(project_dir),
        output_path=project_dir / GENERATED_DIRNAME / "runtime_config.msgpack",
    )


# ---------------------------------------------------------------------------
# Boot-shim + import-graph composition (gap 5 of the workspace-template
# dev-and-regular-mode-gaps audit)
# ---------------------------------------------------------------------------


class _BootShimWithImportGraphSource:
    """Combine the boot-shim file map with import-graph-discovered libraries.

    Internal — :func:`project_boot_with_import_graph_source` returns
    the public :class:`WithRuntimeConfig` wrapper around an instance.

    The boot-shim source ships the entrypoint shim, ``active.py``, the
    on-device ``workspace_runtime`` payload, namespace ``__init__.py``
    markers, and the project's own files under
    ``/lib/projects/<...>/<project>/``.  The import-graph source walks
    the project's host-side entrypoint (``app.py`` by default), follows
    every reachable ``import`` / ``from … import``, and ships each
    resolved module under ``/lib/<package>/...``.

    The two contributions land at disjoint device paths *except* for
    the project-local modules the import-graph walker reaches via
    ``project_dir`` as a search path (so it can follow project-internal
    relative imports and keep walking through them to libraries those
    sub-modules pull in).  Those modules are already shipped by the
    boot-shim under ``/lib/projects/<...>/<project>/``; the import-graph's
    parallel ``/lib/<basename>.py`` landing is dead weight on the device
    (never imported, since the runtime resolves modules through the
    ``projects.<name>`` package).  We drop them post-hoc.

    Boot-shim wins on any other overlap (entrypoint, ``active.py``,
    ``/lib/workspace_runtime/``, namespace ``__init__.py`` markers).
    """

    def __init__(
        self,
        *,
        boot_shim_inner: _BootShimSource,
        import_graph_inner: object,  # chumicro_deploy.ImportGraphSource
        project_dir: Path,
    ) -> None:
        self._boot = boot_shim_inner
        self._graph = import_graph_inner
        self._project_dir = project_dir

    def _project_local_device_paths(self) -> set[str]:
        """Device paths the import-graph walker would assign to project-local files.

        Mirrors :class:`chumicro_deploy.ImportGraphSource`'s
        ``resource_prefix=/lib`` + ``relative_path_from_search_path``
        rule for files under ``project_dir`` (which the combined
        builder adds as the first search path so the walker can follow
        project-internal relative imports).
        """
        local: set[str] = set()
        for source_path in self._project_dir.rglob("*.py"):
            if not source_path.is_file():
                continue
            relative = source_path.relative_to(self._project_dir).as_posix()
            local.add(f"/lib/{relative}")
        return local

    def files(self) -> dict[str, bytes]:
        boot_files = self._boot.files()
        graph_files = self._graph.files()  # type: ignore[attr-defined]
        local_paths = self._project_local_device_paths()
        merged: dict[str, bytes] = {
            path: data for path, data in graph_files.items()
            if path not in local_paths
        }
        merged.update(boot_files)
        return merged

    def entrypoint(self) -> str:
        return self._boot.entrypoint()


def project_boot_with_import_graph_source(
    project_dir: Path,
    *,
    workspace: WorkspaceLayout,
    project_name: str | None = None,
    entrypoint_filename: str = "code.py",
    project_entrypoint: str = "app.py",
    workspace_yaml: Path | None = None,
    extra_excluded: Iterable[str] = (),
    target_runtime: str | None = None,
    extra_modules: list[str] | None = None,
    extra_search_paths: list[Path] | None = None,
) -> WithRuntimeConfig:
    """Boot-shim layout PLUS import-graph-discovered libraries.

    Use when a project authored for the boot-shim convention also
    needs library code (chumicro / shared / packages / library_sources
    overrides) shipped to the device.  Common case: dev mode with a
    sibling ``chumicro/`` checkout configured via ``chumicro-dev.toml``
    — without this composition, ``chumicro_*`` libraries the project
    imports never reach the board.

    Triggered from the CLI by ``deploy --boot-shim --import-graph``.
    The two flags are no longer mutually exclusive.

    Args:
        project_dir: Project directory (same shape as for
            :func:`project_boot_source`).
        workspace: Resolved :class:`WorkspaceLayout`.
        project_name: Active project name (bare / slash / dotted).
            Defaults to ``project_dir.name``.
        entrypoint_filename: Device-side shim entrypoint —
            ``"code.py"`` (CP) or ``"main.py"`` (MP).  The shim is
            written at ``/<entrypoint_filename>`` and calls
            ``workspace_runtime.boot()``.
        project_entrypoint: Host-side filename inside *project_dir*
            that the import-graph walker uses as its starting point.
            Defaults to ``"app.py"`` — the boot-shim convention's
            entrypoint module.
        workspace_yaml: Override ``workspace.yml`` path.
        extra_excluded: Additional filename / directory names to
            skip on the project walk.
        target_runtime: Decision 0044 — forwarded to both inner
            sources so wrong-runtime files are dropped on either side.
        extra_modules: Dotted module names to force-include even when
            AST can't see them.  Forwarded to
            :class:`chumicro_deploy.ImportGraphSource`.
        extra_search_paths: Additional directories prepended to the
            workspace-derived search-path tail (after ``project_dir``).

    Raises:
        FileNotFoundError: When *project_dir* contains no recognized
            config file or *project_entrypoint* doesn't exist under it.
        WorkspaceConfigError: When ``workspace.yml``'s
            ``library_sources:`` block is malformed.
    """
    from chumicro_deploy import ImportGraphSource  # noqa: PLC0415

    from chumicro_workspace.import_graph import (  # noqa: PLC0415
        build_search_paths,
        read_library_sources,
    )

    if workspace_yaml is None:
        workspace_yaml = workspace.workspace_yaml
    resolved_name = project_name if project_name is not None else project_dir.name

    boot_inner = _BootShimSource(
        project_dir=project_dir,
        project_name=resolved_name,
        entrypoint_filename=entrypoint_filename,
        extra_excluded=extra_excluded,
        target_runtime=target_runtime,
    )

    project_entrypoint_path = project_dir / project_entrypoint
    if not project_entrypoint_path.is_file():
        raise FileNotFoundError(
            f"project entrypoint {project_entrypoint_path} not found "
            f"(boot-shim+import-graph composition expects {project_entrypoint!r}; "
            f"pass project_entrypoint to override)",
        )

    library_sources = read_library_sources(workspace_yaml)
    search_paths = [project_dir]
    search_paths.extend(
        build_search_paths(
            workspace,
            library_sources_override=library_sources,
            extra_search_paths=extra_search_paths,
        ),
    )
    graph_inner = ImportGraphSource(
        project_entrypoint_path,
        search_paths=search_paths,
        extra_modules=extra_modules,
        # device_entrypoint of the graph walk; the boot-shim's shim at
        # ``/<entrypoint_filename>`` overrides it in the merged file map.
        device_entrypoint=f"/{entrypoint_filename}",
        resource_prefix="/lib",
        target_runtime=target_runtime,
    )

    combined = _BootShimWithImportGraphSource(
        boot_shim_inner=boot_inner,
        import_graph_inner=graph_inner,
        project_dir=project_dir,
    )

    # Library roots derived from the import-graph search paths so
    # ``WithRuntimeConfig`` validates the merged config against
    # each library's manifest before writing the msgpack.  See
    # ``chumicro_workspace.config_manifest`` and Phase 2 of the
    # unification workstream.
    from chumicro_workspace.config_manifest import (  # noqa: PLC0415
        find_library_roots,
    )
    library_roots = find_library_roots(search_paths)

    return WithRuntimeConfig(
        combined,
        workspace_yaml=workspace_yaml,
        project_config=find_project_config(project_dir),
        output_path=project_dir / GENERATED_DIRNAME / "runtime_config.msgpack",
        library_roots=library_roots,
    )
