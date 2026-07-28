"""Boot-shim deploy layout: shim entrypoint + flat project files.

The boot shim is a three-line ``/code.py`` (CircuitPython) or
``/main.py`` (MicroPython) module synthesised by
chumicro-workspace.  It runs ``from app import run; run()``, so
every project that opts in ships an ``app.py`` exporting a
synchronous ``run()``.  ``app.py`` and any helper modules land at
the device root, alongside the merged ``/runtime_config.msgpack``.
One project per board: switch projects by redeploying.

Three public builders:

* :func:`boot_shim_files` returns the synthesised shim file map
  for the runtime-matching entrypoint.
* :func:`project_boot_source` wraps the shim plus flat project
  files in :class:`WithRuntimeConfig` so the msgpack rides the
  deploy.
* :func:`project_boot_with_import_graph_source` adds the
  import-graph contribution for projects that pull in workspace
  libraries.

Opt-in is automatic when a project ships ``app.py`` with a
top-level ``run()`` and no ``code.py`` / ``main.py``; the
``deploy --boot-shim`` CLI flag forces it.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from chumicro_deploy import file_targets_runtime

from chumicro_workspace.deploy_source import (
    GENERATED_DIRNAME,
    WithRuntimeConfig,
    wrap_with_runtime_config,
)

if TYPE_CHECKING:  # pragma: no cover - type-only
    from chumicro_workspace.workspace import WorkspaceLayout

#: Three-line ``code.py`` (CP) / ``main.py`` (MP) shim.  Imports
#: the project's ``app.run`` and calls it.  The shim is synthesized
#: by chumicro-workspace; users should not edit it (it gets
#: overwritten on every deploy).
SHIM_ENTRYPOINT_SOURCE = (
    "# Shipped by chumicro-workspace; do not edit.\n"
    "from app import run as _run\n"
    "_run()\n"
)

#: Filenames under ``projects/<name>/`` that are workspace-tooling
#: input, not runtime payload, and so are skipped on the device walk.
_PROJECT_HOST_ONLY_NAMES: frozenset[str] = frozenset({"project_config.toml"})

#: Filenames the synthesised shim owns at the device root.  Excluded
#: from the project walk so a stray ``code.py`` / ``main.py`` left
#: over from a prior plain-mode deploy doesn't fight the shim for the
#: runtime entrypoint.  Plain-mode deploys (no shim) ship these
#: through the flat-layout walker instead, see
#: :func:`project_directory_source`.
_SHIM_OWNED_FILENAMES: frozenset[str] = frozenset({"code.py", "main.py"})

#: Cache directory and workspace-tooling-reserved names skipped on
#: the project walk.  Same exclusion set as the simpler
#: ``DirectorySource`` so the behavior matches across sources.
_DEFAULT_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {"__pycache__", ".DS_Store", ".git", ".pytest_cache", ".mypy_cache",
     GENERATED_DIRNAME},
)


# ---------------------------------------------------------------------------
# Project-shape detection
# ---------------------------------------------------------------------------


def _top_level_run_node(project_dir: Path) -> ast.AST | None:
    """Return the AST node of ``app.py``'s top-level ``run`` def, or ``None``.

    AST-based: never imports the project, so a syntax error doesn't
    crash detection.  ``None`` when ``app.py`` is missing / unreadable
    / syntax-broken, or has no top-level ``run`` definition.  A ``run``
    defined inside a class is not top-level and doesn't count.
    """
    app_py = project_dir / "app.py"
    if not app_py.is_file():
        return None
    try:
        tree = ast.parse(app_py.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "run":
                return node
    return None


def project_app_exports_run(project_dir: Path) -> bool:
    """Return ``True`` when ``app.py`` defines a top-level synchronous ``run``.

    Only a plain ``def run(...)`` qualifies.  The shim calls ``run()``
    synchronously (``from app import run; run()``), so an
    ``async def run`` is not a usable entrypoint and returns
    ``False`` here.  :func:`project_app_exports_async_run`
    distinguishes the async case so callers can surface it as a
    clear failure instead of shipping a board that boots and
    silently does nothing.
    """
    return isinstance(_top_level_run_node(project_dir), ast.FunctionDef)


def project_app_exports_async_run(project_dir: Path) -> bool:
    """Return ``True`` when ``app.py``'s top-level ``run`` is ``async def``.

    The boot shim calls ``run()`` synchronously, so an ``async def
    run`` would evaluate to a coroutine that is created and
    immediately discarded.  The board boots and does nothing, with no
    traceback.  Detecting that case lets the deploy path surface it
    as a clear failure instead of letting it through.
    """
    return isinstance(_top_level_run_node(project_dir), ast.AsyncFunctionDef)


#: Modules whose ``reset()`` reboots the board: ``microcontroller`` on
#: CircuitPython, ``machine`` on MicroPython.
_HARD_RESET_MODULES: frozenset[str] = frozenset({"microcontroller", "machine"})


def _hard_reset_local_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Resolve the local names that reach a board-reset call in *tree*.

    Returns two sets: names for which ``<name>.reset()`` reboots the
    board, and names for which a bare ``<name>()`` reboots the board.
    The first is seeded with the module names ``microcontroller`` /
    ``machine`` and extended with each ``import ... as`` alias, so
    ``import machine as m`` adds ``m``.  The second collects
    ``from <module> import reset [as ...]`` bindings, so
    ``from microcontroller import reset as r`` adds ``r``.
    """
    module_names: set[str] = set(_HARD_RESET_MODULES)
    reset_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _HARD_RESET_MODULES:
                    module_names.add(alias.asname or alias.name)
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module in _HARD_RESET_MODULES
        ):
            for alias in node.names:
                if alias.name == "reset":
                    reset_names.add(alias.asname or "reset")
    return module_names, reset_names


def source_calls_hard_reset_at_top_level(source: str) -> int | None:
    """Line of a module-top-level board-reset call in *source*, or ``None``.

    The closure-scan companion to :func:`module_calls_hard_reset`: an
    imported module's top-level code runs at boot exactly like the
    entrypoint's, so a reset there crash-loops the board just the same.
    But a reset inside a ``def`` is the *recommended* pattern (called on
    a deliberate condition), so this walk descends into top-level
    ``if`` / ``try`` / loop / ``with`` blocks (they run at import) and
    prunes at any function or class body (those run only when called).
    Unreadable or unparseable source returns ``None``, because the deploy's
    own compile step reports those failures with better context.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    module_names, reset_names = _hard_reset_local_names(tree)
    hit_line = None
    stack = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
        ):
            continue
        if isinstance(node, ast.Call):
            callee = node.func
            named_reset = (
                isinstance(callee, ast.Attribute)
                and callee.attr == "reset"
                and isinstance(callee.value, ast.Name)
                and callee.value.id in module_names
            ) or (isinstance(callee, ast.Name) and callee.id in reset_names)
            if named_reset and (hit_line is None or node.lineno < hit_line):
                hit_line = node.lineno
        stack.extend(ast.iter_child_nodes(node))
    return hit_line


def module_calls_hard_reset(path: Path) -> int | None:
    """Return the line of a ``microcontroller.reset()`` / ``machine.reset()`` call in *path*, or ``None``.

    Either call reboots the board.  In a shipped boot entrypoint, which
    the board runs on every boot, a reset reboots the board, which
    re-runs the entrypoint and resets again: a crash loop that bricks
    the deploy cycle until the board is wiped.  Returns the first such
    call's line so the deploy path can refuse it.  Import aliases are
    resolved first, so ``import machine as m; m.reset()`` and
    ``from microcontroller import reset as r; r()`` are caught alongside
    the plain ``microcontroller.reset()`` / ``machine.reset()`` forms.
    A file that can't be read or parsed returns ``None``.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    module_names, reset_names = _hard_reset_local_names(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if (
            isinstance(callee, ast.Attribute)
            and callee.attr == "reset"
            and isinstance(callee.value, ast.Name)
            and callee.value.id in module_names
        ):
            return node.lineno
        if isinstance(callee, ast.Name) and callee.id in reset_names:
            return node.lineno
    return None


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
    on the device: ``/code.py`` for CircuitPython, ``/main.py``
    for MicroPython.  Only the runtime-matching file is synthesized.
    Both are never shipped speculatively.

    Args:
        entrypoint_filename: ``"code.py"`` for CircuitPython,
            ``"main.py"`` for MicroPython.

    Returns:
        Path → bytes map ready to merge into a deploy file map,
        a single entry kept dict-shaped to match the merge interface.
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
    """Walk *project_dir* and return ``{/<relative>: bytes}`` for the device root.

    Project files land at the device root (``app.py`` → ``/app.py``,
    ``helpers.py`` → ``/helpers.py``).

    Skipped: ``project_config.toml`` (workspace-tooling input, not
    runtime payload), ``_generated/`` (host-side deploy artifacts),
    cache and dotfile noise (``__pycache__``, ``.DS_Store``,
    ``.git``, ``.pytest_cache``, ``.mypy_cache``), and a top-level
    ``code.py`` / ``main.py`` if present (the synthesised shim owns
    those filenames at the device root).  *extra_excluded* augments
    the directory skip set.

    When *target_runtime* is set, ``.py`` files whose
    ``__chumicro_runtimes__`` marker excludes that runtime are
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

    Internal.  The public surface is the
    :class:`WithRuntimeConfig`-wrapped instance returned by the
    helper function.
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
    secrets_toml: Path | None = None,
    extra_excluded: Iterable[str] = (),
    target_runtime: str | None = None,
) -> WithRuntimeConfig:
    """Build a deploy-ready ``FileSource`` using the boot-shim layout.

    Bundles the synthesized entrypoint shim with the project's own
    files (at the device root) and the merged runtime-config msgpack
    (via :class:`WithRuntimeConfig`).

    Args:
        project_dir: Filesystem path to the project directory.
        workspace: Resolved :class:`WorkspaceLayout`.  Supplies the
            ``secrets.toml`` fallback when *secrets_toml* is ``None``.
        entrypoint_filename: ``"code.py"`` for CP, ``"main.py"``
            for MP.  Decides the host-side filename for the shim
            stub written at the device root.
        secrets_toml: Override ``secrets.toml`` path.
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
    inner = _BootShimSource(
        project_dir=project_dir,
        entrypoint_filename=entrypoint_filename,
        extra_excluded=extra_excluded,
        target_runtime=target_runtime,
    )
    return wrap_with_runtime_config(
        inner,
        project_dir=project_dir,
        workspace=workspace,
        secrets_toml=secrets_toml,
    )


# ---------------------------------------------------------------------------
# Boot-shim + import-graph composition
# ---------------------------------------------------------------------------


class _BootShimWithImportGraphSource:
    """Merge a boot-shim file map with an import-graph file map.

    Internal; the public surface is the
    :class:`WithRuntimeConfig`-wrapped instance returned by
    :func:`project_boot_with_import_graph_source`.

    The boot-shim contribution ships the entrypoint shim and the
    project's flat files at the device root.  The import-graph
    contribution ships every reachable module under
    ``/lib/<package>/...``.  The two contributions land at disjoint
    paths except where the import-graph walker reaches a
    project-local module via *project_dir* on its search path.  That
    module is already shipped by the boot-shim at the device root,
    so its ``/lib/<basename>.py`` twin from the import-graph side
    gets dropped here.  Boot-shim wins on any other overlap.
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
        """Return ``/lib/<relative>`` paths the walker would assign to project-local files.

        The combined builder adds *project_dir* as the first
        import-graph search path so the walker can follow
        project-internal relative imports.  With
        ``resource_prefix=/lib``, that puts every project ``.py`` at
        ``/lib/<relative>`` in the import-graph map.  The boot-shim
        already ships those files at the device root, so these
        ``/lib/<basename>.py`` paths are dead weight (project code
        resolves at the root, not under ``/lib/``).  :meth:`files`
        uses this set to drop them from the import-graph contribution
        before the merge.
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
    secrets_toml: Path | None = None,
    extra_excluded: Iterable[str] = (),
    target_runtime: str | None = None,
    extra_modules: list[str] | None = None,
    extra_search_paths: list[Path] | None = None,
) -> WithRuntimeConfig:
    """Boot-shim layout PLUS import-graph-discovered libraries.

    Use when a project authored for the boot-shim convention also
    needs library code (chumicro / shared / packages / library_sources
    overrides) shipped to the device.  Common case: dev mode with a
    sibling ``chumicro/`` checkout configured via ``chumicro-dev.toml``.
    Without this composition, ``chumicro_*`` libraries the project
    imports never reach the board.

    Auto-detect picks this layout when a project ships ``app.py``
    with ``run()`` and no ``code.py`` / ``main.py``.

    Args:
        project_dir: Project directory (same shape as for
            :func:`project_boot_source`).
        workspace: Resolved :class:`WorkspaceLayout`.
        entrypoint_filename: Device-side shim entrypoint.
            ``"code.py"`` (CP) or ``"main.py"`` (MP).  The shim is
            written at ``/<entrypoint_filename>`` and calls
            ``app.run()``.
        project_entrypoint: Host-side filename inside *project_dir*
            that the import-graph walker uses as its starting point.
            Defaults to ``"app.py"``, the boot-shim convention's
            entrypoint module.
        workspace_yaml: Override ``workspace.yml`` path.
        secrets_toml: Override ``secrets.toml`` path.
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
        # device_entrypoint of the graph walk.  The boot-shim's shim at
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

    return wrap_with_runtime_config(
        combined,
        project_dir=project_dir,
        search_paths=search_paths,
        workspace=workspace,
        secrets_toml=secrets_toml,
    )
