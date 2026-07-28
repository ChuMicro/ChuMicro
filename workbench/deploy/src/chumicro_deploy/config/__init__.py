"""Opt-in configuration loaders for :class:`~chumicro_deploy.Device`.

``chumicro-deploy`` ships one built-in loader (registered as
``"default"``) that reads the ``devices.yml`` schema defined in
:mod:`chumicro_deploy.config.default`.  Third parties with a
different config format register a loader by declaring a Python
entry point in the ``chumicro_deploy.config_loaders`` group.  A
template repo's ``pyproject.toml`` looks like:

.. code-block:: toml

    [project.entry-points."chumicro_deploy.config_loaders"]
    myformat = "my_pkg.loader:load"

Where ``my_pkg.loader.load(path, *, device_id=None)`` returns a
:class:`Device`.

:func:`discover_config_loaders` collects the built-in ``default``
loader plus every registered third-party loader into a single
``{name: callable}`` mapping that downstream code can dispatch from.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - type-only
    from ..device import Device

#: Entry-point group name third parties declare to register a loader.
CONFIG_LOADERS_ENTRY_POINT_GROUP = "chumicro_deploy.config_loaders"

#: Registered name of the built-in loader.
BUILTIN_LOADER_NAME = "default"

#: Type of a config-loader callable.  Loaders take a path (or any
#: string the loader knows how to open) and an optional ``device_id``
#: string, and return a constructed :class:`Device`.
ConfigLoader = Callable[..., "Device"]


def _default_loader(
    path: Path | str,
    *,
    device_id: str | None = None,
    runtime: str | None = None,
) -> Device:
    """Adapter wrapping the built-in ``devices.yml`` loader.

    Forwards both ``device_id`` and ``runtime`` to
    :func:`chumicro_deploy.config.default.load_devices_yml`.
    """
    # Late import so importing :mod:`chumicro_deploy.config` alone
    # does not pull in PyYAML.
    from .default import load_devices_yml

    return load_devices_yml(path, device_id=device_id, runtime=runtime)


def discover_config_loaders() -> dict[str, ConfigLoader]:
    """Return the registered config-loader callables keyed by name.

    The ``default`` entry is always present (built-in).  Third-party
    entries come from Python entry points in the
    ``chumicro_deploy.config_loaders`` group.  Any name collision
    with ``default`` is rejected by the registry so built-in
    behavior is not silently shadowed.

    Returns:
        ``{name: loader}`` mapping where ``loader(path, *, device_id=None)``
        returns a :class:`Device`.
    """
    from importlib.metadata import entry_points

    loaders: dict[str, ConfigLoader] = {BUILTIN_LOADER_NAME: _default_loader}
    group_entries = entry_points(group=CONFIG_LOADERS_ENTRY_POINT_GROUP)
    for entry_point in group_entries:
        if entry_point.name == BUILTIN_LOADER_NAME:
            raise ValueError(
                f"Third-party package registered a "
                f"{BUILTIN_LOADER_NAME!r} config_loaders entry point "
                f"but that name is reserved for the built-in "
                f"devices.yml loader.  Rename the entry point in "
                f"the offending package's pyproject.toml."
            )
        loaders[entry_point.name] = entry_point.load()
    return loaders
