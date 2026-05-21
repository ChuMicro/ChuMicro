"""Build a deploy-ready FileSource for a workspace project by
AST-walking imports from its entrypoint.

:func:`project_import_graph_source` is the one-call factory.  It
composes a workspace-shaped search path (project dir,
``shared/``, each ``libraries/<name>/src/``, ``packages/``, and
any ``library_sources:`` overrides from ``workspace.yml``), hands
it to :class:`chumicro_deploy.ImportGraphSource` for the AST
walk, and wraps the result with :class:`WithRuntimeConfig` so
the merged runtime-config msgpack rides alongside the resolved
app code.

:func:`read_library_sources` parses the ``library_sources:`` map
on its own for callers that compose the layers manually (custom
search paths, alternate entrypoint).  Each entry is an explicit
override mapping an import name to a directory tried first
during resolution.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ruamel.yaml import YAML

from chumicro_workspace.deploy_source import (
    WithRuntimeConfig,
    wrap_with_runtime_config,
)
from chumicro_workspace.loaders import WorkspaceConfigError

if TYPE_CHECKING:  # pragma: no cover - type-only
    from chumicro_workspace.workspace import WorkspaceLayout


def read_library_sources(workspace_yaml: Path) -> dict[str, Path]:
    """Parse ``library_sources:`` out of *workspace_yaml*.

    Returns ``{package_or_root_name: Path}``.  The key is what a
    Python ``import`` statement would spell (e.g. ``chumicro_wifi``
    or ``my_house_libs``), and the value points at a directory whose
    children are importable under that name.

    Returns an empty dict when ``workspace.yml`` has no
    ``library_sources:`` block.  The no-overrides case is normal,
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
    """Compose the import-resolution search-path list for *workspace*.

    First match wins inside :class:`ImportGraphSource`, so order
    encodes precedence: explicit overrides, then workspace-internal
    sources, then third-party packages.  Pure path arithmetic: the
    caller passes any ``library_sources:`` map already parsed, so
    this function performs no YAML I/O.  Paths that don't exist on
    disk are dropped, and duplicates collapse.

    Resolution order::

        1. library_sources_override values
        2. workspace/shared/                (user-authored shared modules)
        3. workspace/libraries/<name>/src/  (scaffolded chumicro-style
                                             library packages)
        4. workspace/packages/              (third-party, gitignored)
        5. extra_search_paths               (caller-supplied tail; e.g.
                                             mono-repo dogfooding with the
                                             live chumicro src/)

    Args:
        workspace: Resolved :class:`WorkspaceLayout`.
        library_sources_override: ``{package_name: Path}`` already
            read from ``workspace.yml``'s ``library_sources:``, or
            ``None`` to skip override processing.
        extra_search_paths: Directories appended at the tail.
    """
    candidates: list[Path] = []
    if library_sources_override:
        # Sort by package name so two invocations with the same map
        # produce the same search-path list.
        for _name, override_path in sorted(library_sources_override.items()):
            candidates.append(override_path)
    candidates.append(workspace.shared_dir)
    # Add each library's src/ so ``import my_lib`` resolves against
    # the local checkout without needing a ``library_sources:`` entry.
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
    secrets_toml: Path | None = None,
    entrypoint_filename: str = "code.py",
    device_entrypoint: str = "/code.py",
    resource_prefix: str = "/lib",
    extra_modules: list[str] | None = None,
    extra_search_paths: list[Path] | None = None,
    target_runtime: str | None = None,
) -> WithRuntimeConfig:
    """Build a deploy-ready FileSource using AST-walked imports.

    Uses :class:`chumicro_deploy.ImportGraphSource` so only
    transitively-imported modules ship.  This keeps the device payload
    minimal even when the workspace has many shared libs.

    The project's entrypoint file is parsed and every reachable module
    via ``shared/`` / ``packages/`` / ``library_sources:`` lands in
    the deploy.  Modules that don't resolve (``gc``, ``time``,
    ``board``, etc.) are silently skipped.  They're assumed to be
    runtime built-ins the host can't ship.

    Args:
        project_dir: ``projects/<name>/`` directory.  Used as the root
            of the entrypoint lookup *and* as a search path so
            project-local modules under the same dir resolve.
        workspace: Resolved :class:`WorkspaceLayout`.  Supplies the
            ``workspace.yml`` and ``secrets.toml`` fallbacks when
            *workspace_yaml* and *secrets_toml* are not given.
        workspace_yaml: Override the workspace.yml path.
            Defaults to ``workspace.workspace_yaml``.
        secrets_toml: Override the secrets.toml path.
            Defaults to ``workspace.secrets_toml``.
        entrypoint_filename: Host-side filename of the project's
            entrypoint; must exist under *project_dir*.  Defaults to
            ``"code.py"`` (CircuitPython convention).  Override to
            ``"main.py"`` for MicroPython.
        device_entrypoint: On-device path the runtime executes
            after staging.  Defaults to ``"/code.py"``.
        resource_prefix: On-device prefix for non-entrypoint module
            files.  Defaults to ``"/lib"``, the conventional
            CP / MP search path.
        extra_modules: Dotted module names to force-include even
            when AST can't see them.  Forwarded to
            :class:`ImportGraphSource`.
        extra_search_paths: Additional directories appended to the
            workspace-derived search path tail.
        target_runtime: Forwarded to :class:`ImportGraphSource` so
            modules marked for a different runtime via
            ``__chumicro_runtimes__`` are dropped (and their
            imports not walked).  ``None`` (the default) ships
            every module unfiltered.

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

    return wrap_with_runtime_config(
        inner,
        project_dir=project_dir,
        search_paths=search_paths,
        workspace=workspace,
        secrets_toml=secrets_toml,
    )
