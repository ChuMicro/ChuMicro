"""Build a deploy-ready FileSource for a single library example.

Composes :class:`ImportGraphSource` and :class:`WithRuntimeConfig` into
a ``FileSource`` the ``deploy-example`` CLI hands straight to
``Deployer.deploy_diff()``.  See :func:`example_source` for the
contract.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from chumicro_workspace.config_manifest import find_library_roots
from chumicro_workspace.deploy_source import (
    GENERATED_DIRNAME,
    WithRuntimeConfig,
)

#: On-device entrypoint name keyed by runtime.  CircuitPython runs
#: ``code.py`` at boot; MicroPython runs ``main.py``.  CPython has no
#: device-level entrypoint convention — passed in here as ``"cpython"``
#: only when a host-side test exercises the source machinery.
_ENTRYPOINT_BY_RUNTIME: dict[str, str] = {
    "circuitpython": "/code.py",
    "micropython": "/main.py",
    "cpython": "/code.py",
}


def _resolve_example_path(library_root: Path, example_name: str) -> Path:
    """Return the host path to ``libraries/<lib>/examples/<name>.py``.

    Strips a trailing ``.py`` from *example_name* if the caller
    supplied it — both ``"circuitpython_blink"`` and
    ``"circuitpython_blink.py"`` resolve to the same file.
    """
    stem = example_name[:-3] if example_name.endswith(".py") else example_name
    return library_root / "examples" / f"{stem}.py"


def _default_output_path(library_root: Path, example_name: str) -> Path:
    """Default output path for the generated msgpack.

    Lives under ``libraries/<lib>/examples/_generated/`` — the same
    ``_generated/`` build-artifact convention :class:`WithRuntimeConfig`
    uses for project deploys, gitignored so it isn't committed beside
    the tracked example source.
    """
    stem = example_name[:-3] if example_name.endswith(".py") else example_name
    return (
        library_root
        / "examples"
        / GENERATED_DIRNAME
        / f"example_runtime_config_{library_root.name}_{stem}.msgpack"
    )


def example_source(
    library_root: Path,
    example_name: str,
    *,
    library_roots: Iterable[Path],
    runtime: str,
    secrets_toml: Path,
    output_path: Path | None = None,
    extra_modules: list[str] | None = None,
) -> WithRuntimeConfig:
    """Build a deploy-ready ``FileSource`` for a single library example.

    Reads ``libraries/<lib>/examples/<example_name>.py``, walks its
    Python imports against ``<root>/src`` for every entry in
    *library_roots*, and wraps the result with
    :class:`WithRuntimeConfig` so a single ``Deployer.deploy_diff(source)``
    call ships the example as ``/code.py`` (CP) or ``/main.py`` (MP)
    plus every reachable ``chumicro_*`` module under ``/lib/`` plus
    a ``/runtime_config.msgpack`` baked from ``secrets.toml``.

    Examples have no per-example config.  The runtime config they
    receive is just ``secrets.toml`` contents.  A library that needs
    example-specific values writes them inline in the example source.

    Manifest validation is automatic: each ``library_roots`` entry's
    ``[tool.chumicro.config]`` block is unioned by ``WithRuntimeConfig``
    and validated against the merged config before the msgpack is
    written.  A missing required key fails the deploy-time precheck
    with a precise error.

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
        output_path: Where to write the generated
            ``runtime_config.msgpack`` on the host.  Defaults to
            ``libraries/<lib>/examples/_generated/example_runtime_config_<lib>_<name>.msgpack``
            (the gitignored ``_generated/`` build-artifact convention).
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
        ready to hand to ``Deployer.deploy_diff(source)``.
    """
    from chumicro_deploy import ImportGraphSource  # noqa: PLC0415

    if runtime not in _ENTRYPOINT_BY_RUNTIME:
        raise ValueError(
            f"runtime must be one of "
            f"{sorted(_ENTRYPOINT_BY_RUNTIME)}, got {runtime!r}",
        )

    entrypoint_path = _resolve_example_path(library_root, example_name)
    device_entrypoint = _ENTRYPOINT_BY_RUNTIME[runtime]

    # Search paths: each library's src/ directory + the current
    # example's own examples/ directory (so a peer `helpers.py`
    # alongside the entrypoint resolves and rides along to /lib/).
    # Drop duplicates while preserving order — the example's own
    # library naturally appears in *library_roots* if the caller
    # passed the full libraries/ glob, but a caller who didn't can
    # still reach the owning library's modules.
    seen: set[Path] = set()
    search_paths: list[Path] = []
    examples_dir = library_root / "examples"
    if examples_dir.is_dir():
        resolved = examples_dir.resolve()
        seen.add(resolved)
        search_paths.append(examples_dir)
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

    if output_path is None:
        output_path = _default_output_path(library_root, example_name)

    return WithRuntimeConfig(
        inner,
        secrets_toml=secrets_toml,
        project_config=None,
        output_path=output_path,
        library_roots=find_library_roots(search_paths),
    )
