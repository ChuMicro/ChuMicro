"""Deploy-time integration with ``chumicro-deploy``.

The deploy package owns ``FileSource`` (path → bytes producers that
the ``Deployer`` ships onto a device).  Workspace-runtime composes
those sources so a single :meth:`Deployer.deploy` call sends both
the project's app code and its generated ``/runtime_config.msgpack``
in one shot — the user no longer has to remember to regenerate the
config before each deploy.

Two pieces:

* :class:`WithRuntimeConfig` — a ``FileSource`` decorator that wraps
  any inner source (``DirectorySource``, ``FileMapSource``,
  ``ImportGraphSource``, custom) and injects the merged msgpack at
  ``/runtime_config.msgpack``.
* :func:`project_directory_source` — convenience that builds a
  ``DirectorySource`` from ``projects/<name>/`` (skipping the host-side
  ``config.{toml,yml,yaml}``, ``_generated/`` output dir, and the
  usual cache artifacts) and wraps it with :class:`WithRuntimeConfig`.
  Covers the typical "self-contained project directory" case.

For projects that import shared libs from elsewhere in the workspace,
build the inner source explicitly (`ImportGraphSource(...)` or a
custom ``FileSource``) and wrap it with :class:`WithRuntimeConfig`
yourself.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from chumicro_workspace.pipeline import build_runtime_config

if TYPE_CHECKING:  # pragma: no cover — type-only
    from chumicro_deploy import FileSource

    from chumicro_workspace.workspace import WorkspaceLayout

#: Canonical on-device path for the merged runtime-config msgpack.
#: Every consumer library + the workspace template assumes this
#: exact location; changing it is an ABI break.
RUNTIME_CONFIG_DEVICE_PATH: str = "/runtime_config.msgpack"

#: Default subdirectory under ``projects/<name>/`` where the generated
#: msgpack lives on the host.  ``_generated/`` is gitignored at the
#: workspace level so the file isn't committed alongside the source.
GENERATED_DIRNAME: str = "_generated"

#: Filename under ``projects/<name>/`` that is workspace-tooling
#: input, not runtime payload, and so is skipped when shipping the
#: project's directory to the device.
_SKIP_FILENAMES: frozenset[str] = frozenset({"project_config.toml"})


def find_project_config(project_dir: Path) -> Path:
    """Return the per-project config path for *project_dir*.

    The project-config filename is ``project_config.toml`` — the only
    name the workspace accepts.

    Args:
        project_dir: Path to ``projects/<name>/``.

    Raises:
        FileNotFoundError: ``project_config.toml`` does not exist in
            *project_dir*.
    """
    candidate = project_dir / "project_config.toml"
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(f"no project_config.toml in {project_dir}")


class WithRuntimeConfig:
    """``FileSource`` decorator that injects the merged runtime config.

    Every call to :meth:`files` regenerates the msgpack (so the freshest
    config rides every deploy without the caller having to call
    :func:`build_runtime_config` manually first), then merges the inner
    source's files with ``{device_path: msgpack_bytes}``.  The
    entrypoint is forwarded from the inner source unchanged.

    Args:
        inner: The base ``FileSource`` (typically the project's app code).
        secrets_toml: Path to ``secrets.toml`` (workspace-wide
            credentials + device defaults).
        project_config: Path to ``projects/<name>/project_config.toml``.
        output_path: Where to write the msgpack on the host.  Defaults
            to ``project_config.parent / _generated / runtime_config.msgpack``.
        device_path: On-device path for the msgpack.  Defaults to
            :data:`RUNTIME_CONFIG_DEVICE_PATH`.

    Raises:
        ValueError: If *device_path* is already a key in the inner
            source's file map — indicates the caller is producing two
            different files for the same on-device location, which the
            transport would resolve unpredictably.
    """

    def __init__(
        self,
        inner: FileSource,
        *,
        secrets_toml: Path,
        project_config: Path,
        output_path: Path | None = None,
        device_path: str = RUNTIME_CONFIG_DEVICE_PATH,
        library_roots: tuple[Path, ...] | list[Path] | None = None,
    ) -> None:
        self._inner = inner
        self._secrets_toml = secrets_toml
        self._project_config = project_config
        self._device_path = device_path
        self._output_path = (
            output_path
            if output_path is not None
            else project_config.parent / GENERATED_DIRNAME / "runtime_config.msgpack"
        )
        # ``library_roots`` enables manifest validation: each path is
        # a library checkout (``libraries/<name>/`` with a
        # ``pyproject.toml``); ``files()`` reads each one's
        # ``[tool.chumicro.config]`` block, unions the required /
        # optional flat keys, and validates the merged + flattened
        # config dict against the union before writing the msgpack.
        # Missing required keys surface as a precise
        # :class:`ConfigManifestError` instead of a cryptic
        # ``MissingConfigKey`` at device boot.  ``None`` (the default)
        # skips validation — for callers that don't yet plumb the
        # import-graph library list through.
        self._library_roots: tuple[Path, ...] = (
            tuple(library_roots) if library_roots else ()
        )
        if device_path in inner.files():
            raise ValueError(
                f"inner source already provides {device_path!r}; "
                "WithRuntimeConfig would clobber it",
            )

    def files(self) -> dict[str, bytes]:
        """Regenerate the msgpack and merge it into the inner file map."""
        resolved = build_runtime_config(
            secrets_toml=self._secrets_toml,
            project_config=self._project_config,
            output_path=self._output_path,
        )
        if self._library_roots:
            self._validate_against_manifests(resolved)
        msgpack_bytes = self._output_path.read_bytes()
        files = self._inner.files()
        files[self._device_path] = msgpack_bytes
        return files

    def _validate_against_manifests(self, resolved: dict) -> None:
        """Validate *resolved* against the union manifest of *library_roots*."""
        # Local import: ``config_manifest`` pulls in ``tomllib`` and
        # the dataclass machinery; keep ``deploy_source``'s import
        # cost flat for the no-validation path.
        from chumicro_workspace.config_manifest import (  # noqa: PLC0415
            aggregate_manifests,
            read_manifest,
            validate_runtime_config,
        )

        manifests = (
            read_manifest(library_root) for library_root in self._library_roots
        )
        union = aggregate_manifests(manifests)
        if union:
            validate_runtime_config(resolved, union)

    def entrypoint(self) -> str:
        """Forward the inner source's entrypoint unchanged."""
        return self._inner.entrypoint()


def wrap_with_runtime_config(
    inner: FileSource,
    *,
    project_dir: Path,
    search_paths: Iterable[Path] | None = None,
    workspace: WorkspaceLayout | None = None,
    secrets_toml: Path | None = None,
    project_config: Path | None = None,
    output_path: Path | None = None,
) -> WithRuntimeConfig:
    """Wrap *inner* in :class:`WithRuntimeConfig`, resolving conventions.

    Every ``FileSource`` front-end ends the same way: build an inner
    source, then wrap it so the merged ``runtime_config.msgpack`` rides
    the deploy.  The wrapping needed the same four conventional-default
    resolutions open-coded in each builder.  This collapses them into
    one call; each front-end keeps its own inner-source construction
    and ends with ``return wrap_with_runtime_config(inner, ...)``.

    Conventions resolved when the corresponding argument is ``None``:

    * *secrets_toml* → ``workspace.secrets_toml`` (requires *workspace*).
    * *project_config* → :func:`find_project_config` under
      *project_dir* (the per-project ``project_config.toml``).
    * *output_path* → ``project_dir / _generated /
      runtime_config.msgpack`` (the gitignored build-artifact dir).
    * *library_roots* (for manifest validation) → derived from
      *search_paths* when given (an import-graph front-end), else
      left empty (a directory / boot-shim front-end with no walked
      libraries — validation off, as before).

    Args:
        inner: The base ``FileSource`` to wrap.
        project_dir: The project (or, for an example, the owning
            library) directory — only consulted for the
            *project_config* / *output_path* defaults.
        search_paths: Import-graph search paths.  When given, each
            ``libraries/<name>/`` root among them is read for its
            ``[tool.chumicro.config]`` manifest and the merged config
            is validated before the msgpack is written.
        workspace: Resolved :class:`WorkspaceLayout` — the
            *secrets_toml* fallback source.
        secrets_toml: Explicit ``secrets.toml`` path; overrides the
            *workspace* fallback.
        project_config: Explicit per-project config path; overrides
            the *project_dir* lookup (an example passes its own
            ``examples/project_config.toml`` via :func:`example_source`).
        output_path: Explicit host path for the generated msgpack;
            overrides the ``_generated/`` default.

    Raises:
        ValueError: Neither *secrets_toml* nor *workspace* given —
            there is no ``secrets.toml`` to resolve.
        FileNotFoundError: *project_config* defaulted and no
            recognized config file exists under *project_dir*.
    """
    if secrets_toml is None:
        if workspace is None:
            raise ValueError(
                "wrap_with_runtime_config needs secrets_toml or workspace",
            )
        secrets_toml = workspace.secrets_toml
    if project_config is None:
        project_config = find_project_config(project_dir)
    if output_path is None:
        output_path = project_dir / GENERATED_DIRNAME / "runtime_config.msgpack"
    library_roots: tuple[Path, ...] | None = None
    if search_paths is not None:
        # Local import: ``config_manifest`` pulls in ``tomllib`` + the
        # dataclass machinery; keep this module's import cost flat for
        # the no-validation (directory / boot-shim) front-ends.
        from chumicro_workspace.config_manifest import (  # noqa: PLC0415
            find_library_roots,
        )

        library_roots = find_library_roots(search_paths)
    return WithRuntimeConfig(
        inner,
        secrets_toml=secrets_toml,
        project_config=project_config,
        output_path=output_path,
        library_roots=library_roots,
    )


def project_directory_source(
    project_dir: Path,
    *,
    secrets_toml: Path,
    entrypoint: str = "/code.py",
    resource_prefix: str = "/",
    extra_excluded: Iterable[str] = (),
    target_runtime: str | None = None,
) -> WithRuntimeConfig:
    """Build a deploy-ready ``FileSource`` for a typical project directory.

    Walks *project_dir* with :class:`chumicro_deploy.DirectorySource`,
    skipping the project's host-side config files and ``_generated/``
    output directory, then wraps the result with
    :class:`WithRuntimeConfig` so the merged msgpack rides the deploy.

    Args:
        project_dir: ``projects/<name>/`` directory.
        secrets_toml: Path to ``secrets.toml`` (workspace-wide
            credentials + device defaults).
        entrypoint: On-device entrypoint path.  Defaults to
            ``"/code.py"`` (CircuitPython convention).  Override to
            ``"/main.py"`` for MicroPython projects.
        resource_prefix: On-device prefix prepended to each app file.
            Forwarded to :class:`DirectorySource`.
        extra_excluded: Additional filename / directory names to skip
            beyond the defaults (config files, ``_generated/``,
            ``__pycache__/``, etc.).
        target_runtime: Forwarded to :class:`DirectorySource` so
            ``.py`` files marked for a different runtime via
            ``__chumicro_runtimes__`` are filtered out before
            staging.  ``None`` (the default) ships every file
            unfiltered; the workspace ``deploy`` CLI fills this in
            from the device's runtime.

    Raises:
        FileNotFoundError: When *project_dir* contains no recognized
            config file.
        NotADirectoryError: When *project_dir* is not a directory.
        ValueError: When the directory walk doesn't include
            *entrypoint*.
    """
    from chumicro_deploy import DirectorySource

    excluded = frozenset(
        DirectorySource.DEFAULT_EXCLUDED
        | _SKIP_FILENAMES
        | {GENERATED_DIRNAME}
        | set(extra_excluded),
    )
    inner = DirectorySource(
        project_dir,
        entrypoint=entrypoint,
        resource_prefix=resource_prefix,
        excluded_names=excluded,
        target_runtime=target_runtime,
    )
    return wrap_with_runtime_config(
        inner,
        project_dir=project_dir,
        secrets_toml=secrets_toml,
    )
