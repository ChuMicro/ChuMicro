"""Boot-shim deploy pattern per Decision 0029 §3.

The boot shim layer is a fixed set of files written onto the
device alongside the thing's app code:

* ``/code.py`` (CP) or ``/main.py`` (MP) — two-line bootstrapper
  that imports :mod:`workspace_runtime` and calls ``boot()``.
* ``/active.py`` — names the active thing
  (``THING_NAME = "<dotted-name>"``).  Nested things use the
  dotted form (``"upstairs.bedroom_sensor"``) so
  ``things.<THING_NAME>.app`` resolves directly via Python's
  import machinery.
* ``/lib/workspace_runtime/__init__.py`` — the on-device boot
  module shipped as a payload from this package.
* ``/lib/things/__init__.py`` + one ``__init__.py`` per
  namespace level under the thing — package markers that let
  ``things.<seg1>.<seg2>...<thing>.app`` resolve.

The thing's own files land at
``/lib/things/<seg1>/<seg2>/.../<thing>/`` (rather than the top-of-filesystem
layout the simpler :func:`thing_directory_source` produces).  This keeps
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
default deploys still use the flat
:func:`thing_directory_source` layout.  Opt-in because the boot
shim is workspace-runtime convention — workspaces / templates
that don't follow it (third-party templates per Decision 0032)
keep working unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from chumicro_workspace.deploy_source import (
    GENERATED_DIRNAME,
    RUNTIME_CONFIG_DEVICE_PATH,
    WithRuntimeConfig,
    find_thing_config,
)
from chumicro_workspace.pipeline import build_runtime_config

if TYPE_CHECKING:  # pragma: no cover — type-only
    from chumicro_deploy import FileMapSource

    from chumicro_workspace.workspace import WorkspaceLayout

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
    "# Shipped by chumicro-workspace; do not edit.\n"
    "import workspace_runtime\n"
    "workspace_runtime.boot()\n"
)

#: Directory under :mod:`chumicro_workspace`'s package
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


# ---------------------------------------------------------------------------
# Nested-name helpers
# ---------------------------------------------------------------------------


def _dotted_thing_name(thing_name: str) -> str:
    """Return *thing_name* in dotted form.

    Accepts dotted (``"upstairs.bedroom_sensor"``) or slash
    (``"upstairs/bedroom_sensor"``) input.  The dotted form is
    written into ``/active.py`` because ``workspace_runtime.boot``
    constructs ``things.<THING_NAME>.app`` via string concatenation.
    """
    return thing_name.replace("/", ".")


def _thing_segments(thing_name: str) -> tuple[str, ...]:
    """Split *thing_name* on ``.`` / ``/`` into per-namespace segments."""
    return tuple(_dotted_thing_name(thing_name).split("."))


def _device_thing_dir(thing_name: str) -> str:
    """Return the on-device dir prefix for *thing_name*'s payload files.

    Single-segment ``"weather"`` → ``"/lib/things/weather"``;
    nested ``"garage/sensors/door_open"`` →
    ``"/lib/things/garage/sensors/door_open"``.
    """
    return "/lib/things/" + "/".join(_thing_segments(thing_name))


def _namespace_init_paths(thing_name: str) -> list[str]:
    """Return ``__init__.py`` device paths for every level above the thing.

    Includes the thing's own ``/lib/things/<...>/<thing>/__init__.py``
    leaf; excludes ``/lib/things/__init__.py`` (caller adds it via
    :data:`THINGS_PACKAGE_INIT_DEVICE_PATH`).  Single-segment names
    return one path; an N-segment dotted name returns N paths.
    """
    segments = _thing_segments(thing_name)
    return [
        "/lib/things/" + "/".join(segments[:depth]) + "/__init__.py"
        for depth in range(1, len(segments) + 1)
    ]


def _per_thing_runtime_config_device_path(thing_name: str) -> str:
    """On-device path of *thing_name*'s per-thing runtime-config msgpack.

    Multi-thing deploys ship one msgpack per installed thing under
    ``/lib/things/<...>/<thing>/runtime_config.msgpack`` so future
    switch flows can copy the right one to
    :data:`RUNTIME_CONFIG_DEVICE_PATH` without re-reading host config
    files.
    """
    return _device_thing_dir(thing_name) + "/runtime_config.msgpack"


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


def build_active_py(thing_name: str) -> str:
    """Return the ``active.py`` body that names *thing_name*.

    Single-line module; ``workspace_runtime.boot()`` reads
    ``THING_NAME`` from it.  Header comment guards the file
    against well-meaning user edits — the host overwrites
    ``active.py`` on every deploy.

    *thing_name* is normalised to dotted form before being written
    so nested-thing names (passed in either dotted or slash form)
    end up as the import-shaped ``"upstairs.bedroom_sensor"`` that
    :func:`workspace_runtime.boot` concatenates into
    ``things.<THING_NAME>.app``.
    """
    dotted = _dotted_thing_name(thing_name)
    return (
        "# Shipped by chumicro-workspace; rewritten on each deploy.\n"
        f"THING_NAME = \"{dotted}\"\n"
    )


def boot_shim_files(
    *,
    thing_name: str,
    entrypoint_filename: str = "code.py",
) -> dict[str, bytes]:
    """Return the static "shim layer" file map.

    Includes the entrypoint shim (``code.py`` / ``main.py``),
    ``active.py``, the on-device ``workspace_runtime`` module,
    the ``things/`` package init, and one empty ``__init__.py`` for
    every namespace level beneath ``things/`` down to and including
    the thing's own directory.  The thing's own files are NOT
    included here — :func:`thing_boot_source` adds them.

    Args:
        thing_name: Active thing name (bare, slash, or dotted form).
            Written into ``active.py`` and used to construct the
            namespace ``__init__.py`` paths.
        entrypoint_filename: ``"code.py"`` for CircuitPython,
            ``"main.py"`` for MicroPython.

    Returns:
        Path → bytes map ready to merge into a deploy file map.
    """
    files: dict[str, bytes] = {
        f"/{entrypoint_filename}": SHIM_ENTRYPOINT_SOURCE.encode("utf-8"),
        "/active.py": build_active_py(thing_name).encode("utf-8"),
        BOOT_MODULE_DEVICE_PATH: load_workspace_runtime_payload(),
        THINGS_PACKAGE_INIT_DEVICE_PATH: b"",
    }
    for init_path in _namespace_init_paths(thing_name):
        files[init_path] = b""
    return files


def _walk_thing_files(
    thing_dir: Path,
    *,
    thing_name: str,
    extra_excluded: Iterable[str] = (),
) -> dict[str, bytes]:
    """Walk *thing_dir* and return ``/lib/things/<...>/<name>/...`` → bytes.

    Skips ``config.{toml,yml,yaml}`` (host-only), ``_generated/``
    (deploy artifacts), and the usual cache / dotfile noise.
    *extra_excluded* augments the skip set.  *thing_name* drives the
    on-device prefix via :func:`_device_thing_dir` so nested thing
    names produce nested paths.
    """
    excluded = _DEFAULT_EXCLUDED_DIRS | set(extra_excluded)
    device_prefix = _device_thing_dir(thing_name)
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
        device_path = f"{device_prefix}/{device_relative}"
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
    ``workspace_runtime`` payload + namespace ``__init__.py`` markers)
    with the thing's own files (under
    ``/lib/things/<...>/<thing>/``) and the merged runtime-config
    msgpack (via :class:`WithRuntimeConfig`).

    Args:
        thing_dir: Filesystem path to the thing directory.  May be
            nested (``things/garage/sensors/door_open/``); the
            on-device layout follows the same nesting.
        workspace: Resolved :class:`WorkspaceLayout`.  Used to
            locate ``workspace.yml`` / ``secrets.yml`` defaults
            when those args are ``None``.
        thing_name: Bare, slash, or dotted name for the active thing.
            Required for nested layouts (the directory's basename
            alone loses the namespace prefix).  Defaults to
            ``thing_dir.name`` for flat layouts.
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


# ---------------------------------------------------------------------------
# Multi-thing-on-one-device support
# ---------------------------------------------------------------------------


def multi_thing_boot_files(
    *,
    active_thing_name: str,
    thing_names: Iterable[str],
    entrypoint_filename: str = "code.py",
) -> dict[str, bytes]:
    """Static shim layer for a multi-thing layout.

    Same shape as :func:`boot_shim_files` but registers a
    ``__init__.py`` chain for every name in *thing_names* — not just
    the active one — so all installed things are importable.
    Namespace inits are deduped across things (two siblings under the
    same namespace share one ``/lib/things/<ns>/__init__.py``).
    ``/active.py`` still names a single active thing via
    :func:`build_active_py`.

    Args:
        active_thing_name: Which thing ``/active.py`` points at (bare,
            slash, or dotted).  Must appear in *thing_names* (raises
            ``ValueError`` otherwise).
        thing_names: Every thing to register a namespace chain for.
            Order is irrelevant; duplicates collapse silently.
        entrypoint_filename: ``"code.py"`` for CP, ``"main.py"`` for MP.

    Returns:
        Path → bytes map ready to merge into a deploy file map.

    Raises:
        ValueError: When *thing_names* is empty or *active_thing_name*
            isn't one of the registered names.
    """
    distinct_names = list(dict.fromkeys(thing_names))
    if not distinct_names:
        raise ValueError("multi_thing_boot_files requires at least one thing")
    if active_thing_name not in distinct_names:
        raise ValueError(
            f"active_thing_name={active_thing_name!r} not in thing_names "
            f"({sorted(distinct_names)})",
        )
    files: dict[str, bytes] = {
        f"/{entrypoint_filename}": SHIM_ENTRYPOINT_SOURCE.encode("utf-8"),
        "/active.py": build_active_py(active_thing_name).encode("utf-8"),
        BOOT_MODULE_DEVICE_PATH: load_workspace_runtime_payload(),
        THINGS_PACKAGE_INIT_DEVICE_PATH: b"",
    }
    for thing_name in distinct_names:
        for init_path in _namespace_init_paths(thing_name):
            files.setdefault(init_path, b"")
    return files


class _MultiThingBootSource:
    """``FileSource``-shaped wrapper for multi-thing boot-shim deploys.

    Internal — :func:`multi_thing_boot_source` is the public surface.
    Kept private because the multi-thing layout is convention; users
    should reach it via the helper rather than constructing the class
    directly.

    Each call to :meth:`files` rebuilds every per-thing msgpack so
    config edits in any thing surface on the next deploy.  The active
    thing's msgpack is also placed at :data:`RUNTIME_CONFIG_DEVICE_PATH`
    so existing app code that reads from the canonical workspace-wide
    path keeps working.
    """

    def __init__(
        self,
        *,
        thing_dirs: Sequence[Path],
        thing_names: Sequence[str],
        active_thing_name: str,
        entrypoint_filename: str,
        workspace_yaml: Path,
        secrets_yaml: Path,
        extra_excluded: Iterable[str] = (),
    ) -> None:
        self._thing_dirs = list(thing_dirs)
        self._thing_names = list(thing_names)
        self._active_thing_name = active_thing_name
        self._entrypoint_filename = entrypoint_filename
        self._workspace_yaml = workspace_yaml
        self._secrets_yaml = secrets_yaml
        self._extra_excluded = tuple(extra_excluded)

    def files(self) -> dict[str, bytes]:
        """Combine shim layer + every thing's files + per-thing msgpacks."""
        files = multi_thing_boot_files(
            active_thing_name=self._active_thing_name,
            thing_names=self._thing_names,
            entrypoint_filename=self._entrypoint_filename,
        )
        active_msgpack: bytes | None = None
        for thing_dir, thing_name in zip(
            self._thing_dirs, self._thing_names, strict=True,
        ):
            files.update(
                _walk_thing_files(
                    thing_dir,
                    thing_name=thing_name,
                    extra_excluded=self._extra_excluded,
                ),
            )
            output_path = (
                thing_dir / GENERATED_DIRNAME / "runtime_config.msgpack"
            )
            build_runtime_config(
                workspace_yaml=self._workspace_yaml,
                thing_config=find_thing_config(thing_dir),
                secrets_yaml=self._secrets_yaml,
                output_path=output_path,
            )
            msgpack_bytes = output_path.read_bytes()
            files[_per_thing_runtime_config_device_path(thing_name)] = msgpack_bytes
            if thing_name == self._active_thing_name:
                active_msgpack = msgpack_bytes
        # The check in __init__ guarantees the active thing is in the
        # list, so active_msgpack is always assigned by the loop.
        assert active_msgpack is not None  # noqa: S101 — invariant
        files[RUNTIME_CONFIG_DEVICE_PATH] = active_msgpack
        return files

    def entrypoint(self) -> str:
        """Return the on-device entrypoint path (``/code.py`` or ``/main.py``)."""
        return f"/{self._entrypoint_filename}"


def multi_thing_boot_source(
    thing_dirs: Sequence[Path],
    *,
    workspace: WorkspaceLayout,
    thing_names: Sequence[str] | None = None,
    active_thing_name: str | None = None,
    entrypoint_filename: str = "code.py",
    workspace_yaml: Path | None = None,
    secrets_yaml: Path | None = None,
    extra_excluded: Iterable[str] = (),
) -> _MultiThingBootSource:
    """Build a deploy-ready ``FileSource`` shipping multiple things.

    Each thing's files land at ``/lib/things/<...>/<name>/...``; each thing's
    runtime config lands at ``/lib/things/<...>/<name>/runtime_config.msgpack``.
    The active thing's runtime config also appears at the canonical
    :data:`RUNTIME_CONFIG_DEVICE_PATH` so existing app code keeps
    reading it from the workspace-wide path.

    Args:
        thing_dirs: ``things/<...>/<name>/`` directories to ship.
        workspace: Resolved :class:`WorkspaceLayout`.
        thing_names: Bare / slash / dotted names matching *thing_dirs*
            position-by-position.  Required for nested layouts where
            the directory basename alone loses the namespace prefix.
            Defaults to ``[thing_dir.name for thing_dir in thing_dirs]``
            for flat layouts.
        active_thing_name: Which thing ``/active.py`` names.  Defaults
            to the first *thing_names* entry.
        entrypoint_filename: ``"code.py"`` for CP, ``"main.py"`` for MP.
        workspace_yaml: Override the workspace's ``workspace.yml`` path.
        secrets_yaml: Override the workspace's ``secrets.yml`` path.
        extra_excluded: Extra filenames / directory names to skip on
            each thing's directory walk.

    Raises:
        ValueError: When *thing_dirs* is empty, contains duplicate
            names, *thing_names* doesn't match *thing_dirs* in length,
            or *active_thing_name* doesn't match one of the entries.
        FileNotFoundError: When any of the listed thing directories has
            no recognized config file.
    """
    if not thing_dirs:
        raise ValueError("multi_thing_boot_source requires at least one thing")
    if thing_names is None:
        resolved_names = [thing_dir.name for thing_dir in thing_dirs]
    else:
        if len(thing_names) != len(thing_dirs):
            raise ValueError(
                "multi_thing_boot_source: thing_names length "
                f"({len(thing_names)}) does not match thing_dirs "
                f"length ({len(thing_dirs)})",
            )
        resolved_names = list(thing_names)
    if len(set(resolved_names)) != len(resolved_names):
        duplicates = sorted(
            {name for name in resolved_names if resolved_names.count(name) > 1},
        )
        raise ValueError(
            f"multi_thing_boot_source: duplicate thing names {duplicates}",
        )
    resolved_active = (
        active_thing_name if active_thing_name is not None else resolved_names[0]
    )
    if resolved_active not in resolved_names:
        raise ValueError(
            f"active_thing_name={resolved_active!r} not in thing_dirs "
            f"({resolved_names})",
        )
    # Surface a missing-config error eagerly rather than waiting for the
    # first files() call so the CLI can report it before transport setup.
    for thing_dir in thing_dirs:
        find_thing_config(thing_dir)
    return _MultiThingBootSource(
        thing_dirs=thing_dirs,
        thing_names=resolved_names,
        active_thing_name=resolved_active,
        entrypoint_filename=entrypoint_filename,
        workspace_yaml=workspace_yaml if workspace_yaml is not None else workspace.workspace_yaml,
        secrets_yaml=secrets_yaml if secrets_yaml is not None else workspace.secrets_yaml,
        extra_excluded=extra_excluded,
    )


# ---------------------------------------------------------------------------
# Switch — re-point /active.py without re-shipping thing payloads
# ---------------------------------------------------------------------------


def build_switch_files(
    *,
    thing_name: str,
    runtime_config_msgpack: bytes,
    entrypoint_filename: str = "code.py",
) -> dict[str, bytes]:
    """File map that swaps the active thing.

    Returns the three files a switch needs: the entrypoint shim
    (re-staged byte-identical so the transport's "execute entrypoint"
    contract is satisfied — the entrypoint must be in ``files()``),
    the new ``/active.py`` naming the new thing, and the new
    ``/runtime_config.msgpack`` carrying the new thing's merged config.

    The thing payloads under ``/lib/things/<...>/<name>/`` are NOT
    touched — they stay on flash from the prior
    :func:`multi_thing_boot_source` deploy, which is what makes switch
    fast.

    Args:
        thing_name: Name of the thing to make active (bare, slash, or
            dotted form).  Normalised to dotted before being written
            into ``/active.py``.
        runtime_config_msgpack: Pre-built msgpack bytes for that thing's
            merged config.  Caller produces this via
            :func:`build_runtime_config` (or reads it from a
            previously-staged per-thing msgpack on disk).
        entrypoint_filename: ``"code.py"`` for CP, ``"main.py"`` for MP.
    """
    return {
        f"/{entrypoint_filename}": SHIM_ENTRYPOINT_SOURCE.encode("utf-8"),
        "/active.py": build_active_py(thing_name).encode("utf-8"),
        RUNTIME_CONFIG_DEVICE_PATH: runtime_config_msgpack,
    }


def switch_source(
    thing_dir: Path,
    *,
    workspace: WorkspaceLayout,
    thing_name: str | None = None,
    entrypoint_filename: str = "code.py",
    workspace_yaml: Path | None = None,
    secrets_yaml: Path | None = None,
) -> FileMapSource:
    """``FileMapSource`` that switches the active thing on a multi-thing device.

    Builds the merged runtime-config msgpack for *thing_dir* on the
    host, then returns a :class:`FileMapSource` shipping only the
    three switch files — no thing payloads, no shim layer files
    beyond the entrypoint.  Use with :class:`Deployer.deploy()`; the
    device boots into the new thing on the next reset.

    Args:
        thing_dir: ``things/<...>/<name>/`` directory of the thing to
            switch to.  Must already have been included in a prior
            :func:`multi_thing_boot_source` deploy or this switch will
            boot a thing whose payload isn't on the device.
        workspace: Resolved :class:`WorkspaceLayout`.
        thing_name: Override the directory's basename as the active
            thing name.  Required for nested layouts; otherwise
            defaults to ``thing_dir.name``.
        entrypoint_filename: ``"code.py"`` for CP, ``"main.py"`` for MP.
        workspace_yaml: Override the workspace's ``workspace.yml`` path.
        secrets_yaml: Override the workspace's ``secrets.yml`` path.

    Raises:
        FileNotFoundError: When *thing_dir* contains no recognized
            config file.
    """
    from chumicro_deploy import FileMapSource  # noqa: PLC0415

    resolved_name = thing_name if thing_name is not None else thing_dir.name
    resolved_workspace_yaml = (
        workspace_yaml if workspace_yaml is not None else workspace.workspace_yaml
    )
    resolved_secrets_yaml = (
        secrets_yaml if secrets_yaml is not None else workspace.secrets_yaml
    )
    output_path = thing_dir / GENERATED_DIRNAME / "runtime_config.msgpack"
    build_runtime_config(
        workspace_yaml=resolved_workspace_yaml,
        thing_config=find_thing_config(thing_dir),
        secrets_yaml=resolved_secrets_yaml,
        output_path=output_path,
    )
    files = build_switch_files(
        thing_name=resolved_name,
        runtime_config_msgpack=output_path.read_bytes(),
        entrypoint_filename=entrypoint_filename,
    )
    return FileMapSource(files, entrypoint=f"/{entrypoint_filename}")
