"""Boot-shim deploy pattern per Decision 0029 §3.

The boot shim layer is a fixed set of files written onto the
device alongside the thing's app code:

* ``/code.py`` (CP) or ``/main.py`` (MP) — two-line bootstrapper
  that imports :mod:`workspace_runtime` and calls ``boot()``.
* ``/active.py`` — names the active thing
  (``THING_NAME = "<name>"``).
* ``/lib/workspace_runtime/__init__.py`` — the on-device boot
  module shipped as a payload from this package.
* ``/lib/things/__init__.py`` + ``/lib/things/<name>/__init__.py``
  — package markers that let ``things.<name>.app`` resolve.

The thing's own files land at
``/lib/things/<name>/`` (rather than the top-of-filesystem layout
the simpler :func:`thing_directory_source` produces).  This keeps
multi-thing-on-one-device paths open: future slices can deploy
several thing payloads and switch between them by rewriting
``active.py`` instead of re-flashing the whole stack.

Two pieces:

* :func:`load_workspace_runtime_payload` reads the on-device
  module out of the package's ``_payloads/`` directory.  Pure
  filesystem read — no network, no codegen.
* :func:`thing_boot_source` produces a ``WithRuntimeConfig``-
  wrapped :class:`FileMapSource` that bundles the shim layer +
  the thing's files at the right paths + the merged runtime-
  config msgpack.

The CLI ``deploy --boot-shim`` flag opts into this pattern;
default deploys still use Slice 1's flat
:func:`thing_directory_source` layout.  Opt-in because the boot
shim is workspace-runtime convention — workspaces / templates
that don't follow it (third-party templates per Decision 0032)
keep working unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from chumicro_workspace_runtime.deploy_source import (
    GENERATED_DIRNAME,
    WithRuntimeConfig,
    find_thing_config,
)

if TYPE_CHECKING:  # pragma: no cover — type-only
    from chumicro_workspace_runtime.workspace import WorkspaceLayout

#: On-device path of the boot module the shim imports.  Decision
#: 0029 §3's contract — every workspace template's ``code.py``
#: ends up calling :func:`workspace_runtime.boot`.
BOOT_MODULE_DEVICE_PATH = "/lib/workspace_runtime/__init__.py"

#: On-device path of the ``things/`` namespace marker.  Empty file
#: that just makes ``things`` an importable package on CP / MP.
THINGS_PACKAGE_INIT_DEVICE_PATH = "/lib/things/__init__.py"

#: One-line ``code.py`` (CP) / ``main.py`` (MP) shim.  Contents
#: are stable across deploys — Decision 0029 §3 calls this out
#: explicitly: ``code.py — shipped by template; do not edit``.
SHIM_ENTRYPOINT_SOURCE = (
    "# Shipped by chumicro-workspace-runtime; do not edit.\n"
    "import workspace_runtime\n"
    "workspace_runtime.boot()\n"
)

#: Directory under :mod:`chumicro_workspace_runtime`'s package
#: tree where on-device payloads live.  Resolved at import time
#: so ``importlib.resources``-style access stays simple — we read
#: payload files directly from the wheel.
_PAYLOADS_DIR = Path(__file__).resolve().parent / "_payloads"

#: Filenames under ``things/<name>/`` that are workspace-tooling
#: inputs, not runtime payload — same exclusions
#: :func:`thing_directory_source` applies.
_THING_HOST_ONLY_NAMES: frozenset[str] = frozenset(
    {"config.toml", "config.yml", "config.yaml"},
)

#: Cache directory + workspace-tooling-reserved names skipped on
#: the thing walk.  Mirrors
#: ``chumicro_deploy.DirectorySource.DEFAULT_EXCLUDED`` so the
#: behavior matches what users see with the simpler source.
_DEFAULT_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {"__pycache__", ".DS_Store", ".git", ".pytest_cache", ".mypy_cache",
     GENERATED_DIRNAME},
)


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
            f"{payload_path} — chumicro-workspace-runtime install "
            "may be broken; reinstall the package.",
        )
    return payload_path.read_bytes()


def build_active_py(thing_name: str) -> str:
    """Return the ``active.py`` body that names *thing_name*.

    Single-line module; ``workspace_runtime.boot()`` reads
    ``THING_NAME`` from it.  Header comment guards the file
    against well-meaning user edits — the host overwrites
    ``active.py`` on every deploy.
    """
    return (
        "# Shipped by chumicro-workspace-runtime; rewritten on each deploy.\n"
        f"THING_NAME = \"{thing_name}\"\n"
    )


def boot_shim_files(
    *,
    thing_name: str,
    entrypoint_filename: str = "code.py",
) -> dict[str, bytes]:
    """Return the static "shim layer" file map.

    Includes the entrypoint shim (``code.py`` / ``main.py``),
    ``active.py``, the on-device ``workspace_runtime`` module,
    the ``things/`` package init, and an empty
    ``things/<thing_name>/__init__.py``.  The thing's own files
    are NOT included here — :func:`thing_boot_source` adds them.

    Args:
        thing_name: Active thing name; written into ``active.py``
            and used to construct the ``things.<name>`` package
            init path.
        entrypoint_filename: ``"code.py"`` for CircuitPython,
            ``"main.py"`` for MicroPython.

    Returns:
        Path → bytes map ready to merge into a deploy file map.
    """
    thing_init_path = f"/lib/things/{thing_name}/__init__.py"
    return {
        f"/{entrypoint_filename}": SHIM_ENTRYPOINT_SOURCE.encode("utf-8"),
        "/active.py": build_active_py(thing_name).encode("utf-8"),
        BOOT_MODULE_DEVICE_PATH: load_workspace_runtime_payload(),
        THINGS_PACKAGE_INIT_DEVICE_PATH: b"",
        thing_init_path: b"",
    }


def _walk_thing_files(
    thing_dir: Path,
    *,
    thing_name: str,
    extra_excluded: Iterable[str] = (),
) -> dict[str, bytes]:
    """Walk *thing_dir* and return ``/lib/things/<name>/...`` → bytes.

    Skips ``config.{toml,yml,yaml}`` (host-only), ``_generated/``
    (deploy artifacts), and the usual cache / dotfile noise.
    *extra_excluded* augments the skip set.
    """
    excluded = _DEFAULT_EXCLUDED_DIRS | set(extra_excluded)
    collected: dict[str, bytes] = {}
    for source_path in sorted(thing_dir.rglob("*")):
        if not source_path.is_file():
            continue
        relative = source_path.relative_to(thing_dir)
        parts = relative.parts
        if any(part in excluded for part in parts):
            continue
        if relative.name in _THING_HOST_ONLY_NAMES:
            continue
        device_relative = "/".join(parts)
        device_path = f"/lib/things/{thing_name}/{device_relative}"
        collected[device_path] = source_path.read_bytes()
    return collected


class _BootShimSource:
    """``FileSource``-shaped wrapper for the boot-shim deploy layout.

    Internal — :func:`thing_boot_source` returns the public
    :class:`WithRuntimeConfig` wrapper around an instance.  Kept
    private because the boot-shim layout is convention, and the
    convention's externally-facing surface is the helper function.
    """

    def __init__(
        self,
        *,
        thing_dir: Path,
        thing_name: str,
        entrypoint_filename: str,
        extra_excluded: Iterable[str] = (),
    ) -> None:
        self._thing_dir = thing_dir
        self._thing_name = thing_name
        self._entrypoint_filename = entrypoint_filename
        self._extra_excluded = tuple(extra_excluded)

    def files(self) -> dict[str, bytes]:
        """Combine shim layer + thing files at their on-device paths."""
        files = boot_shim_files(
            thing_name=self._thing_name,
            entrypoint_filename=self._entrypoint_filename,
        )
        files.update(
            _walk_thing_files(
                self._thing_dir,
                thing_name=self._thing_name,
                extra_excluded=self._extra_excluded,
            ),
        )
        return files

    def entrypoint(self) -> str:
        """Return the on-device entrypoint path the runtime executes."""
        return f"/{self._entrypoint_filename}"


def thing_boot_source(
    thing_dir: Path,
    *,
    workspace: WorkspaceLayout,
    thing_name: str | None = None,
    entrypoint_filename: str = "code.py",
    workspace_yaml: Path | None = None,
    secrets_yaml: Path | None = None,
    extra_excluded: Iterable[str] = (),
) -> WithRuntimeConfig:
    """Build a deploy-ready ``FileSource`` using the boot-shim layout.

    Bundles the static shim layer (entrypoint + ``active.py`` +
    ``workspace_runtime`` payload + ``things/`` package markers)
    with the thing's own files (under
    ``/lib/things/<name>/``) and the merged runtime-config
    msgpack (via :class:`WithRuntimeConfig`).

    Args:
        thing_dir: ``things/<name>/`` directory.
        workspace: Resolved :class:`WorkspaceLayout`.  Used to
            locate ``workspace.yml`` / ``secrets.yml`` defaults
            when those args are ``None``.
        thing_name: Override the directory name as the active
            thing name.  Defaults to ``thing_dir.name``.
        entrypoint_filename: ``"code.py"`` for CP, ``"main.py"``
            for MP.  Decides the host-side filename for the shim
            stub written at the device root.
        workspace_yaml: Override ``workspace_yaml`` path.
        secrets_yaml: Override ``secrets_yaml`` path.
        extra_excluded: Additional filename / directory names to
            skip on the thing walk.

    Raises:
        FileNotFoundError: When *thing_dir* contains no
            recognized config file.
    """
    if workspace_yaml is None:
        workspace_yaml = workspace.workspace_yaml
    if secrets_yaml is None:
        secrets_yaml = workspace.secrets_yaml
    resolved_name = thing_name if thing_name is not None else thing_dir.name

    inner = _BootShimSource(
        thing_dir=thing_dir,
        thing_name=resolved_name,
        entrypoint_filename=entrypoint_filename,
        extra_excluded=extra_excluded,
    )
    return WithRuntimeConfig(
        inner,
        workspace_yaml=workspace_yaml,
        thing_config=find_thing_config(thing_dir),
        secrets_yaml=secrets_yaml,
        output_path=thing_dir / GENERATED_DIRNAME / "runtime_config.msgpack",
    )
