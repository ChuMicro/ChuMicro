"""Opt-in configuration loaders for :class:`~chumicro_deploy.Device`.

chumicro's own devices.yml loader lives at
:func:`chumicro_deploy.config.chumicro.load_devices_yml`.  Third
parties with a custom config format register a loader by declaring
a Python entry point in the ``chumicro_deploy.config_loaders``
group.  A template repo's ``pyproject.toml`` looks like:

.. code-block:: toml

    [project.entry-points."chumicro_deploy.config_loaders"]
    myformat = "my_pkg.loader:load"

Where ``my_pkg.loader.load(path, *, device_id=None)`` returns a
:class:`Device`.

:func:`discover_config_loaders` collects the built-in ``chumicro``
loader plus every registered third-party loader into a single
``{name: callable}`` mapping that the CLI and any
orchestration-layer code can dispatch from.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — type-only
    from ..device import Device

#: Entry-point group name third parties declare to register a loader.
CONFIG_LOADERS_ENTRY_POINT_GROUP = "chumicro_deploy.config_loaders"

#: Type of a config-loader callable.  Loaders take a path (or any
#: string the loader knows how to open) and an optional ``device_id``
#: string, and return a constructed :class:`Device`.
ConfigLoader = Callable[..., "Device"]


def _chumicro_loader(path: Path | str, *, device_id: str | None = None) -> Device:
    """Adapter wrapping chumicro's devices.yml loader."""
    # Late import so importing :mod:`chumicro_deploy.config` alone
    # does not pull in PyYAML.
    from .chumicro import load_devices_yml

    return load_devices_yml(path, device_id=device_id)


def discover_config_loaders() -> dict[str, ConfigLoader]:
    """Return the registered config-loader callables keyed by name.

    The ``chumicro`` entry is always present (built-in).  Third-party
    entries come from Python entry points in the
    ``chumicro_deploy.config_loaders`` group — any name collision
    with ``chumicro`` is rejected by the registry so built-in
    behaviour is not silently shadowed.

    Returns:
        ``{name: loader}`` mapping where ``loader(path, *, device_id=None)``
        returns a :class:`Device`.
    """
    from importlib.metadata import entry_points

    loaders: dict[str, ConfigLoader] = {"chumicro": _chumicro_loader}
    try:
        group_entries = entry_points(group=CONFIG_LOADERS_ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover — Python <3.10 fallback shape
        all_entries = entry_points()
        group_entries = all_entries.get(
            CONFIG_LOADERS_ENTRY_POINT_GROUP, []
        )  # type: ignore[assignment,union-attr]
    for entry_point in group_entries:
        if entry_point.name == "chumicro":
            # Prevent third parties from shadowing the built-in.
            # Surface loudly rather than silently swallow, so the
            # collision is fixable upstream.
            raise ValueError(
                "Third-party package registered a 'chumicro' "
                "config_loaders entry point — that name is reserved "
                "for the built-in devices.yml loader.  Rename the "
                "entry point in the offending package's "
                "pyproject.toml."
            )
        loaders[entry_point.name] = entry_point.load()
    return loaders
