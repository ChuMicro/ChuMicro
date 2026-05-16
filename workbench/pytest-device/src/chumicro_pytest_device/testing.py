"""Test fakes and builders for the ``chumicro-pytest-device`` plugin.

Host-side helpers for tests that exercise the plugin without spinning
up a real ``pytest.Session`` or building items through pytest's collect
machinery.

- :class:`HotPathTransport` — focused ``FakeTransport`` covering the
  plugin's hot path (``connect`` / ``stage`` / ``execute`` /
  ``execute_scripts`` / ``recover`` / ``soft_reset`` /
  ``inline_script_budget_bytes`` / ``disconnect``).  Configurable
  per-call ``execute``/``execute_scripts`` outputs and per-method raise
  hooks for failure-path tests.
- :class:`FakeConfig` — minimal ``pytest.Config`` stand-in with
  ``rootpath`` + ``stash`` + ``getoption``.
- :class:`FakeSession` — minimal ``pytest.Session`` stand-in carrying
  a private ``_TransportCache``, a ``DeviceBackend``, and a
  :class:`FakeConfig`.
- :func:`hot_path_device` — :class:`DeviceEntry` builder with a
  reasonable default address per runtime.
- :func:`prime_transport_cache` — install a transport in the
  session-scoped cache without going through
  ``build_transport_for_entry``.
- :func:`make_prepare_item` / :func:`make_run_file_item` /
  :func:`make_test_item` — build :class:`DevicePrepareItem` /
  :class:`DeviceRunFileItem` / :class:`DeviceTestItem` without
  pytest's collect machinery (uses ``__new__`` + attribute assignment
  the way the production ``__init__`` does).

Mirrors the structure of :mod:`chumicro_deploy.testing` and
:mod:`chumicro_workspace.testing`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from chumicro_deploy import DeviceEntry

from . import plugin as _plugin

if TYPE_CHECKING:
    from .plugin import (
        DevicePrepareItem,
        DeviceRunFileItem,
        DeviceTestItem,
    )

__all__ = [
    "FakeConfig",
    "FakeSession",
    "HotPathTransport",
    "hot_path_device",
    "make_prepare_item",
    "make_run_file_item",
    "make_test_item",
    "prime_transport_cache",
]


class HotPathTransport:
    """Focused ``FakeTransport`` for the plugin hot path.

    Supports the deploy modes the plugin cares about (``ram``,
    ``mount``, ``flash``) and the methods the deploy / probe / recover
    flow calls.  Records every call to ``calls`` as
    ``(method_name, args_tuple)``.  Configurable per-method raise
    hooks let failure-path tests script "connect fails" / "execute
    raises" without subclassing.
    """

    def __init__(
        self,
        *,
        mode: str = "ram",
        outputs: list[str] | None = None,
        connect_raises: Exception | None = None,
        execute_raises: Exception | None = None,
        recover_raises: Exception | None = None,
    ) -> None:
        self.mode = mode
        self._outputs = list(outputs or [])
        self._connect_raises = connect_raises
        self._execute_raises = execute_raises
        self._recover_raises = recover_raises
        self.calls: list[tuple[str, tuple]] = []
        self.staged_sources: list[tuple[str, str]] = []

    def connect(self) -> None:
        self.calls.append(("connect", ()))
        if self._connect_raises is not None:
            raise self._connect_raises

    def stage(
        self,
        source_dirs: list[Path],
        test_files: list[Path],
        harness_source: Path,
        *,
        extra_modules: list[Path] | None = None,
        extra_files: dict[str, bytes] | None = None,
        include_test_support: bool = False,
    ) -> None:
        self.calls.append(
            (
                "stage",
                (source_dirs, test_files, harness_source, extra_modules, extra_files),
            ),
        )

    def execute(self, bootstrap_script: str) -> str:
        self.calls.append(("execute", (bootstrap_script,)))
        if self._execute_raises is not None:
            raise self._execute_raises
        return self._outputs.pop(0) if self._outputs else ""

    def execute_scripts(self, bootstrap_scripts: list[str]) -> str:
        self.calls.append(("execute_scripts", (list(bootstrap_scripts),)))
        if self._execute_raises is not None:
            raise self._execute_raises
        return self._outputs.pop(0) if self._outputs else ""

    def inline_script_budget_bytes(self) -> int:
        return 32 * 1024

    def soft_reset(self) -> None:
        self.calls.append(("soft_reset", ()))

    def clear_entrypoints(self) -> None:
        self.calls.append(("clear_entrypoints", ()))

    def recover(self) -> None:
        self.calls.append(("recover", ()))
        if self._recover_raises is not None:
            raise self._recover_raises

    def disconnect(self) -> None:
        self.calls.append(("disconnect", ()))


class FakeConfig:
    """Minimal ``pytest.Config`` stand-in.

    Carries the three surfaces the plugin reads: ``rootpath``,
    ``stash``, and ``getoption``.  ``rootpath`` is always required —
    pinning a default to a hard-coded workspace root silently couples
    tests to live filesystem state.  ``getoption`` returns its
    ``default`` for every name.
    """

    def __init__(self, rootpath: Path) -> None:
        self.rootpath = rootpath
        self.stash: dict = {}

    def getoption(self, name: str, default: object = None) -> object:
        return default


class FakeSession:
    """Minimal ``pytest.Session`` stand-in.

    Carries the three attributes the plugin reads off the session:
    a session-scoped ``_TransportCache``, a ``DeviceBackend``, and a
    :class:`FakeConfig`.  The cache attribute is named with the
    leading-underscore form the production plugin uses
    (``_device_transport_cache``) so tests can pass the session
    straight into production code paths.
    """

    def __init__(
        self,
        cache: _plugin._TransportCache,
        *,
        rootpath: Path,
    ) -> None:
        self._device_transport_cache = cache
        self._backend = _plugin.DeviceBackend()
        self.config = FakeConfig(rootpath=rootpath)


def hot_path_device(runtime: str = "circuitpython") -> DeviceEntry:
    """Build a :class:`DeviceEntry` for hot-path tests.

    Defaults to a deploy-mode of ``"ram"`` (what the plugin reaches for
    when no override is set) and a synthetic ``/dev/ttyUSB-<runtime>``
    address so tests don't depend on real-board enumeration.
    """
    return DeviceEntry(
        identifier=f"{runtime}-1",
        runtime=runtime,
        address=f"/dev/ttyUSB-{runtime}",
        deploy_mode="ram",
    )


def prime_transport_cache(
    cache: _plugin._TransportCache,
    device: DeviceEntry,
    transport: object,
) -> None:
    """Install *transport* in *cache* without ``build_transport_for_entry``.

    Lets tests script the hot path with a pre-built fake transport
    instead of monkeypatching the build path.
    """
    cache._transports[device.identifier] = transport


def _init_runtime_item(
    item: object,
    session: object,
    device: DeviceEntry,
    test_file: Path,
) -> None:
    """Set the attributes :class:`DeviceRuntimeItem.__init__` sets.

    The production ``__init__`` runs ``pytest.Item.__init__``, which
    needs a parent — brittle to wire up in unit tests.  This sets the
    attributes the rest of the codepath reads directly.
    """
    item.session = session
    item.test_file = test_file
    item.target_device = device
    item.library_dir = test_file.parent.parent
    item._library_name = item.library_dir.name
    item._reported_duration = None
    item._reported_test_total_duration = None


def make_prepare_item(
    session: object,
    device: DeviceEntry,
    test_file: Path,
) -> DevicePrepareItem:
    """Build a :class:`DevicePrepareItem` bypassing pytest's collect."""
    item = _plugin.DevicePrepareItem.__new__(_plugin.DevicePrepareItem)
    _init_runtime_item(item, session, device, test_file)
    return item


def make_run_file_item(
    session: object,
    device: DeviceEntry,
    test_file: Path,
) -> DeviceRunFileItem:
    """Build a :class:`DeviceRunFileItem` bypassing pytest's collect."""
    item = _plugin.DeviceRunFileItem.__new__(_plugin.DeviceRunFileItem)
    _init_runtime_item(item, session, device, test_file)
    return item


def make_test_item(
    session: object,
    device: DeviceEntry,
    test_file: Path,
    function_name: str,
) -> DeviceTestItem:
    """Build a :class:`DeviceTestItem` bypassing pytest's collect."""
    item = _plugin.DeviceTestItem.__new__(_plugin.DeviceTestItem)
    _init_runtime_item(item, session, device, test_file)
    item._function_name = function_name
    return item
