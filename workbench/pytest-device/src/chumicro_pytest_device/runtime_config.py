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
  from the payload.  The plugin skips that library's ``DeviceTestItem``s
  at collection time with an explicit ``"missing required runtime-config
  keys: ..."`` message, which is preferable to the cryptic
  ``MissingConfigKey`` boot crash the silent-skip path produces when
  a test actually needs the value.

Each library registers under its own scope (derived from the calling
conftest's path), so two libraries' ``functional_tests`` conftests in
one session validate and stage independently rather than the last
``pytest_configure`` overwriting the rest.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from pathlib import Path

import pytest

#: Scope for registrations that can't be attributed to one library
#: (a caller outside a ``libraries/<name>/functional_tests`` conftest).
#: Such a registration applies session-wide, the pre-scoping behavior.
_DEFAULT_SCOPE = "__session__"

#: Per-scope payload map: ``{scope: payload}``.  Each library's
#: ``functional_tests/conftest.py`` registers under its own library-name
#: scope, so two libraries in one session can't clobber each other's
#: staged runtime-config or required-keys validation.
_RUNTIME_CONFIG_KEY: pytest.StashKey[dict[str, dict | None]] = pytest.StashKey()
_REQUIRED_KEYS_KEY: pytest.StashKey[dict[str, tuple[str, ...]]] = pytest.StashKey()


def _library_scope_from_path(path: Path) -> str | None:
    """Return the scope key for a functional-test conftest path.

    Recognizes the ``libraries/<name>/functional_tests/...`` layout and
    returns ``<name>``, and the ``projects/<name>/functional_tests/...``
    layout (possibly nested, ``projects/garage/heater/functional_tests/``)
    and returns the slash-form project name (``garage/heater``).  Either
    is the same string a ``DeviceRuntimeItem`` carries as
    ``library_name``, so a conftest's registration and its items resolve
    to one scope key and a project's ``functional_tests/conftest.py``
    scopes its ``set_runtime_config`` to its own project.  Any other path
    returns ``None``.

    The project path-shape walk mirrors
    ``session._is_project_functional_test`` and
    ``session._project_unit_name``, duplicated here (as the library-name
    walk already is) to keep this module a leaf that ``session`` imports,
    never the reverse.
    """
    parts = path.parts
    for index, component in enumerate(parts):
        if (
            component == "functional_tests"
            and index >= 2
            and parts[index - 2] == "libraries"
        ):
            return parts[index - 1]
    return _project_scope_from_path(parts)


def _project_scope_from_path(parts: tuple[str, ...]) -> str | None:
    """Return the slash-form project name for a project functional-test path.

    Ownership is the nearest marker walking up from a ``functional_tests``
    component: ``projects`` (not ``libraries``) makes the tree
    project-owned.  The name is the components between the LAST
    ``projects`` marker and ``functional_tests``, joined with ``/``,
    falling back to the immediate parent's name when nothing sits
    between.  Returns ``None`` for a path no ``functional_tests``
    component classifies as project-owned.
    """
    for index, component in enumerate(parts):
        if component != "functional_tests":
            continue
        preceding = parts[:index]
        owner_is_project = False
        for candidate in reversed(preceding):
            if candidate == "libraries":
                break
            if candidate == "projects":
                owner_is_project = True
                break
        if not owner_is_project:
            continue
        last_projects_index: int | None = None
        for inner_index, inner_component in enumerate(preceding):
            if inner_component == "projects":
                last_projects_index = inner_index
        if last_projects_index is not None:
            tail = preceding[last_projects_index + 1 :]
            if tail:
                return "/".join(tail)
            if preceding:
                return preceding[-1]
    return None


def _caller_library_scope() -> str:
    """Return the library scope of the conftest that called this module.

    Walks the call stack for the first frame whose file is a
    ``libraries/<name>/functional_tests`` conftest and returns ``<name>``.
    Falls back to :data:`_DEFAULT_SCOPE` for any other caller (a unit test
    exercising the API directly), which keeps such registrations
    session-wide.
    """
    frame = inspect.currentframe()
    try:
        while frame is not None:
            scope = _library_scope_from_path(Path(frame.f_code.co_filename))
            if scope is not None:
                return scope
            frame = frame.f_back
    finally:
        del frame
    return _DEFAULT_SCOPE


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
            is absent (None payload OR a partial dict), that library's
            :class:`DeviceTestItem`s are skipped at collection time with
            an explicit message naming the missing keys.  Default ``()``
            means no validation, existing behavior, on-device test
            handles its own miss.

    Notes:
        The payload and required-keys are stored under the calling
        library's scope (derived from the conftest's file path), so a
        second library's ``set_runtime_config`` call in the same session
        can't overwrite this one's.  A caller outside a library's
        ``functional_tests`` conftest registers session-wide.

        RAM-mode runs cannot stage extra files (no writable
        device-side filesystem).  When a payload is registered AND
        the resolved deploy mode is RAM, ``transport.stage()`` raises
        :class:`chumicro_deploy.UnsupportedExtraFilesError`.  Switch
        the device's ``deploy_mode`` to ``"flash"`` (or set
        ``--deploy-mode=flash``) to fix.
    """
    scope = _caller_library_scope()
    payloads = config.stash.get(_RUNTIME_CONFIG_KEY, None)
    if payloads is None:
        payloads = {}
        config.stash[_RUNTIME_CONFIG_KEY] = payloads
    payloads[scope] = payload
    required_map = config.stash.get(_REQUIRED_KEYS_KEY, None)
    if required_map is None:
        required_map = {}
        config.stash[_REQUIRED_KEYS_KEY] = required_map
    required_map[scope] = tuple(required_keys)


def get_runtime_config(
    config: pytest.Config, scope: str | None = None,
) -> dict | None:
    """Return the payload registered for *scope*, or ``None``.

    A ``None`` *scope* reads the session-wide registration.  A named
    scope with no registration of its own falls back to the session-wide
    one, so a library that never registered a payload still sees any
    session-wide default.
    """
    payloads = config.stash.get(_RUNTIME_CONFIG_KEY, {})
    key = scope if scope is not None else _DEFAULT_SCOPE
    if key in payloads:
        return payloads[key]
    return payloads.get(_DEFAULT_SCOPE)


def get_required_keys(
    config: pytest.Config, scope: str | None = None,
) -> tuple[str, ...]:
    """Return the required-keys tuple registered for *scope*, or ``()``.

    Resolution mirrors :func:`get_runtime_config`: a named scope with no
    registration falls back to the session-wide one.
    """
    required_map = config.stash.get(_REQUIRED_KEYS_KEY, {})
    key = scope if scope is not None else _DEFAULT_SCOPE
    if key in required_map:
        return required_map[key]
    return required_map.get(_DEFAULT_SCOPE, ())


def missing_required_keys(
    config: pytest.Config, scope: str | None = None,
) -> tuple[str, ...]:
    """Return *scope*'s required keys absent from its staged payload.

    The plugin's ``pytest_collection_modifyitems`` hook calls this per
    item, passing the item's ``library_name`` as *scope*, to decide
    whether to skip that library's device tests.

    Returns:
        Empty tuple when no required keys are registered for the scope
        (no validation requested), or when every required key is present
        in the scope's staged payload.  The full required-keys tuple when
        the payload is ``None`` and required keys are non-empty (nothing
        staged, so everything is "missing").  A subset tuple, in
        declaration order, when the payload is a partial dict.
    """
    required = get_required_keys(config, scope)
    if not required:
        return ()
    payload = get_runtime_config(config, scope)
    if payload is None:
        return required
    return tuple(key for key in required if key not in payload)
