"""Conftest-side hook for staging ``/runtime_config.msgpack`` onto the device.

A library's ``functional_tests/conftest.py`` calls
:func:`set_runtime_config` from its ``pytest_configure`` hook to hand
the plugin a section-namespaced dict (typically the result of
``chumicro_workspace.compose_runtime_config()`` plus any dynamic
overrides like a randomised mosquitto-broker port).  The plugin
msgpack-encodes the dict once and stages it at
``/runtime_config.msgpack`` via ``transport.stage(extra_files=...)``
on every test invocation, so on-device test code can read it via the
same ``chumicro_config.load_runtime_config()`` API user code uses.

Design notes:

* Storage is :attr:`pytest.Config.stash` — the canonical pytest
  plugin location.  Stash is mutable, so a session-scoped fixture
  can overwrite the registered dict after ``pytest_configure`` if a
  future consumer needs late-binding.  No current consumer does;
  every dynamic value is resolved synchronously inside ``pytest_configure``.
* Passing ``None`` (or omitting the call entirely) suppresses staging.
  The on-device test then sees ``OSError`` from
  ``load_runtime_config()`` and skips silently — the same path that
  fires on a fresh clone with no credentials.
* The plugin re-uses the cached payload across every staged batch in
  a session, so the encoding cost is one ``msgpack.packb`` per pytest
  invocation, not per test.

"""

from __future__ import annotations

import pytest

_RUNTIME_CONFIG_KEY: pytest.StashKey[dict | None] = pytest.StashKey()


def set_runtime_config(
    config: pytest.Config, payload: dict | None,
) -> None:
    """Register the runtime-config dict pytest-device will stage on the device.

    Call from a conftest's ``pytest_configure(config)`` hook (or any
    later hook / fixture with access to the pytest ``Config``).  The
    plugin reads the latest stashed value lazily at stage time —
    overwriting it from a session-scoped autouse fixture is supported
    when late-binding is required.

    Args:
        config: The pytest ``Config`` from ``pytest_configure``.
        payload: The section-namespaced dict to msgpack-encode and
            stage at ``/runtime_config.msgpack``.  ``None`` suppresses
            staging — useful when credentials aren't configured and
            the on-device test should hit its silent-skip path.

    Notes:
        RAM-mode runs cannot stage extra files (no writable
        device-side filesystem).  When a payload is registered AND
        the resolved deploy mode is RAM, ``transport.stage()`` raises
        :class:`chumicro_deploy.UnsupportedExtraFilesError`; switch
        the device's ``deploy_mode`` to ``"flash"`` (or set
        ``--chumicro-deploy-mode=flash``) to fix.
    """
    config.stash[_RUNTIME_CONFIG_KEY] = payload


def get_runtime_config(config: pytest.Config) -> dict | None:
    """Return the most-recently-registered payload, or ``None``."""
    return config.stash.get(_RUNTIME_CONFIG_KEY, None)
