"""Test fakes and builders for the ``chumicro-pytest-device`` plugin.

Host-side helpers for tests that exercise the plugin without spinning
up a real ``pytest.Session`` or building items through pytest's collect
machinery.

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

The transport fake itself lives in :mod:`chumicro_deploy.testing` —
:class:`~chumicro_deploy.testing.FakeTransport` carries the full
``TransportProtocol`` surface plus the per-call ``outputs`` queue and
per-method ``*_raises`` hooks the plugin tests script.

Mirrors the structure of :mod:`chumicro_deploy.testing` and
:mod:`chumicro_workspace.testing`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from chumicro_deploy import DeviceEntry

from . import collection as _collection
from . import device_backend as _device_backend
from . import transport_cache as _transport_cache

if TYPE_CHECKING:
    from .collection import (
        DevicePrepareItem,
        DeviceRunFileItem,
        DeviceTestItem,
    )

__all__ = [
    "FakeConfig",
    "FakeSession",
    "hot_path_device",
    "make_prepare_item",
    "make_run_file_item",
    "make_test_item",
    "prime_transport_cache",
]


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
        cache: _transport_cache._TransportCache,
        *,
        rootpath: Path,
    ) -> None:
        self._device_transport_cache = cache
        self._backend = _device_backend.DeviceBackend()
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
    cache: _transport_cache._TransportCache,
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
    item.library_name = item.library_dir.name
    item.reported_duration = None
    item.reported_test_total_duration = None


def make_prepare_item(
    session: object,
    device: DeviceEntry,
    test_file: Path,
) -> DevicePrepareItem:
    """Build a :class:`DevicePrepareItem` bypassing pytest's collect."""
    item = _collection.DevicePrepareItem.__new__(_collection.DevicePrepareItem)
    _init_runtime_item(item, session, device, test_file)
    return item


def make_run_file_item(
    session: object,
    device: DeviceEntry,
    test_file: Path,
) -> DeviceRunFileItem:
    """Build a :class:`DeviceRunFileItem` bypassing pytest's collect."""
    item = _collection.DeviceRunFileItem.__new__(_collection.DeviceRunFileItem)
    _init_runtime_item(item, session, device, test_file)
    return item


def make_test_item(
    session: object,
    device: DeviceEntry,
    test_file: Path,
    function_name: str,
) -> DeviceTestItem:
    """Build a :class:`DeviceTestItem` bypassing pytest's collect."""
    item = _collection.DeviceTestItem.__new__(_collection.DeviceTestItem)
    _init_runtime_item(item, session, device, test_file)
    item.function_name = function_name
    return item
