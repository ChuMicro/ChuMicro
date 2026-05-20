"""Session-state accessors shared by plugin / device_backend / collection.

A small leaf module of ``getattr``-style helpers over the dynamic
attributes that :func:`chumicro_pytest_device.plugin.pytest_sessionstart`
stashes on the pytest ``Session``.  Lives here so the device-backend
module and the collection module can read session state without
importing plugin.py (the cycle break for the full plugin split).

Also carries the path predicates (``_is_library_functional_test`` /
``_is_library_unit_test``), the ``--target``-flag readers, and the
runtime-config encode + cache helper.

The ``_device_*`` walkers iterate over ``session.items``; they import
the ``DeviceTestItem`` type lazily inside the function body because
those items live in :mod:`collection`, which depends on this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from chumicro_deploy import (
    DeviceCaps,
    DeviceEntry,
    find_libraries_requiring_flash,
    resolve_deploy_mode,
)
from msgpack import packb

from .runtime_config import get_runtime_config
from .test_runner import (
    resolve_effective_deploy_mode,
    resolve_library_source_dirs,
)
from .transport_cache import _TransportCache

if TYPE_CHECKING:
    from .backends import Backend
    from .pr_summary import DeviceRunResult  # noqa: F401 — kept for type hints downstream


#: Canonical on-device path for the staged runtime-config payload —
#: matches :data:`chumicro_config.runtime.DEFAULT_RUNTIME_CONFIG_PATH`.
#: Hard-coded here rather than imported because workbench packages
#: don't import device libraries (they ship to host-side users via
#: PyPI, libraries ship to boards via circup / mip).
_RUNTIME_CONFIG_DEVICE_PATH = "/runtime_config.msgpack"

#: Cache of encoded runtime-config bytes keyed by ``id(payload)`` so
#: the per-stage ``packb`` cost amortises to one ``packb`` per pytest
#: invocation.  Invalidated automatically: if a fixture overwrites
#: the stashed payload, ``id()`` changes and we re-encode.
_ENCODED_RUNTIME_CONFIG_KEY: pytest.StashKey[tuple[int, bytes]] = (
    pytest.StashKey()
)


def _encode_runtime_config_extra_files(
    config: pytest.Config,
) -> dict[str, bytes] | None:
    """Return the ``extra_files`` dict to pass to ``transport.stage()``.

    Returns ``None`` when no conftest registered a payload (default
    state for libraries with no runtime-config requirements, plus the
    silent-skip path when credentials aren't configured).  Returns a
    one-entry dict mapping :data:`_RUNTIME_CONFIG_DEVICE_PATH` to the
    msgpack-encoded payload otherwise.

    Encoding uses ``use_single_float=True`` so float values round-trip
    through CircuitPython's native ``msgpack`` decoder (CP doesn't
    support float64).  Mirrors :func:`chumicro_workspace.writer.write_runtime_config`'s
    encoding contract.  The encoded bytes are cached on the config
    stash keyed by ``id(payload)`` — every device sweep stages once
    per file batch, and re-encoding the same dotted-key dict 50+ times
    is wasted work.
    """
    payload = get_runtime_config(config)
    if payload is None:
        return None
    cached = config.stash.get(_ENCODED_RUNTIME_CONFIG_KEY, None)
    if cached is not None and cached[0] == id(payload):
        return {_RUNTIME_CONFIG_DEVICE_PATH: cached[1]}
    encoded = packb(payload, use_single_float=True)
    config.stash[_ENCODED_RUNTIME_CONFIG_KEY] = (id(payload), encoded)
    return {_RUNTIME_CONFIG_DEVICE_PATH: encoded}


def _workspace_root(session: pytest.Session) -> Path:
    """Return the root of the workspace pytest was invoked against.

    Derived from ``pytest.Config.rootpath`` so the plugin works inside
    any workspace, not just one specific layout.
    """
    return Path(session.config.rootpath)


def _harness_source_dir(session: pytest.Session) -> Path:
    """Return ``support/test_harness/src`` for the on-device test harness.

    The plugin stages a lightweight test harness alongside library
    sources so ``import chumicro_test_harness`` resolves on the device.
    Workspaces without this directory won't run harness-shaped
    functional tests.
    """
    return _workspace_root(session) / "support" / "test_harness" / "src"


def _libraries_root(session: pytest.Session) -> Path:
    """Return ``libraries/`` for dependency-resolution staging."""
    return _workspace_root(session) / "libraries"


def _session_cache(session: pytest.Session) -> _TransportCache:
    """Return the session-scoped ``_TransportCache``, asserting it exists.

    ``pytest_sessionstart`` populates the dynamic attribute; any code
    path that uses the cache runs strictly after that hook.  The cast
    keeps the rest of the module free of ``# type: ignore`` noise from
    pytest's dynamic ``session`` attributes.
    """
    cache = getattr(session, "_device_transport_cache", None)
    assert cache is not None, "pytest_sessionstart must run before cache access"
    return cast("_TransportCache", cache)


def _session_targets(session: pytest.Session) -> list[DeviceEntry] | None:
    """Return the resolved target devices from ``pytest_sessionstart``."""
    targets = getattr(session, "_device_targets", None)
    if targets is None:
        return None
    return cast("list[DeviceEntry]", targets)


def _device_closure_source_dirs(
    session: pytest.Session, device_entry: DeviceEntry,
) -> list[Path]:
    """Union of every test's library source closure for one device.

    Walks the same dependency closure the staging path uses
    (:func:`resolve_library_source_dirs`) for every ``DeviceTestItem``
    targeting *device_entry*, deduplicated.  Deploy mode is
    session-scoped (one cached transport per device), so the resolver
    must see the whole device's closure up front — a functional test
    that pulls a dependency's data file has to force the session to
    flash *before* a RAM-mode transport gets cached.
    """
    from .plugin import DeviceTestItem  # noqa: PLC0415 — break import cycle

    closure: list[Path] = []
    # ``getattr`` guard mirrors the feature pass: test stubs (FakeSession)
    # don't populate ``items``; no items ⇒ empty closure ⇒ the resolver
    # returns the configured mode unchanged.
    for item in getattr(session, "items", ()):
        if not isinstance(item, DeviceTestItem):
            continue
        target = item.target_device
        if target is None or target.identifier != device_entry.identifier:
            continue
        for source_dir in resolve_library_source_dirs(
            item.library_dir,
            libraries_root=_libraries_root(session),
            test_files=[item.test_file],
        ):
            if source_dir not in closure:
                closure.append(source_dir)
    return closure


def _device_is_unit_sweep(
    session: pytest.Session, device_entry: DeviceEntry,
) -> bool:
    """True when every test targeting *device_entry* is a unit test.

    The cross-runtime *unit* suite (``libraries/<name>/tests``) and a
    *functional* run (``libraries/<name>/functional_tests``) scope
    ``staged_files`` differently: functional needs the full
    dependency closure (it exercises a dependency's data-file code
    path for real), the unit sweep needs the library's own ``src``
    only (a pure unit test cannot reach a dependency's data file by the
    runtime-boundary contract, so a dependency's data file must not
    poison every dependent suite into flash).  A run is unit-scoped
    only when *all* of the device's items are unit tests; any
    functional item makes it closure-scoped (the safe direction).
    """
    from .plugin import DeviceTestItem  # noqa: PLC0415 — break import cycle

    items = [
        item
        for item in getattr(session, "items", ())
        if isinstance(item, DeviceTestItem)
        and item.target_device is not None
        and item.target_device.identifier == device_entry.identifier
    ]
    return bool(items) and all(
        _is_library_unit_test(item.test_file) for item in items
    )


def _device_own_source_dirs(
    session: pytest.Session, device_entry: DeviceEntry,
) -> list[Path]:
    """Each tested library's *own* ``src`` dir (no dependency closure).

    The unit-sweep ``staged_files`` scope: only ``chumicro_sockets``'s
    own suite sees its ``_ca_bundle.der``; a light sockets *user*
    (``ntp``) does not, so the data file does not flip it to flash.
    """
    from .plugin import DeviceTestItem  # noqa: PLC0415 — break import cycle

    own: list[Path] = []
    for item in getattr(session, "items", ()):
        if not isinstance(item, DeviceTestItem):
            continue
        target = item.target_device
        if target is None or target.identifier != device_entry.identifier:
            continue
        source_dir = item.library_dir / "src"
        if source_dir.is_dir() and source_dir not in own:
            own.append(source_dir)
    return own


def _staged_file_names(source_dirs: list[Path]) -> list[str]:
    """Every file the closure would stage, by name.

    ``transport.stage`` copies whole ``src`` trees, so the resolver's
    "any non-``.py`` data file" check must see them all.
    ``__pycache__`` is build cruft the staging rsync never carries —
    excluding it stops a stray ``.pyc`` being misread as a shipped
    asset and wrongly forcing flash.
    """
    names: list[str] = []
    for source_dir in source_dirs:
        for path in source_dir.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                names.append(path.name)
    return names


def _session_effective_deploy_mode(
    session: pytest.Session, device_entry: DeviceEntry,
) -> str:
    """Resolve the device's deploy mode through the shared policy, once.

    Combines the precedence resolution (CLI → per-device → global →
    flash) with the one shared :func:`resolve_deploy_mode`.  Two inputs
    have opposite scoping: ``requires_flash_libs``
    is *always* the full transitive closure (a flash-only dependency
    OOMs on import regardless of test shape), while ``staged_files`` is
    caller-scoped — the full closure for a functional run (it really
    uses a dependency's data file) but the libraries' own ``src`` for
    the unit sweep (a pure unit test can't reach a dependency's data
    file, so ``sockets``'s ``_ca_bundle.der`` must not poison every
    sockets-dependent suite).  Memoized per device: the transport is
    cached per device so the mode is fixed for the session, and the
    explanation prints exactly once.
    """
    cache = _session_cache(session)
    device_id = device_entry.identifier
    memoized = cache.resolved_deploy_mode(device_id)
    if memoized is not None:
        return memoized

    deploy_mode_override = cast(
        "str | None",
        session.config.getoption("--deploy-mode", default=None),
    )
    configured = resolve_effective_deploy_mode(
        device_entry, deploy_mode_override,
    )
    closure = _device_closure_source_dirs(session, device_entry)
    staged_dirs = (
        _device_own_source_dirs(session, device_entry)
        if _device_is_unit_sweep(session, device_entry)
        else closure
    )
    mode, message = resolve_deploy_mode(
        configured,
        staged_files=_staged_file_names(staged_dirs),
        device_caps=DeviceCaps(
            supports_ram_mode=device_entry.supports_ram_mode,
        ),
        requires_flash_libs=find_libraries_requiring_flash(closure),
        resolution_unit=None,
        force=None,
    )
    if message is not None:
        import warnings  # noqa: PLC0415 — only used on the override path

        warnings.warn(f"Device {device_id!r}: {message}", stacklevel=2)
    cache.set_resolved_deploy_mode(device_id, mode)
    return mode


def _session_pr_summary(session: pytest.Session) -> object | None:
    """Return the PR-summary collector when ``--pr-summary`` is set.

    The concrete type lives in :mod:`plugin` so this module stays a
    leaf.  Callers that want the collector's interface narrow the
    return type at the call site.
    """
    return getattr(session, "_pr_summary", None)


def _session_backend(session: pytest.Session) -> Backend:
    """Return the execution backend installed for this session.

    ``pytest_sessionstart`` installs a single :class:`DeviceBackend`
    (or the unix-port equivalent once ``--target`` is wired up).
    Items dispatch through this getter so the device-vs-unix-port
    branch lives in one place — the rest of the plugin is shape-agnostic.
    """
    backend = getattr(session, "_backend", None)
    assert backend is not None, "pytest_sessionstart must run before backend access"
    return cast("Backend", backend)


def _session_per_file(session: pytest.Session) -> bool:
    """Return whether ``--per-file`` opt-in per-file reset is set."""
    return bool(session.config.getoption("--per-file", default=False))


def _is_library_functional_test(file_path: Path) -> bool:
    """Return ``True`` for ``libraries/<name>/functional_tests/test_*.py`` paths."""
    if not (
        file_path.suffix == ".py"
        and file_path.name.startswith("test_")
        and "functional_tests" in file_path.parts
    ):
        return False
    functional_index = file_path.parts.index("functional_tests")
    return (
        functional_index >= 2
        and file_path.parts[functional_index - 2] == "libraries"
    )


def _is_library_unit_test(file_path: Path) -> bool:
    """Return ``True`` for ``libraries/<name>/tests/test_*.py`` paths.

    Structural only — lane filtering layers on top of this and is
    driven by in-file markers, not the filename.  A CPython-only file
    declares ``__chumicro_runtimes__ = ("cpython",)`` and is excluded
    from the unix-port / device-unit lanes by
    :func:`_filter_targets_by_marker` (it still runs under plain
    CPython pytest).  A host-only file declares
    ``__chumicro_host_only__ = True`` and is excluded from the
    on-device unit sweep by :func:`pytest_collect_file` /
    :func:`pytest_pycollect_makemodule` (it still runs on the
    unix-ports and CPython).  The marker is the contract; the filename
    is never inspected for lane.
    """
    if not (
        file_path.suffix == ".py"
        and file_path.name.startswith("test_")
        and "tests" in file_path.parts
    ):
        return False
    tests_index = file_path.parts.index("tests")
    return (
        tests_index >= 2
        and file_path.parts[tests_index - 2] == "libraries"
    )


def _target_is_unix_port(config: pytest.Config) -> bool:
    """Return ``True`` when ``--target unix-port`` is in effect."""
    return cast(
        "str",
        config.getoption("--target", default="device"),
    ) == "unix-port"


def _target_is_device_unit(config: pytest.Config) -> bool:
    """Return ``True`` when ``--target device-unit`` is in effect.

    The on-device unit sweep: the cross-runtime
    ``libraries/<name>/tests`` suite routed to the device transport
    backend instead of the unix-port subprocess.  ``--target device``
    stays functional-only; this is opt-in so existing functional runs
    and IDE play buttons are unaffected.
    """
    return cast(
        "str",
        config.getoption("--target", default="device"),
    ) == "device-unit"


def _collect_unit_tests_on_device_backend(config: pytest.Config) -> bool:
    """Route ``libraries/<name>/tests`` through the harness backend.

    True under both ``unix-port`` (subprocess backend) and
    ``device-unit`` (device transport backend).  Plain ``--target
    device`` leaves the unit suite in the ordinary CPython lane that
    bare ``pytest`` already covers.
    """
    return _target_is_unix_port(config) or _target_is_device_unit(config)
