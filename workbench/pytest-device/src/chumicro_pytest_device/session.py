"""Session-state accessors shared by plugin / device_backend / collection.

``getattr``-style readers over the dynamic attributes that
:func:`chumicro_pytest_device.plugin.pytest_sessionstart` stashes on
the pytest ``Session`` (transport cache, target list, backend,
PR-summary collector).  Also exports the test-file path predicates,
the ``--target`` flag readers, and the runtime-config encode-plus-cache
helper used at stage time.

This is a leaf module: it must not import :mod:`plugin` or
:mod:`collection`, so they can both depend on it.
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
    from .pr_summary import DeviceRunResult  # noqa: F401, kept for type hints downstream


#: On-device path for the staged runtime-config payload.  Matches
#: :data:`chumicro_config.runtime.DEFAULT_RUNTIME_CONFIG_PATH`.
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
    config: pytest.Config, scope: str | None = None,
) -> dict[str, bytes] | None:
    """Return the ``extra_files`` dict to pass to ``transport.stage()``.

    Returns ``None`` when the library being staged registered no payload
    (default state for libraries with no runtime-config requirements,
    plus the silent-skip path when credentials aren't configured).
    Returns a one-entry dict mapping :data:`_RUNTIME_CONFIG_DEVICE_PATH`
    to the msgpack-encoded payload otherwise.  *scope* is the library
    name of the batch being staged, so each library stages its own
    registered payload rather than whichever conftest ran last.

    Encoding uses ``use_single_float=True`` so float values round-trip
    through CircuitPython's native ``msgpack`` decoder (CP doesn't
    support float64).  The encoded bytes are cached on the config
    stash keyed by ``id(payload)``: every device sweep stages once
    per file batch, and re-encoding the same dotted-key dict 50+ times
    is wasted work.
    """
    payload = get_runtime_config(config, scope)
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

    ``pytest_sessionstart`` populates the dynamic attribute, and any
    code path that uses the cache runs strictly after that hook.  The cast
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
    branch lives in one place, and the rest of the plugin is shape-agnostic.
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
    # Scan every ``functional_tests`` component, not just the first:
    # a checkout under an ancestor directory named ``functional_tests``
    # would otherwise pin ``.index`` to that ancestor and hide the real
    # ``libraries/<name>/functional_tests`` two levels up.
    parts = file_path.parts
    return any(
        component == "functional_tests"
        and index >= 2
        and parts[index - 2] == "libraries"
        for index, component in enumerate(parts)
    )


def _is_library_unit_test(file_path: Path) -> bool:
    """Return ``True`` for ``libraries/<name>/tests/test_*.py`` paths.

    Path-shape check only.  Lane membership (CPython-only,
    host-only, on-device) is decided downstream by in-file markers
    (``__chumicro_runtimes__``, ``__chumicro_host_only__``), never by
    the filename.
    """
    if not (
        file_path.suffix == ".py"
        and file_path.name.startswith("test_")
        and "tests" in file_path.parts
    ):
        return False
    # Scan every ``tests`` component, not just the first: a checkout
    # under an ancestor directory named ``tests`` would otherwise pin
    # ``.index`` to that ancestor and hide the real
    # ``libraries/<name>/tests`` two levels up.
    parts = file_path.parts
    return any(
        component == "tests"
        and index >= 2
        and parts[index - 2] == "libraries"
        for index, component in enumerate(parts)
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
    stays functional-only, and this is opt-in so existing functional runs
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
