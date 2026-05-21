"""Conftest-side hook for staging ``/runtime_config.msgpack`` onto the device.

A library's ``functional_tests/conftest.py`` calls
:func:`set_runtime_config` from its ``pytest_configure`` hook with a
flat dotted-key dict (typically built from
``chumicro_workspace.compose_runtime_config()`` plus any dynamic
overrides like a randomised mosquitto-broker port).  The plugin
msgpack-encodes the dict and stages it at
``/runtime_config.msgpack`` via ``transport.stage(extra_files=...)``,
so on-device test code can read it through the same
``chumicro_config.load_runtime_config()`` API used by user code.

Two ways a test session sees "no config":

* ``payload`` is ``None`` (or :func:`set_runtime_config` is never
  called).  Nothing is staged. On-device tests get ``OSError`` from
  ``load_runtime_config()`` and skip silently, the same path a fresh
  clone with no credentials hits.
* ``required_keys`` is non-empty and one or more keys are missing
  from the payload.  The plugin skips every ``DeviceTestItem`` at
  collection time with an explicit ``"missing required runtime-config
  keys: ..."`` message, which is preferable to the cryptic
  ``MissingConfigKey`` boot crash the silent-skip path produces when
  a test actually needs the value.
"""

from __future__ import annotations

from collections.abc import Iterable

import pytest

_RUNTIME_CONFIG_KEY: pytest.StashKey[dict | None] = pytest.StashKey()
_REQUIRED_KEYS_KEY: pytest.StashKey[tuple[str, ...]] = pytest.StashKey()


def set_runtime_config(
    config: pytest.Config,
    payload: dict | None,
    *,
    required_keys: Iterable[str] = (),
) -> None:
    """Register the runtime-config dict pytest-device will stage on the device.

    Call from a conftest's ``pytest_configure(config)`` hook (or any
    later hook / fixture with access to the pytest ``Config``).  The
    plugin reads the latest stashed value lazily at stage time, so
    overwriting it from a session-scoped autouse fixture is supported
    when late-binding is required.

    Args:
        config: The pytest ``Config`` from ``pytest_configure``.
        payload: The flat dotted-key dict to msgpack-encode and stage
            at ``/runtime_config.msgpack``.  ``None`` suppresses
            staging.  When paired with a non-empty ``required_keys``,
            the plugin skips every device test with a clear
            "missing required runtime-config keys: …" message
            (unconfigured-creds path).
        required_keys: Flat dotted keys this library's functional
            tests need in the staged payload.  When any required key
            is absent (None payload OR a partial dict), every
            :class:`DeviceTestItem` in the session is skipped at
            collection time with an explicit message naming the
            missing keys.  Default ``()`` means no validation,
            existing behavior, on-device test handles its own miss.

    Notes:
        RAM-mode runs cannot stage extra files (no writable
        device-side filesystem).  When a payload is registered AND
        the resolved deploy mode is RAM, ``transport.stage()`` raises
        :class:`chumicro_deploy.UnsupportedExtraFilesError`.  Switch
        the device's ``deploy_mode`` to ``"flash"`` (or set
        ``--deploy-mode=flash``) to fix.
    """
    config.stash[_RUNTIME_CONFIG_KEY] = payload
    config.stash[_REQUIRED_KEYS_KEY] = tuple(required_keys)


def get_runtime_config(config: pytest.Config) -> dict | None:
    """Return the most-recently-registered payload, or ``None``."""
    return config.stash.get(_RUNTIME_CONFIG_KEY, None)


def get_required_keys(config: pytest.Config) -> tuple[str, ...]:
    """Return the required-keys tuple from the latest :func:`set_runtime_config`
    call, or ``()`` when no validation was requested.
    """
    return config.stash.get(_REQUIRED_KEYS_KEY, ())


def missing_required_keys(config: pytest.Config) -> tuple[str, ...]:
    """Return required keys absent from the staged payload.

    The plugin's ``pytest_collection_modifyitems`` hook calls this to
    decide whether to skip every device test in the session.

    Returns:
        Empty tuple when no required keys are registered (no
        validation requested), or when every required key is present
        in the staged payload.  The full required-keys tuple when the
        payload is ``None`` and required keys are non-empty (nothing
        staged, so everything is "missing").  A subset tuple, in
        declaration order, when the payload is a partial dict.
    """
    required = get_required_keys(config)
    if not required:
        return ()
    payload = get_runtime_config(config)
    if payload is None:
        return required
    return tuple(key for key in required if key not in payload)
