"""Boot-shim deploy pattern.

The boot shim layer is a tiny synthesized entrypoint written onto the
device alongside the project's app code:

* ``/code.py`` (CP) or ``/main.py`` (MP) — three-line bootstrapper
  that imports the project's ``app.run`` and calls it.

The project's own files (``app.py``, helper modules) land at the
device root.  ``app.py`` exports ``run()``; the synthesized shim
calls it.  No ``active.py``, no ``/lib/workspace_runtime/`` payload,
no ``/lib/projects/<name>/`` namespace — chumicro is one-project-per-
board.  Switch to a different project by redeploying.

Two pieces:

* :func:`boot_shim_files` returns the synthesized shim file
  (a single entry — the runtime-matching entrypoint).
* :func:`project_boot_source` produces a ``WithRuntimeConfig``-
  wrapped source that bundles the shim + the project's files at
  the device root + the merged runtime-config msgpack.

The CLI ``deploy --boot-shim`` flag (and the auto-detected default
when a project ships ``app.py`` with ``run()`` and no
``code.py``/``main.py``) opts into this pattern.
"""

from __future__ import annotations

import ast
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

#: Three-line ``code.py`` (CP) / ``main.py`` (MP) shim.  Imports
#: the project's ``app.run`` and calls it.  The shim is shipped by
#: chumicro-deploy; users should not edit it (it gets overwritten
#: on every deploy).
SHIM_ENTRYPOINT_SOURCE = (
    "# Shipped by chumicro-deploy; do not edit.\n"
    "from app import run as _run\n"
    "_run()\n"
)

#: Filenames under ``projects/<name>/`` that are workspace-tooling
#: inputs, not runtime payload — same exclusions
#: :func:`project_directory_source` applies.
_PROJECT_HOST_ONLY_NAMES: frozenset[str] = frozenset(
    {"config.toml", "config.yml", "config.yaml"},
)

#: Filenames the synthesised shim owns at the device root.  Excluded
#: from the project walk so a stray ``code.py`` / ``main.py`` in the
#: project directory (left over from a prior plain-mode deploy, or
#: the test fixture that seeds both) doesn't fight the shim for the
#: runtime entrypoint.  Plain-mode deploys (no shim) ship these
#: through the flat-layout walker instead — see
#: :func:`project_directory_source`.
_SHIM_OWNED_FILENAMES: frozenset[str] = frozenset({"code.py", "main.py"})

#: Cache directory + workspace-tooling-reserved names skipped on
#: the project walk.  Mirrors
#: ``chumicro_deploy.DirectorySource.DEFAULT_EXCLUDED`` so the
#: behavior matches what users see with the simpler source.
_DEFAULT_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {"__pycache__", ".DS_Store", ".git", ".pytest_cache", ".mypy_cache",
     GENERATED_DIRNAME},
)


# ---------------------------------------------------------------------------
# Project-shape detection
# ---------------------------------------------------------------------------


def project_app_exports_run(project_dir: Path) -> bool:
    """Return ``True`` when ``project_dir/app.py`` defines a top-level ``run``.

    AST-based check — does not import ``app.py``, so a syntax error
    in the project doesn't crash detection.  Recognises both
    ``def run(...)`` and ``async def run(...)``.  Returns ``False``
    for ``app.py`` missing, syntax errors, or no top-level ``run``.

    Used by :func:`chumicro_workspace.cli._cmd_deploy`'s auto-detect
    pass: when the project ships ``app.py`` with ``run()`` and no
    runtime-specific entrypoint (``code.py`` / ``main.py``), boot-
    shim mode is the right default.
    """
    app_py = project_dir / "app.py"
    if not app_py.is_file():
        return False
    try:
        tree = ast.parse(app_py.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "run":
                return True
    return False


# ---------------------------------------------------------------------------
# Static file helpers
# ---------------------------------------------------------------------------


def boot_shim_files(
    *,
    entrypoint_filename: str = "code.py",
) -> dict[str, bytes]:
    """Return the synthesized shim file map (a single entry).

    The shim is a three-line module that imports the project's
    ``app.run`` and calls it.  Lands at ``/<entrypoint_filename>``
    on the device — ``/code.py`` for CircuitPython, ``/main.py``
    for MicroPython.  Only the runtime-matching file is synthesized;
    the deployer doesn't speculatively ship both.

    Args:
        entrypoint_filename: ``"code.py"`` for CircuitPython,
            ``"main.py"`` for MicroPython.

    Returns:
        Path → bytes map ready to merge into a deploy file map.
        A single entry — kept dict-shaped so the merge interface
        stays uniform with the other source builders.
    """
    return {
        f"/{entrypoint_filename}": SHIM_ENTRYPOINT_SOURCE.encode("utf-8"),
    }


def _walk_project_files(
    project_dir: Path,
    *,
    extra_excluded: Iterable[str] = (),
    target_runtime: str | None = None,
) -> dict[str, bytes]:
    """Walk *project_dir* and return ``/<relative>`` → bytes at device root.

    Skips ``config.{toml,yml,yaml}`` (host-only), ``_generated/``
    (deploy artifacts), and the usual cache / dotfile noise.
    *extra_excluded* augments the skip set.

    Project files land at the device root (``app.py`` → ``/app.py``,
    ``helpers.py`` → ``/helpers.py``).  Under one-project-per-board,
    the device's namespace is the project's namespace; no
    ``/lib/projects/<name>/`` prefix.

    When *target_runtime* is set, ``.py`` files carrying a
    ``__chumicro_runtimes__`` marker for a different runtime are
    dropped before they reach the device.
    """
    excluded = _DEFAULT_EXCLUDED_DIRS | set(extra_excluded)
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
        # The synthesised shim owns ``/code.py`` and ``/main.py`` at the
        # device root — exclude any project-side copies from the walk.
        if len(parts) == 1 and relative.name in _SHIM_OWNED_FILENAMES:
            continue
        if source_path.suffix == ".py" and not file_targets_runtime(
            source_path, target_runtime=target_runtime,
        ):
            continue
        device_relative = "/".join(parts)
        device_path = f"/{device_relative}"
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
        entrypoint_filename: str,
        extra_excluded: Iterable[str] = (),
        target_runtime: str | None = None,
    ) -> None:
        self._project_dir = project_dir
        self._entrypoint_filename = entrypoint_filename
        self._extra_excluded = tuple(extra_excluded)
        self._target_runtime = target_runtime

    def files(self) -> dict[str, bytes]:
        """Combine shim + project files at their on-device paths."""
        files = boot_shim_files(
            entrypoint_filename=self._entrypoint_filename,
        )
        files.update(
            _walk_project_files(
                self._project_dir,
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
    entrypoint_filename: str = "code.py",
    workspace_yaml: Path | None = None,
    extra_excluded: Iterable[str] = (),
    target_runtime: str | None = None,
) -> WithRuntimeConfig:
    """Build a deploy-ready ``FileSource`` using the boot-shim layout.

    Bundles the synthesized entrypoint shim with the project's own
    files (at the device root) and the merged runtime-config msgpack
    (via :class:`WithRuntimeConfig`).

    Args:
        project_dir: Filesystem path to the project directory.
        workspace: Resolved :class:`WorkspaceLayout`.  Used to
            locate ``workspace.yml`` defaults when *workspace_yaml* is
            ``None``.
        entrypoint_filename: ``"code.py"`` for CP, ``"main.py"``
            for MP.  Decides the host-side filename for the shim
            stub written at the device root.
        workspace_yaml: Override ``workspace_yaml`` path.
        extra_excluded: Additional filename / directory names to
            skip on the project walk.
        target_runtime: When set, ``.py`` files in the project
            directory whose ``__chumicro_runtimes__`` marker
            excludes this runtime are dropped.  ``None`` (the
            default) ships every file unfiltered; the workspace
            ``deploy`` CLI fills this in from the device's runtime.

    Raises:
        FileNotFoundError: When *project_dir* contains no
            recognized config file.
    """
    if workspace_yaml is None:
        workspace_yaml = workspace.workspace_yaml

    inner = _BootShimSource(
        project_dir=project_dir,
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
# Boot-shim + import-graph composition
# ---------------------------------------------------------------------------


class _BootShimWithImportGraphSource:
    """Combine the boot-shim file map with import-graph-discovered libraries.

    Internal — :func:`project_boot_with_import_graph_source` returns
    the public :class:`WithRuntimeConfig` wrapper around an instance.

    The boot-shim source ships the entrypoint shim and the project's
    own files at the device root.  The import-graph source walks the
    project's host-side entrypoint (``app.py`` by default), follows
    every reachable ``import`` / ``from … import``, and ships each
    resolved module under ``/lib/<package>/...``.

    The two contributions land at disjoint device paths *except* for
    the project-local modules the import-graph walker reaches via
    ``project_dir`` as a search path.  Those modules are already
    shipped by the boot-shim at the device root; the import-graph's
    parallel ``/lib/<basename>.py`` landing is dead weight (project
    code resolves at the device root, not under ``/lib/``).  We drop
    them post-hoc.

    Boot-shim wins on any other overlap (the entrypoint shim).
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
        project-internal relative imports).  These paths shadow the
        boot-shim's device-root placement and would be dead weight on
        the device — drop them from the import-graph contribution.
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

    Triggered from the CLI by ``deploy --boot-shim --import-graph``,
    or by the auto-detected default when a project ships
    ``app.py`` + ``run()`` and no ``code.py`` / ``main.py``.

    Args:
        project_dir: Project directory (same shape as for
            :func:`project_boot_source`).
        workspace: Resolved :class:`WorkspaceLayout`.
        entrypoint_filename: Device-side shim entrypoint —
            ``"code.py"`` (CP) or ``"main.py"`` (MP).  The shim is
            written at ``/<entrypoint_filename>`` and calls
            ``app.run()``.
        project_entrypoint: Host-side filename inside *project_dir*
            that the import-graph walker uses as its starting point.
            Defaults to ``"app.py"`` — the boot-shim convention's
            entrypoint module.
        workspace_yaml: Override ``workspace.yml`` path.
        extra_excluded: Additional filename / directory names to
            skip on the project walk.
        target_runtime: Forwarded to both inner sources so
            wrong-runtime files are dropped on either side.
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

    boot_inner = _BootShimSource(
        project_dir=project_dir,
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
