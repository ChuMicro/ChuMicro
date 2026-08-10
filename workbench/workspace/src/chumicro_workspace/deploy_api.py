"""Programmatic deploy+marker-orchestration entry point for demos and host tooling.

``deploy_project(project_dir, ...)`` is the one public API for "deploy
a project-shaped directory to a board and orchestrate the bootstrap."
Wraps the same staging mechanism the ``chumicro-workspace deploy`` CLI
uses, plus a test-shaped raw-REPL bootstrap execution with stdout-marker
capture so the caller can ``wait_for(marker_name)`` mid-execute and
orchestrate host-side counterparties (HTTP requests, MQTT publishes,
etc.).

The caller is expected to provide ``project_dir/app.py``; the harness
modules the bootstrap imports are staged automatically so the inline
bootstrap can ``_exec_as_namespace`` the entrypoint.

Usage::

    from chumicro_workspace.deploy_api import deploy_project

    with deploy_project(
        project_dir=Path("demos/mqtt_pub_sub"),
        device_id="pi-pico-w-circuitpython-board",
        deploy_mode="flash",
        extra_runtime_config={
            "mqtt.broker.host": "10.0.0.5",
            "mqtt.broker.port": 1883,
        },
    ) as session:
        session.wait_for("MQTT_CONNECTED", timeout_s=60)
        ...
        session.wait_for_completion(timeout_s=90)
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from types import TracebackType

from chumicro_deploy import (
    DeviceCaps,
    DeviceEntry,
    TransportProtocol,
    find_libraries_requiring_flash,
    load_device_registry,
    resolve_deploy_mode,
)
from msgpack import packb

from .device_orchestration import (
    build_device_bootstrap,
    build_transport_for_entry,
    resolve_effective_deploy_mode,
    resolve_library_source_dirs,
)
from .device_runner import DeviceBootstrapRunner
from .markers import Marker
from .pipeline import compose_runtime_config
from .workspace import runner_invocation


class DeployApiError(RuntimeError):
    """Base for deploy_api configuration / resolution failures.

    Wraps the kind of errors that surface before the bg-thread bootstrap
    runs: no matching device, missing ``app.py``, ``deploy_mode``
    inconsistent with the device entry.  Transport-level failures during
    the run itself surface through ``wait_for_completion`` as their
    native exception types.
    """


class DeviceNotFoundError(DeployApiError):
    """Raised when no registered device matches the filters."""


@dataclass
class DeployedProject:
    """Live deploy session: a board running a bootstrap with markers streaming back.

    Returned by :func:`deploy_project`.  Public attributes are read-only
    (modify-by-replace via a fresh ``deploy_project`` call); public
    methods delegate to the underlying :class:`DeviceBootstrapRunner`.

    Context-manager compatible: ``__exit__`` calls :meth:`shutdown`.
    """

    #: The resolved device registry entry the deploy targets.  Exposed
    #: so callers can read ``device_entry.identifier`` / ``runtime`` /
    #: ``address`` without re-loading the registry.
    device_entry: DeviceEntry
    #: The transport instance owned by this session.  Public for
    #: read-only introspection (``.mode`` is useful for assertions);
    #: ``shutdown()`` owns the close.
    transport: TransportProtocol
    #: The background-thread bootstrap runner.  Public for advanced
    #: callers that want to reach into ``runner.marker_queue``
    #: directly; the public methods on this dataclass cover the
    #: common case.
    runner: DeviceBootstrapRunner

    _shutdown_called: bool = field(default=False, init=False, repr=False)

    def wait_for(self, marker_name: str, *, timeout_s: float, pump=None) -> Marker:
        """Block until *marker_name* arrives on the board's stdout.

        Forwards to :meth:`DeviceBootstrapRunner.wait_for`.  Non-matching
        markers that arrive while the wait is pending are retained (per
        :class:`chumicro_workspace.markers.MarkerQueue`'s contract), so
        waits may run out of print order; a timeout message names what
        did arrive, including marker-shaped lines that failed to parse.

        Args:
            marker_name: The marker name to wait for (uppercase identifier).
            timeout_s: Seconds to wait before raising
                :class:`chumicro_workspace.markers.MarkerTimeoutError`.
            pump: Optional zero-arg callable invoked between marker
                polls, so a driver running a live counterparty (a
                host-side MQTT client, an HTTP poller) keeps it ticking
                through the wait instead of re-implementing the
                poll-and-pump loop.
        """
        return self.runner.wait_for(marker_name, timeout_s=timeout_s, pump=pump)

    def wait_for_completion(self, *, timeout_s: float) -> str:
        """Join the bootstrap thread; return the captured stdout.

        Forwards to :meth:`DeviceBootstrapRunner.wait_for_completion`.
        Re-raises any transport-level exception the bootstrap encountered
        (e.g. ``CircuitpythonTransportError`` if the board crashed mid-
        bootstrap and the raw-REPL framing broke).
        """
        return self.runner.wait_for_completion(timeout_s=timeout_s)

    @property
    def captured_stdout(self) -> str | None:
        """Best-effort snapshot of captured stdout.

        Returns the full captured stdout once the bootstrap finishes;
        :data:`None` while it's still running.  For real-time observation
        during the run, reach into ``runner.marker_queue`` instead, because
        the captured stream is only populated when ``execute()`` returns.
        """
        # pylint: disable=protected-access - runner's _captured_output is
        # public-shaped state without a public getter today; the abstraction
        # is "expose the captured stream while still alive."
        return self.runner._captured_output  # noqa: SLF001

    def shutdown(self, *, timeout_s: float = 5.0) -> None:
        """Close the transport and reap the bg thread.  Idempotent.

        Safe to call from a ``finally`` clause even when the bootstrap
        is still running: the runner's shutdown is best-effort and the
        transport's ``disconnect()`` is tolerant of any state.  When
        the first join times out, ``disconnect()`` fails the bg
        thread's blocked read fast, so the follow-up reap bounds the
        window where a stale thread still holds the dead transport.
        """
        if self._shutdown_called:
            return
        self._shutdown_called = True
        try:
            self.runner.shutdown(timeout_s=timeout_s)
        finally:
            try:
                self.transport.disconnect()
            except Exception:  # noqa: BLE001, S110 - best-effort teardown
                pass
            self.runner.shutdown(timeout_s=1.0)

    def __enter__(self) -> DeployedProject:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.shutdown()


def _select_device(
    workspace_root: Path,
    *,
    device_id: str | None,
    runtime: str | None,
) -> DeviceEntry:
    """Pick a registered device matching the *device_id* / *runtime* filters."""
    entries, _ = load_device_registry(workspace_root=workspace_root)
    if device_id is not None:
        for entry in entries:
            if entry.identifier == device_id:
                if runtime is not None and entry.runtime != runtime:
                    raise DeployApiError(
                        f"device_id={device_id!r} resolves to a "
                        f"{entry.runtime!r} board, but runtime={runtime!r} "
                        f"was also passed.  Drop one to disambiguate.",
                    )
                return entry
        known = [entry.identifier for entry in entries]
        raise DeviceNotFoundError(
            f"no device with id {device_id!r} in devices.yml "
            f"(known: {known!r})",
        )
    effective_runtime = runtime or "circuitpython"
    for entry in entries:
        if entry.runtime == effective_runtime:
            return entry
    raise DeviceNotFoundError(
        f"no {effective_runtime!r} device in devices.yml; register one "
        f"with `{runner_invocation(workspace_root)} add-device`.",
    )


def _build_runtime_config_extra_files(
    workspace_root: Path,
    extra_runtime_config: dict[str, object] | None,
) -> dict[str, bytes] | None:
    """Compose ``secrets.toml`` + *extra_runtime_config* into the msgpack payload.

    Returns the ``{path: bytes}`` mapping ``transport.stage`` accepts as
    ``extra_files=``, or :data:`None` when neither source has content
    worth shipping (no ``secrets.toml`` and no overrides).  Extras are
    applied on top of secrets so a caller can inject a transient broker
    address that takes precedence over any stored default.
    """
    secrets_toml = workspace_root / "secrets.toml"
    has_secrets = secrets_toml.is_file()
    if not has_secrets and not extra_runtime_config:
        return None
    merged: dict
    if has_secrets:
        merged = compose_runtime_config(
            secrets_toml=secrets_toml, project_config=None,
        )
    else:
        merged = {}
    if extra_runtime_config:
        for key, value in extra_runtime_config.items():
            merged[key] = value
    encoded = packb(merged, use_single_float=True)
    return {"/runtime_config.msgpack": encoded}


def _resolve_workspace_root(project_dir: Path) -> Path:
    """Walk parents of *project_dir* until ``secrets.toml`` or ``devices.yml`` is found.

    Most callers pass a project under ``<repo>/demos/<name>/`` or
    ``<repo>/projects/<name>/``; the repo root is what carries
    ``secrets.toml`` + ``devices.yml`` + ``libraries/`` + the harness.
    Fall back to ``project_dir.parents[1]`` (assume two-deep) when
    neither marker is found, because the demos convention is exactly this
    layout.
    """
    for candidate in [project_dir, *project_dir.parents]:
        if (candidate / "devices.yml").is_file():
            return candidate
        if (candidate / "secrets.toml").is_file():
            return candidate
    return project_dir.parents[1] if len(project_dir.parents) >= 2 else project_dir


#: Harness modules a demo deploy leaves off the minimum-tier flash budget.
#: A demo's bootstrap imports only ``chumicro_test_harness.runner`` and
#: ``.discovery`` (whose closure is ``__init__`` + ``assertions`` + ``skip``).
#: The ``network`` real-I/O helpers and ``patching`` fakes exist only to
#: support test files, so a running demo never loads them, and on a 256 KB
#: board their ~15 KB of source (before the device-stage strip) is the
#: difference between a one-request demo fitting and ``No space left``.
_DEMO_UNUSED_HARNESS_MODULES = ("network.py", "patching.py")


def _stage_demo_harness_core(harness_source: Path, mirror_root: Path) -> Path:
    """Mirror the harness package into *mirror_root* minus its test-only modules.

    Copies every harness file except the ones in
    :data:`_DEMO_UNUSED_HARNESS_MODULES` and returns the mirrored ``src``
    directory to hand to ``transport.stage``.  A demo then carries only
    the harness its bootstrap imports, not the network/patching modules
    that exist for test files.
    """
    mirrored_source = mirror_root / "src"
    shutil.copytree(
        harness_source,
        mirrored_source,
        ignore=shutil.ignore_patterns(*_DEMO_UNUSED_HARNESS_MODULES),
    )
    return mirrored_source


def _staged_file_names(source_dirs: list[Path]) -> list[str]:
    """Every file the closure stages, by name.

    ``transport.stage`` copies whole ``src`` trees, so the flash-mode
    data-file check must see them all.  ``__pycache__`` is build cruft
    the staging never carries, so excluding it stops a stray ``.pyc``
    from wrongly forcing flash.
    """
    names: list[str] = []
    for source_dir in source_dirs:
        for path in source_dir.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                names.append(path.name)
    return names


def _resolve_project_deploy_mode(
    device_entry: DeviceEntry,
    deploy_mode: str | None,
    source_dirs: list[Path],
) -> str:
    """Return the deploy mode after applying flash-promotion policy.

    Starts from the configured mode (explicit override, then the device
    entry, then the workspace default) and asks
    :func:`chumicro_deploy.resolve_deploy_mode` to promote RAM to flash
    when the source closure carries a ``requires_flash`` library or a
    non-``.py`` data file RAM mode can't reliably place on the device.
    A promotion message prints to stderr; the deploy always continues.
    Mirrors the gating the CLI ``Deployer`` and the pytest-device plugin
    apply, so a programmatic deploy of a flash-only closure onto a
    RAM-configured board doesn't silently OOM on import.
    """
    configured = resolve_effective_deploy_mode(device_entry, deploy_mode)
    mode, message = resolve_deploy_mode(
        configured,
        staged_files=_staged_file_names(source_dirs),
        device_caps=DeviceCaps(supports_ram_mode=device_entry.supports_ram_mode),
        requires_flash_libs=find_libraries_requiring_flash(source_dirs),
        resolution_unit=None,
        force=None,
    )
    if message is not None:
        print(message, file=sys.stderr)
    return mode


def deploy_project(
    project_dir: Path,
    *,
    device_id: str | None = None,
    runtime: str | None = None,
    deploy_mode: str | None = None,
    extra_runtime_config: dict[str, object] | None = None,
    boot_shim: bool = True,  # noqa: ARG001 - reserved for future use
    import_graph: bool = True,  # noqa: ARG001 - reserved for future use
    workspace_root: Path | None = None,
) -> DeployedProject:
    """Deploy *project_dir*'s ``app.py`` to a registered board, start the bootstrap.

    Returns a live :class:`DeployedProject` whose bg-thread bootstrap is
    already running.  Caller drives via :meth:`DeployedProject.wait_for`
    + :meth:`wait_for_completion`; cleanup happens in
    :meth:`DeployedProject.shutdown` (or context-manager ``__exit__``).

    Args:
        project_dir: Directory containing ``app.py``.  May also contain
            ``project_config.toml`` (reserved for future use; not read yet).
        device_id: Optional device id from ``devices.yml``.
        runtime: Optional ``"circuitpython"`` or ``"micropython"``
            filter.  When *device_id* is also passed, this validates
            the chosen device's runtime matches.
        deploy_mode: Optional ``"flash"`` / ``"ram"`` / ``"mount"``
            override.  :data:`None` defers to devices.yml resolution
            (per-device entry first, then global default).  Demos pin
            ``"flash"`` explicitly so the production-shaped path is
            what runs.
        extra_runtime_config: Flat-key dict merged on top of
            ``secrets.toml`` to form ``/runtime_config.msgpack``.
            Last-write-wins: extras override secrets defaults.
        boot_shim: Reserved.  Always uses the test-shaped raw-REPL
            bootstrap path today; a future signature change may wire
            this kwarg to a different bootstrap shape.
        import_graph: Reserved.  Always walks the entrypoint's import
            graph today via ``resolve_library_source_dirs``.
        workspace_root: Optional explicit workspace root.  Defaults to
            walking *project_dir*'s parents for ``secrets.toml`` /
            ``devices.yml``.

    Returns:
        A live :class:`DeployedProject` session.

    Raises:
        DeviceNotFoundError: No registered device matches the filters.
        DeployApiError: ``project_dir/app.py`` is absent, or *device_id*
            + *runtime* contradict each other.
    """
    if not project_dir.is_dir():
        raise DeployApiError(f"project_dir is not a directory: {project_dir}")
    app_file = project_dir / "app.py"
    if not app_file.is_file():
        raise DeployApiError(
            f"no app.py in {project_dir}; deploy_api expects a "
            f"project-shaped directory with app.py at its root.",
        )

    resolved_workspace_root = workspace_root or _resolve_workspace_root(
        project_dir,
    )
    libraries_root = resolved_workspace_root / "libraries"
    harness_source = (
        resolved_workspace_root / "support" / "test_harness" / "src"
    )

    device_entry = _select_device(
        resolved_workspace_root, device_id=device_id, runtime=runtime,
    )
    # Resolve the source closure before building the transport: the
    # deploy mode depends on what the closure ships (a requires_flash
    # library or a data file promotes RAM to flash), and the transport
    # is built for the resolved mode.
    source_dirs = resolve_library_source_dirs(
        project_dir,
        libraries_root=libraries_root,
        test_files=[app_file],
    )
    resolved_deploy_mode = _resolve_project_deploy_mode(
        device_entry, deploy_mode, source_dirs,
    )
    transport = build_transport_for_entry(
        device_entry, deploy_mode=resolved_deploy_mode,
    )
    transport.connect()

    try:
        extra_files = _build_runtime_config_extra_files(
            resolved_workspace_root, extra_runtime_config,
        )
        # stage() fully consumes the harness dir (reads/copies it) before it
        # returns, so the reduced mirror only has to outlive this call.
        with TemporaryDirectory(prefix="chumicro-demo-harness-") as harness_mirror:
            transport.stage(
                source_dirs,
                [app_file],
                _stage_demo_harness_core(harness_source, Path(harness_mirror)),
                extra_files=extra_files,
                include_test_support=False,
            )
        bootstrap = build_device_bootstrap(
            device_entry, transport, app_file, function_filter=None,
        )
        runner = DeviceBootstrapRunner(transport, bootstrap)
        runner.start()
    except BaseException:
        # Best-effort transport cleanup if any of the staging or
        # bootstrap-build steps blow up before the bg thread starts.
        try:
            transport.disconnect()
        except Exception:  # noqa: BLE001, S110 - best-effort teardown
            pass
        raise

    return DeployedProject(
        device_entry=device_entry,
        transport=transport,
        runner=runner,
    )
