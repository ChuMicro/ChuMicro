"""Build a deploy-ready FileSource for a single library example.

The ``deploy-example`` front-door command ships
``libraries/<lib>/examples/<name>.py`` to a board as ``code.py``
(CircuitPython) or ``main.py`` (MicroPython), bringing along every
``chumicro_*`` module the example imports under ``/lib/`` and a
merged ``runtime_config.msgpack`` baked from ``secrets.toml`` plus
an optional per-example ``examples/config.toml``.

This module owns the shape of that source.  The CLI just asks for
one and hands it to ``Deployer.deploy()`` like any other
``FileSource``.

The shape composes existing pieces:

* ``ImportGraphSource`` walks the example's ``import`` graph and
  resolves each module against the union of every
  ``libraries/<name>/src`` directory.  Wrong-runtime files
  (``__chumicro_runtimes__`` marker mismatch) drop out automatically.
* ``WithRuntimeConfig`` merges ``secrets.toml`` + the per-example
  config (if present) into ``/runtime_config.msgpack`` and validates
  the merged dict against each library's ``[tool.chumicro.config]``
  manifest before writing.

What this module adds:

* Resolves the example file under ``libraries/<lib>/examples/<name>.py``.
* Picks the on-device entrypoint name from the *runtime* arg
  (``code.py`` for CircuitPython, ``main.py`` for MicroPython).
* Sensible default ``output_path`` for the generated msgpack —
  ``<secrets_toml>.parent/.scratch/example_runtime_config_<lib>_<name>.msgpack``
  so the artifact lands in the gitignored ``.scratch/`` tree, never
  inside the tracked ``libraries/<lib>/examples/`` folder.

Scoped to working trees that own a ``libraries/<lib>/`` directory
layout (the upstream chumicro source tree).  Workspace template
repos that grow user-authored library trees of the same shape can
adopt the helper later — it's general over the directory layout,
not the upstream consumer.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from chumicro_workspace.config_manifest import find_library_roots
from chumicro_workspace.deploy_source import WithRuntimeConfig

if TYPE_CHECKING:  # pragma: no cover — type-only
    pass

#: On-device entrypoint name keyed by runtime.  CircuitPython runs
#: ``code.py`` at boot; MicroPython runs ``main.py``.  CPython has no
#: device-level entrypoint convention — passed in here as ``"cpython"``
#: only when a host-side test exercises the source machinery; the
#: deploy CLI rejects ``cpython`` upstream.
_ENTRYPOINT_BY_RUNTIME: dict[str, str] = {
    "circuitpython": "/code.py",
    "micropython": "/main.py",
    "cpython": "/code.py",  # test-only; never deployed to a device
}


def _resolve_example_path(library_root: Path, example_name: str) -> Path:
    """Return the host path to ``libraries/<lib>/examples/<name>.py``.

    Strips a trailing ``.py`` from *example_name* if the caller
    supplied it — both ``"circuitpython_blink"`` and
    ``"circuitpython_blink.py"`` resolve to the same file.
    """
    stem = example_name[:-3] if example_name.endswith(".py") else example_name
    return library_root / "examples" / f"{stem}.py"


def _default_output_path(
    secrets_toml: Path, library_root: Path, example_name: str,
) -> Path:
    """Default scratch path for the generated msgpack.

    Lives under ``<secrets_toml>.parent/.scratch/`` so the artifact
    lands in the gitignored scratch tree, never inside the tracked
    ``libraries/<lib>/examples/`` folder.
    """
    stem = example_name[:-3] if example_name.endswith(".py") else example_name
    return (
        secrets_toml.parent
        / ".scratch"
        / f"example_runtime_config_{library_root.name}_{stem}.msgpack"
    )


def example_source(
    library_root: Path,
    example_name: str,
    *,
    library_roots: Iterable[Path],
    runtime: str,
    secrets_toml: Path,
    project_config: Path | None = None,
    output_path: Path | None = None,
    extra_modules: list[str] | None = None,
) -> WithRuntimeConfig:
    """Build a deploy-ready ``FileSource`` for a single library example.

    Reads ``libraries/<lib>/examples/<example_name>.py``, walks its
    Python imports against ``<root>/src`` for every entry in
    *library_roots*, and wraps the result with
    :class:`WithRuntimeConfig` so a single ``Deployer.deploy(source)``
    call ships the example as ``/code.py`` (CP) or ``/main.py`` (MP)
    plus every reachable ``chumicro_*`` module under ``/lib/`` plus
    the merged ``/runtime_config.msgpack``.

    Wrong-runtime files (``__chumicro_runtimes__`` marker mismatch)
    drop out automatically — neither the example file nor any walked
    module lands on the device unless its marker matches *runtime*.

    Manifest validation is automatic: each ``library_roots`` entry's
    ``[tool.chumicro.config]`` block is unioned by ``WithRuntimeConfig``
    and validated against the merged config before the msgpack is
    written.  A missing required key fails the deploy-time precheck
    with a precise error instead of a cryptic ``MissingConfigKey``
    on the board.

    Args:
        library_root: Path to ``libraries/<lib>/`` — the library this
            example belongs to.  Used to resolve
            ``examples/<example_name>.py``; ``<library_root>/src`` is
            included in the search paths automatically (added once
            even if also present in *library_roots*).
        example_name: Filename stem under
            ``<library_root>/examples/`` — the trailing ``.py`` is
            optional (``"circuitpython_blink"`` and
            ``"circuitpython_blink.py"`` both resolve).
        library_roots: Every ``libraries/<name>/`` path the example
            might import from.  Each contributes ``<root>/src`` to
            ``ImportGraphSource``'s search paths and is read by
            ``WithRuntimeConfig`` for ``[tool.chumicro.config]``
            manifest validation.  Typically every directory under
            the mono-repo's ``libraries/``.
        runtime: ``"circuitpython"`` (entrypoint ``/code.py``),
            ``"micropython"`` (entrypoint ``/main.py``), or
            ``"cpython"`` (host-side test only — never lands on a
            device).  Forwarded to ``ImportGraphSource`` as
            ``target_runtime`` so wrong-runtime files filter out.
        secrets_toml: Path to the workspace's ``secrets.toml`` —
            workspace-wide credentials and device defaults consumed
            by ``WithRuntimeConfig``.
        project_config: Optional per-example
            ``libraries/<lib>/examples/config.toml`` (or
            ``project_config.toml`` / ``.yml`` / ``.yaml``).  When
            absent or non-existent, only ``secrets_toml`` drives the
            merged runtime config.  Defaults to looking for
            ``<library_root>/examples/config.toml`` automatically.
        output_path: Where to write the generated
            ``runtime_config.msgpack`` on the host.  Defaults to
            ``<secrets_toml>.parent/.scratch/example_runtime_config_<lib>_<name>.msgpack``
            so the artifact lands in the gitignored scratch tree.
        extra_modules: Force-included dotted module names — passed
            through to ``ImportGraphSource`` for dynamic-import
            cases the AST walker can't see.

    Raises:
        ValueError: *runtime* is not one of the accepted values.
        FileNotFoundError: The example file or *secrets_toml* doesn't
            exist (``ImportGraphSource`` raises for the example,
            ``compose_runtime_config`` raises for the secrets file).

    Returns:
        A ``WithRuntimeConfig`` wrapping an ``ImportGraphSource`` —
        ready to hand to ``Deployer.deploy(source)``.
    """
    from chumicro_deploy import ImportGraphSource  # noqa: PLC0415

    if runtime not in _ENTRYPOINT_BY_RUNTIME:
        raise ValueError(
            f"runtime must be one of "
            f"{sorted(_ENTRYPOINT_BY_RUNTIME)}, got {runtime!r}",
        )

    entrypoint_path = _resolve_example_path(library_root, example_name)
    device_entrypoint = _ENTRYPOINT_BY_RUNTIME[runtime]

    # Search paths: each library's src/ directory.  Drop duplicates
    # while preserving order — the example's own library naturally
    # appears in *library_roots* if the caller passed the full
    # libraries/ glob, but a caller who didn't can still reach the
    # owning library's modules.
    seen: set[Path] = set()
    search_paths: list[Path] = []
    for root in (library_root, *library_roots):
        src_dir = root / "src"
        if not src_dir.is_dir():
            continue
        resolved = src_dir.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        search_paths.append(src_dir)

    inner = ImportGraphSource(
        entrypoint_path,
        search_paths=search_paths,
        extra_modules=extra_modules,
        device_entrypoint=device_entrypoint,
        resource_prefix="/lib",
        target_runtime=runtime,
    )

    if project_config is None:
        project_config = library_root / "examples" / "config.toml"
    if output_path is None:
        output_path = _default_output_path(
            secrets_toml, library_root, example_name,
        )

    library_roots_for_validation = find_library_roots(search_paths)

    return WithRuntimeConfig(
        inner,
        secrets_toml=secrets_toml,
        project_config=project_config,
        output_path=output_path,
        library_roots=library_roots_for_validation,
    )
