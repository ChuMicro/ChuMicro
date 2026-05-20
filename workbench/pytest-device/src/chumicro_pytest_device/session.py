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
from chumicro_deploy import DeviceEntry
from msgpack import packb

from .runtime_config import get_runtime_config
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
