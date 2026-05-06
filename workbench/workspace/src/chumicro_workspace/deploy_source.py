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

#: Canonical on-device path for the merged runtime-config msgpack.
#: Every consumer library + the workspace template assumes this
#: exact location; changing it is an ABI break.
RUNTIME_CONFIG_DEVICE_PATH: str = "/runtime_config.msgpack"

#: Default subdirectory under ``projects/<name>/`` where the generated
#: msgpack lives on the host.  ``_generated/`` is gitignored at the
#: workspace level so the file isn't committed alongside the source.
GENERATED_DIRNAME: str = "_generated"

#: Filenames under ``projects/<name>/`` that are workspace-tooling
#: inputs, not runtime payload, and so are skipped when shipping the
#: project's directory to the device.
_SKIP_FILENAMES: frozenset[str] = frozenset(
    {"project_config.toml", "config.toml", "config.yml", "config.yaml"},
)


def find_project_config(project_dir: Path) -> Path:
    """Return the per-project config file for *project_dir*.

    Picks the first existing file in this priority order:

    1. ``project_config.toml`` — current canonical name.  Self-documenting
       (a beginner reading the project directory immediately sees this
       is project-specific config, not a generic ``config.toml``).
    2. ``config.toml`` — legacy name, accepted so user-edited workspaces
       from before the rename keep working without a migration.
    3. ``config.yml`` / ``config.yaml`` — YAML opt-in.

    Args:
        project_dir: Path to ``projects/<name>/``.

    Raises:
        FileNotFoundError: When no recognized config file exists.
    """
    for filename in (
        "project_config.toml",
        "config.toml",
        "config.yml",
        "config.yaml",
    ):
        candidate = project_dir / filename
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"no project_config.toml / config.toml / config.yml / config.yaml "
        f"in {project_dir}",
    )


class WithRuntimeConfig:
    """``FileSource`` decorator that injects the merged runtime config.

    Every call to :meth:`files` regenerates the msgpack (so the freshest
    config rides every deploy without the caller having to call
    :func:`build_runtime_config` manually first), then merges the inner
    source's files with ``{device_path: msgpack_bytes}``.  The
    entrypoint is forwarded from the inner source unchanged.

    Args:
        inner: The base ``FileSource`` (typically the project's app code).
        workspace_yaml: Path to ``workspace.yml``.
        project_config: Path to ``projects/<name>/config.{toml,yml,yaml}``.
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
        workspace_yaml: Path,
        project_config: Path,
        output_path: Path | None = None,
        device_path: str = RUNTIME_CONFIG_DEVICE_PATH,
        library_roots: tuple[Path, ...] | list[Path] | None = None,
    ) -> None:
        self._inner = inner
        self._workspace_yaml = workspace_yaml
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
            workspace_yaml=self._workspace_yaml,
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


def project_directory_source(
    project_dir: Path,
    *,
    workspace_yaml: Path,
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
        workspace_yaml: Path to ``workspace.yml``.
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
    return WithRuntimeConfig(
        inner,
        workspace_yaml=workspace_yaml,
        project_config=find_project_config(project_dir),
    )
