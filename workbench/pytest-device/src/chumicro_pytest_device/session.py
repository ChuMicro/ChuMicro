"""Session-state accessors shared by plugin / device_backend / collection.

``getattr``-style readers over the dynamic attributes that
:func:`chumicro_pytest_device.plugin.pytest_sessionstart` stashes on
the pytest ``Session`` (transport cache, target list, backend,
PR-summary collector).  Also exports the library- and project-tree
test-file path predicates (``_is_library_functional_test``,
``_is_project_functional_test`` and the project-targeting /
project-name helpers), the ``--target`` flag readers, and the
runtime-config encode-plus-cache helper used at stage time.

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
    """Return the source dir for the on-device test harness.

    The plugin stages a lightweight test harness alongside library
    sources so ``import chumicro_test_harness`` resolves on the device.
    Prefers the mono-repo ``support/test_harness/src`` tree; when that
    directory is absent (a standalone workspace, where the harness is a
    pip-installed dependency), falls back to
    :func:`_installed_harness_source_dir`.
    """
    mono_repo_source = (
        _workspace_root(session) / "support" / "test_harness" / "src"
    )
    if mono_repo_source.is_dir():
        return mono_repo_source
    return _installed_harness_source_dir(session.config)


def _installed_harness_source_dir(config: pytest.Config) -> Path:
    """Return a source dir that stages the pip-installed test harness.

    Locates the installed ``chumicro_test_harness`` package via
    :func:`importlib.util.find_spec` and returns a directory the
    transports can stage.  The transports copy *every* package under
    whatever dir they are handed, so the returned directory must contain
    the harness package and nothing else.

    Two installed layouts resolve differently:

    * Source checkout / editable install: the package sits at
      ``.../src/chumicro_test_harness``, whose parent ``src`` holds only
      the harness package.  Return that ``src`` directory directly.
    * Wheel install: the package sits in ``site-packages`` next to every
      other installed distribution.  Returning ``site-packages`` would
      stage the whole environment, so the package is copied into a
      private per-run staging dir under the pytest cache and that dir is
      returned instead.

    Raises:
        pytest.UsageError: When ``chumicro_test_harness`` isn't
            importable (neither a mono-repo ``support/test_harness/`` tree
            nor a pip install provides it).
    """
    import importlib.util  # noqa: PLC0415
    import shutil  # noqa: PLC0415

    spec = importlib.util.find_spec("chumicro_test_harness")
    if spec is None or spec.origin is None:
        raise pytest.UsageError(
            "functional tests need the on-device test harness; "
            "pip install chumicro-test-harness (or run in a workspace "
            "with support/test_harness/)",
        )
    package_directory = Path(spec.origin).parent
    if package_directory.parent.name == "src":
        return package_directory.parent

    staging_root = Path(config.cache.mkdir("chumicro_device_harness"))
    staged_package = staging_root / "chumicro_test_harness"
    if staged_package.exists():
        shutil.rmtree(staged_package)
    shutil.copytree(
        package_directory,
        staged_package,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    return staging_root


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


def _is_project_functional_test(file_path: Path) -> bool:
    """Return ``True`` for ``projects/<name>/functional_tests/test_*.py`` paths.

    A workspace project's functional tests live under a ``projects``
    directory; this routes them to a board the way library functional
    tests are routed.  Ownership is decided by the *nearest* marker while
    walking up from each ``functional_tests`` component: a checkout under
    a directory literally named ``projects``
    (``~/projects/chumicro/libraries/kvstore/functional_tests/``) hits
    ``libraries`` before ``projects``, so it stays a LIBRARY test.  Only
    when ``projects`` is the nearer marker is the file project-owned.
    Projects may be nested (``projects/garage/heater/functional_tests/``),
    so any number of segments may sit between ``projects`` and
    ``functional_tests``.
    """
    if not (
        file_path.suffix == ".py"
        and file_path.name.startswith("test_")
        and "functional_tests" in file_path.parts
    ):
        return False
    parts = file_path.parts
    for index, component in enumerate(parts):
        if component != "functional_tests":
            continue
        for preceding in reversed(parts[:index]):
            if preceding == "libraries":
                break
            if preceding == "projects":
                return True
    return False


def _project_functional_tests_dir(file_path: Path) -> Path:
    """Return the ``functional_tests`` directory owning a project test file.

    The deepest ``functional_tests`` component that classified as
    project-owned (nearest marker walking up is ``projects``, not
    ``libraries``).  Only meaningful for a *file_path* that
    :func:`_is_project_functional_test` already accepted.
    """
    parts = file_path.parts
    owning_index: int | None = None
    for index, component in enumerate(parts):
        if component != "functional_tests":
            continue
        for preceding in reversed(parts[:index]):
            if preceding == "libraries":
                break
            if preceding == "projects":
                owning_index = index
                break
    assert owning_index is not None, (
        "_project_functional_tests_dir requires a project functional test path"
    )
    return Path(*parts[: owning_index + 1])


def _project_functional_test_targeted(
    config: pytest.Config, file_path: Path,
) -> bool:
    """Return ``True`` when the invocation explicitly targeted this tree.

    Reads ``config.invocation_params.args`` (the literal command line).
    Each entry that isn't an option (doesn't start with ``-``) is treated
    as a path: any ``::nodeid`` suffix is stripped, a relative path is
    resolved against ``config.invocation_params.dir``, and the result is
    compared to the file's owning ``functional_tests`` directory (from
    :func:`_project_functional_tests_dir`).  A match means the directory
    itself or a file inside it was named.

    Targeting an *ancestor* (``projects/example_sensor`` or a bare
    workspace sweep) does not count: project functional tests fire only
    when their tree is named directly, so a sweep leaves them deselected.

    Option values that happen not to start with ``-`` (``ram`` after
    ``--deploy-mode``) resolve to nonexistent paths and simply never
    match, so they need no special handling.
    """
    tests_dir = _project_functional_tests_dir(file_path).resolve()
    invocation_dir = Path(config.invocation_params.dir)
    for argument in config.invocation_params.args:
        if argument.startswith("-"):
            continue
        path_part = argument.split("::", 1)[0]
        candidate = Path(path_part)
        if not candidate.is_absolute():
            candidate = invocation_dir / candidate
        candidate = candidate.resolve()
        if candidate == tests_dir or candidate.is_relative_to(tests_dir):
            return True
    return False


def _project_unit_name(test_file: Path) -> str:
    """Return the slash-form project name for display and config scoping.

    Takes the project directory (``test_file.parent.parent``), finds the
    LAST ``projects`` component in its parts, and joins everything after
    it with ``/`` (``projects/garage/heater/...`` yields ``garage/heater``).
    Falls back to the project directory's own name when nothing follows
    the marker.  A slash-form name keeps batch cache keys unique across
    same-named nested projects and gives runtime-config scoping a stable
    key.
    """
    project_directory = test_file.parent.parent
    parts = project_directory.parts
    last_projects_index: int | None = None
    for index, component in enumerate(parts):
        if component == "projects":
            last_projects_index = index
    if last_projects_index is not None:
        tail = parts[last_projects_index + 1 :]
        if tail:
            return "/".join(tail)
    return project_directory.name


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
