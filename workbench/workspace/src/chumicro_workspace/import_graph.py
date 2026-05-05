"""Import-graph deploy source per Decision 0029 §6 + §7.

``chumicro_deploy.ImportGraphSource`` already performs the AST walk
(parses an entrypoint, follows ``import`` / ``from ... import``
targets, recurses).  This module assembles the *workspace-shaped*
search-path list — project directory + ``shared/`` (user-authored
shared modules) + ``packages/`` (third-party, gitignored) +
optional ``library_sources:`` overrides — and wraps the result
with :class:`WithRuntimeConfig` so the merged runtime-config
msgpack rides the deploy alongside the AST-resolved app code.

Two pieces:

* :func:`read_library_sources` — parses ``workspace.yml``'s
  ``library_sources:`` map into ``{package_name: Path}``.  Decision
  0029 §7 makes these explicit overrides for "use the local
  checkout instead of the published copy"; the value is a search
  path that the import-graph walker tries before the workspace's
  ``shared/`` / ``packages/`` defaults.
* :func:`project_import_graph_source` — convenience that builds the
  search-path list, constructs an :class:`ImportGraphSource` for
  the project's entrypoint, and wraps with :class:`WithRuntimeConfig`.
  The CLI ``deploy --import-graph`` invokes this; programmatic
  callers can compose the layers themselves for finer control
  (custom search paths, extra modules, alternate entrypoint).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ruamel.yaml import YAML

from chumicro_workspace.deploy_source import (
    GENERATED_DIRNAME,
    WithRuntimeConfig,
    find_project_config,
)
from chumicro_workspace.loaders import WorkspaceConfigError

if TYPE_CHECKING:  # pragma: no cover — type-only
    from chumicro_workspace.workspace import WorkspaceLayout


def read_library_sources(workspace_yaml: Path) -> dict[str, Path]:
    """Parse ``library_sources:`` out of *workspace_yaml*.

    Returns ``{package_or_root_name: Path}``.  Decision 0029 §7's
    semantics: the key is what a Python ``import`` statement would
    spell (e.g. ``chumicro_wifi`` or ``my_house_libs``); the value
    points at a directory whose children are importable under that
    name.  Typical local-checkout case: ``chumicro_wifi:
    /home/me/dev/chumicro/libraries/wifi/src``.

    Returns an empty dict when ``workspace.yml`` has no
    ``library_sources:`` block — the no-overrides case is normal,
    not an error.

    Args:
        workspace_yaml: Path to ``workspace.yml``.

    Raises:
        WorkspaceConfigError: When ``library_sources:`` exists but
            isn't a mapping, or when any value isn't a string path.
    """
    if not workspace_yaml.is_file():
        return {}
    with workspace_yaml.open("r", encoding="utf-8") as handle:
        loaded = YAML(typ="safe").load(handle)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise WorkspaceConfigError(
            f"{workspace_yaml}: top-level must be a mapping, "
            f"got {type(loaded).__name__}",
        )
    raw = loaded.get("library_sources")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise WorkspaceConfigError(
            f"{workspace_yaml}: 'library_sources' must be a mapping, "
            f"got {type(raw).__name__}",
        )
    sources: dict[str, Path] = {}
    for package_name, raw_path in raw.items():
        if not isinstance(package_name, str):
            raise WorkspaceConfigError(
                f"{workspace_yaml}: 'library_sources' keys must be "
                f"strings, got {type(package_name).__name__}",
            )
        if not isinstance(raw_path, str):
            raise WorkspaceConfigError(
                f"{workspace_yaml}: 'library_sources.{package_name}' "
                f"must be a string path, got {type(raw_path).__name__}",
            )
        sources[package_name] = Path(raw_path)
    return sources


def build_search_paths(
    workspace: WorkspaceLayout,
    *,
    library_sources_override: dict[str, Path] | None = None,
    extra_search_paths: list[Path] | None = None,
) -> list[Path]:
    """Compose the import-resolution search path list for *workspace*.

    Order matters — first match wins inside
    :class:`ImportGraphSource`.  Decision 0029 §7's intent: explicit
    overrides beat workspace-internal sources beat third-party
    packages.

    Resolution order::

        1. library_sources_override values (Decision 0029 §7)
        2. workspace/shared/         (user-authored shared modules — flat layout)
        3. workspace/libraries/<name>/src/  (full chumicro-style library
                                             packages, scaffolded via
                                             ``new --library``)
        4. workspace/packages/     (third-party, gitignored)
        5. extra_search_paths      (caller-supplied tail; e.g. mono-repo
                                    devs adding the live chumicro src/)

    Only paths that actually exist on disk are returned —
    :class:`ImportGraphSource` rejects nonexistent search paths at
    construction.  Read ``library_sources`` from ``workspace.yml``
    yourself via :func:`read_library_sources` and pass it in if you
    want the override layer; this function is content with whatever
    map you supply (or none).

    Args:
        workspace: Resolved :class:`WorkspaceLayout`.
        library_sources_override: ``{package_name: Path}`` from
            ``workspace.yml``'s ``library_sources:``.  Pass ``None``
            (the default) when you don't want override processing —
            this function doesn't read the file itself, so callers
            stay in control of when YAML I/O happens.
        extra_search_paths: Additional directories to append at the
            tail.  Useful for in-mono-repo dogfooding where the
            chumicro library checkouts live alongside the workspace.
    """
    candidates: list[Path] = []
    if library_sources_override:
        # Stable ordering — sort by package name so two invocations
        # with the same map produce the same search-path list.
        for _name, override_path in sorted(library_sources_override.items()):
            candidates.append(override_path)
    candidates.append(workspace.shared_dir)
    # Full chumicro-style library packages scaffolded via
    # ``new --library`` live at ``libraries/<name>/`` with the
    # importable module under ``src/``.  Add each ``src/`` so a
    # project's ``import my_lib`` resolves against the local checkout
    # without forcing the user to register an entry in
    # ``library_sources:``.
    if workspace.libraries_dir.is_dir():
        for library_dir in sorted(workspace.libraries_dir.iterdir()):
            src_dir = library_dir / "src"
            if src_dir.is_dir():
                candidates.append(src_dir)
    candidates.append(workspace.packages_dir)
    if extra_search_paths:
        candidates.extend(extra_search_paths)

    seen: set[Path] = set()
    resolved: list[Path] = []
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        resolved.append(candidate)
    return resolved


def project_import_graph_source(
    project_dir: Path,
    *,
    workspace: WorkspaceLayout,
    workspace_yaml: Path | None = None,
    workspace_local_yaml: Path | None = None,
    entrypoint_filename: str = "code.py",
    device_entrypoint: str = "/code.py",
    resource_prefix: str = "/lib",
    extra_modules: list[str] | None = None,
    extra_search_paths: list[Path] | None = None,
    target_runtime: str | None = None,
) -> WithRuntimeConfig:
    """Build a deploy-ready FileSource using AST-walked imports.

    Mirrors :func:`project_directory_source` but uses
    :class:`chumicro_deploy.ImportGraphSource` so only transitively-
    imported modules ship — keeps the device payload minimal even
    when the workspace has many shared libs.

    The project's entrypoint file is parsed; every reachable module
    via ``shared/`` / ``packages/`` / ``library_sources:`` lands in
    the deploy.  Modules that don't resolve (``gc``, ``time``,
    ``board``, etc.) are silently skipped — they're assumed to be
    runtime built-ins the host can't ship anyway.

    Args:
        project_dir: ``projects/<name>/`` directory.  Used as the root
            of the entrypoint lookup *and* as a search path so
            project-local modules under the same dir resolve.
        workspace: Resolved :class:`WorkspaceLayout`.  Used to
            locate ``workspace.yml`` (defaults block + library_sources)
            and ``workspace.local.yml`` when those args are ``None``.
        workspace_yaml: Override the workspace.yml path.  Defaults
            to ``workspace.workspace_yaml``.  Tests inject when
            staging a workspace under tmp_path with a non-default
            layout.
        workspace_local_yaml: Override the workspace.local.yml path
            (gitignored overlay; Decision 0057).  Defaults to
            ``workspace.workspace_local_yaml``.
        entrypoint_filename: Host-side filename of the project's
            entrypoint; must exist under *project_dir*.  Defaults to
            ``"code.py"`` (CircuitPython convention).  Override to
            ``"main.py"`` for MicroPython.
        device_entrypoint: On-device path the runtime executes
            after staging.  Defaults to ``"/code.py"``.
        resource_prefix: On-device prefix for non-entrypoint module
            files.  Defaults to ``"/lib"`` — the conventional
            CP / MP search path.
        extra_modules: Dotted module names to force-include even
            when AST can't see them.  Forwarded to
            :class:`ImportGraphSource`.
        extra_search_paths: Additional directories prepended to the
            workspace-derived search path tail.
        target_runtime: Decision 0044 — forwarded to
            :class:`ImportGraphSource` so modules marked for a
            different runtime via ``__chumicro_runtimes__`` are
            dropped (and their imports not walked).  ``None`` (the
            default) preserves the prior behavior; the workspace
            ``deploy`` CLI fills this in from the device's runtime.

    Raises:
        FileNotFoundError: When *project_dir* doesn't contain a
            recognized config file or *entrypoint_filename* doesn't
            exist under it.
        WorkspaceConfigError: When workspace.yml's
            ``library_sources:`` block is malformed.
    """
    from chumicro_deploy import ImportGraphSource  # noqa: PLC0415

    if workspace_yaml is None:
        workspace_yaml = workspace.workspace_yaml
    if workspace_local_yaml is None:
        workspace_local_yaml = workspace.workspace_local_yaml

    entrypoint_path = project_dir / entrypoint_filename
    if not entrypoint_path.is_file():
        raise FileNotFoundError(
            f"entrypoint {entrypoint_path} not found "
            f"(pass entrypoint_filename to override)",
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

    inner = ImportGraphSource(
        entrypoint_path,
        search_paths=search_paths,
        extra_modules=extra_modules,
        device_entrypoint=device_entrypoint,
        resource_prefix=resource_prefix,
        target_runtime=target_runtime,
    )

    # Library roots extracted from the search paths so
    # ``WithRuntimeConfig`` can read each library's
    # ``[tool.chumicro.config.sections.*]`` block and validate the
    # merged config dict against the union manifest before writing
    # the msgpack — Phase 2 of the unification workstream.  Local
    # import keeps the import-graph module's import cost flat for
    # callers who don't deploy.
    from chumicro_workspace.config_manifest import (  # noqa: PLC0415
        find_library_roots,
    )
    library_roots = find_library_roots(search_paths)

    return WithRuntimeConfig(
        inner,
        workspace_yaml=workspace_yaml,
        project_config=find_project_config(project_dir),
        workspace_local_yaml=workspace_local_yaml,
        output_path=project_dir / GENERATED_DIRNAME / "runtime_config.msgpack",
        library_roots=library_roots,
    )
