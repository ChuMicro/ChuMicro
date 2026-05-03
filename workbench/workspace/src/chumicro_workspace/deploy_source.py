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
  ``/runtime_config.msgpack`` per Decision 0035 §8.
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

#: Canonical on-device path for the merged runtime-config msgpack
#: (Decision 0035 §8).  Every consumer library + the workspace
#: template assumes this exact location; changing it is an ABI break.
RUNTIME_CONFIG_DEVICE_PATH: str = "/runtime_config.msgpack"

#: Default subdirectory under ``projects/<name>/`` where the generated
#: msgpack lives on the host.  ``_generated/`` is gitignored at the
#: workspace level so the file isn't committed alongside the source.
GENERATED_DIRNAME: str = "_generated"

#: Filenames under ``projects/<name>/`` that are workspace-tooling
#: inputs, not runtime payload, and so are skipped when shipping the
#: project's directory to the device.
_SKIP_FILENAMES: frozenset[str] = frozenset(
    {"config.toml", "config.yml", "config.yaml"},
)


def find_project_config(project_dir: Path) -> Path:
    """Return the config file for *project_dir* — TOML wins over YAML.

    Per Decision 0035 §1, every project carries one config file.  This
    helper picks the canonical name in priority order: ``config.toml``,
    then ``config.yml``, then ``config.yaml``.

    Args:
        project_dir: Path to ``projects/<name>/``.

    Raises:
        FileNotFoundError: When no recognized config file exists.
    """
    for filename in ("config.toml", "config.yml", "config.yaml"):
        candidate = project_dir / filename
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"no config.toml / config.yml / config.yaml in {project_dir}",
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
        secrets_yaml: Path to ``secrets.yml``.  May not exist —
            ``read_secrets_yaml`` treats absence as "no secrets".
        output_path: Where to write the msgpack on the host.  Defaults
            to ``project_config.parent / _generated / runtime_config.msgpack``.
        device_path: On-device path for the msgpack.  Defaults to
            :data:`RUNTIME_CONFIG_DEVICE_PATH` (Decision 0035 §8).

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
        secrets_yaml: Path,
        output_path: Path | None = None,
        device_path: str = RUNTIME_CONFIG_DEVICE_PATH,
    ) -> None:
        self._inner = inner
        self._workspace_yaml = workspace_yaml
        self._project_config = project_config
        self._secrets_yaml = secrets_yaml
        self._device_path = device_path
        self._output_path = (
            output_path
            if output_path is not None
            else project_config.parent / GENERATED_DIRNAME / "runtime_config.msgpack"
        )
        if device_path in inner.files():
            raise ValueError(
                f"inner source already provides {device_path!r}; "
                "WithRuntimeConfig would clobber it",
            )

    def files(self) -> dict[str, bytes]:
        """Regenerate the msgpack and merge it into the inner file map."""
        build_runtime_config(
            workspace_yaml=self._workspace_yaml,
            project_config=self._project_config,
            secrets_yaml=self._secrets_yaml,
            output_path=self._output_path,
        )
        msgpack_bytes = self._output_path.read_bytes()
        files = self._inner.files()
        files[self._device_path] = msgpack_bytes
        return files

    def entrypoint(self) -> str:
        """Forward the inner source's entrypoint unchanged."""
        return self._inner.entrypoint()


def project_directory_source(
    project_dir: Path,
    *,
    workspace_yaml: Path,
    secrets_yaml: Path,
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
        secrets_yaml: Path to ``secrets.yml``.
        entrypoint: On-device entrypoint path.  Defaults to
            ``"/code.py"`` (CircuitPython convention).  Override to
            ``"/main.py"`` for MicroPython projects.
        resource_prefix: On-device prefix prepended to each app file.
            Forwarded to :class:`DirectorySource`.
        extra_excluded: Additional filename / directory names to skip
            beyond the defaults (config files, ``_generated/``,
            ``__pycache__/``, etc.).
        target_runtime: Decision 0044 — forwarded to
            :class:`DirectorySource` so ``.py`` files marked for a
            different runtime via ``__chumicro_runtimes__`` are
            filtered out before staging.  ``None`` (the default)
            preserves the prior unfiltered behavior; the workspace
            ``deploy`` CLI fills this in from the device's runtime.

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
        secrets_yaml=secrets_yaml,
    )
