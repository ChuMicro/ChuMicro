"""Deployer — orchestrate file staging + entrypoint execution on a Device.

The :class:`Deployer` owns the end-to-end "push code onto a board and
run it" flow.  It consumes a :class:`~chumicro_deploy.sources.FileSource`,
constructs a transport via :class:`~chumicro_deploy.device.Device`,
stages every file the source returns, executes the entrypoint, and
returns a :class:`~chumicro_deploy.result.DeployResult`.

The transport-level primitive this builds on is
:meth:`~chumicro_deploy.protocol.TransportProtocol.deploy_files`.
Test orchestrators that need per-file iteration and per-group resets
stick with the richer ``stage()`` / ``execute()`` flow.

Both :meth:`Deployer.deploy` and :meth:`Deployer.deploy_diff` run a
pre-flight pass before transport setup: when the device's
``deploy_mode == "ram"`` and the source exposes ``host_paths()``
referencing any library with ``[tool.chumicro] requires_flash = true``,
the deploy auto-switches to flash mode for this run only and emits
a human-readable explanation through the optional
``on_preflight_message`` callback (or stderr by default).  The
explicit ``force_deploy_mode`` parameter bypasses pre-flight entirely.
"""

from __future__ import annotations

import dataclasses
import re
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING

from .host_platform import check_rsync_available, check_supported_platform
from .preflight import find_libraries_requiring_flash
from .protocol import DeployMode, Runtime
from .result import DeployResult

if TYPE_CHECKING:  # pragma: no cover — type-only
    from .device import Device
    from .protocol import TransportProtocol
    from .sources import FileSource

#: Matches MicroPython / CircuitPython traceback output.  Both runtimes
#: prefix tracebacks with ``Traceback (most recent call last):``.  The
#: pattern consumes from the header line through the end of the block,
#: stopping at the start of the next traceback header or the end of the
#: output.  Using a trailing-boundary lookahead rather than hand-rolled
#: line classification keeps the match self-contained and re-entrant.
_TRACEBACK_RE = re.compile(
    r"Traceback \(most recent call last\):.*?"
    r"(?=\nTraceback \(most recent call last\):|\Z)",
    re.DOTALL,
)


def _extract_traceback(output: str) -> str | None:
    """Return the last traceback block in *output* or ``None``."""
    matches = _TRACEBACK_RE.findall(output)
    return matches[-1].rstrip() if matches else None


def _deploy_files_kwargs(
    device: Device,
    entrypoint: str,
    *,
    tail_seconds: float | None = None,
) -> dict[str, object]:
    """Compute transport-specific kwargs for :meth:`TransportProtocol.deploy_files`.

    MicroPython flash deploys with entrypoint ``/main.py`` opt into the
    soft-reboot follow mode so ``while True`` app code captures partial
    output instead of timing out waiting for the raw-REPL EOF marker
    that an infinite loop never emits.  Other paths (CP, MP RAM, MP
    flash with non-``/main.py`` entrypoints) keep transport defaults —
    CP doesn't accept ``follow``, and MP RAM / test-harness deploys
    want ``follow="exec"`` because their entrypoints return cleanly
    and the EOF marker fires.

    *tail_seconds* is CP-only — it tunes how long
    :meth:`CircuitpythonTransport._read_code_py_output` waits for
    boot-time prints before exiting.  MP transports ignore it
    (mpremote follow mode owns its own timing).
    """
    kwargs: dict[str, object] = {}
    if (
        device.transport == Runtime.MICROPYTHON
        and device.deploy_mode == DeployMode.FLASH
        and entrypoint.lstrip("/") == "main.py"
    ):
        kwargs["follow"] = "soft_reboot"
    if tail_seconds is not None and device.transport == Runtime.CIRCUITPYTHON:
        kwargs["tail_seconds"] = tail_seconds
    return kwargs


class Deployer:
    """End-to-end deploy orchestrator.

    Args:
        device: Target board configuration.  :attr:`Device.create_transport`
            is called once per :meth:`deploy` invocation.
    """

    def __init__(self, device: Device) -> None:
        check_supported_platform()
        self._device = device

    @property
    def device(self) -> Device:
        """The target :class:`Device` this Deployer was constructed with."""
        return self._device

    def _effective_device_for_source(
        self,
        source: FileSource,
        *,
        force_deploy_mode: str | None,
        on_preflight_message: Callable[[str], None] | None,
    ) -> Device:
        """Return the effective :class:`Device` for deploying *source*.

        The configured device is the starting point, but the deploy
        *mode* is a policy decision that depends on the source — hence
        the name takes ``_for_source``.  Two policies can force a
        RAM-configured device to flash: a non-``.py`` data file in the
        staged set, or a library in the graph declaring
        ``[tool.chumicro] requires_flash = true``.

        Returns a :class:`Device` whose ``deploy_mode`` is the effective
        mode for this deploy.  The original ``self._device`` is never
        mutated — when an override is needed, ``dataclasses.replace``
        produces a fresh frozen copy.

        Resolution order:

        1. *force_deploy_mode* set: override to that value, no further
           pre-flight.  This is the explicit "I know what I'm doing"
           escape hatch.
        2. ``self._device.deploy_mode != "ram"``: the device already
           wants flash (or some future mode); nothing to switch.
        3. Staged set contains any non-``.py`` data file: switch the
           *whole* deploy to flash.  RAM-mode CircuitPython is a
           raw-REPL ``exec()`` with no device filesystem — non-``.py``
           files are silently dropped, so the asset would simply be
           missing on-device.  All-or-nothing (no half-RAM/half-flash
           dance); emit an explanation.
        4. Source doesn't expose ``host_paths()``: we have no graph to
           inspect — proceed in RAM mode silently
           (:class:`~chumicro_deploy.sources.FileMapSource` is the
           common case here).
        5. No library in the graph carries ``[tool.chumicro]
           requires_flash = true``: proceed in RAM mode silently.
        6. At least one library is flagged: switch to flash mode and
           emit a human-readable explanation through
           *on_preflight_message* (or stderr when ``None``).
        """

        def _emit(message: str) -> None:
            if on_preflight_message is not None:
                on_preflight_message(message)
            else:
                print(message, file=sys.stderr)

        if force_deploy_mode is not None:
            if force_deploy_mode == self._device.deploy_mode:
                return self._device
            return dataclasses.replace(self._device, deploy_mode=force_deploy_mode)

        if self._device.deploy_mode != DeployMode.RAM:
            return self._device

        data_files = sorted(
            name for name in source.files() if not name.endswith(".py")
        )
        if data_files:
            _emit(
                f"chumicro-deploy: switching to flash mode — staged set "
                f"includes non-.py data file(s) ({', '.join(data_files)}) "
                f"that RAM-mode deploy cannot carry (raw-REPL exec has no "
                f"device filesystem; the file(s) would be missing). "
                f"Pass force_deploy_mode='ram' to bypass.",
            )
            return dataclasses.replace(
                self._device, deploy_mode=DeployMode.FLASH,
            )

        host_paths_method = getattr(source, "host_paths", None)
        if host_paths_method is None:
            return self._device

        flagged = find_libraries_requiring_flash(host_paths_method())
        if not flagged:
            return self._device

        _emit(
            f"chumicro-deploy: switching to flash mode — "
            f"{', '.join(flagged)} declare `[tool.chumicro] "
            f"requires_flash = true` (heavy parsers / state machines / "
            f"recv buffers often OOM in RAM mode on smaller boards). "
            f"Pass force_deploy_mode='ram' to bypass.",
        )
        return dataclasses.replace(self._device, deploy_mode=DeployMode.FLASH)

    def _run_deploy(
        self,
        source: FileSource,
        *,
        force_deploy_mode: str | None,
        on_progress: Callable[[float, str], None] | None,
        on_file_staged: Callable[[str], None] | None,
        on_execute_line: Callable[[str], None] | None,
        on_preflight_message: Callable[[str], None] | None,
        tail_seconds: float | None,
        pre_stage_hook: Callable[
            [TransportProtocol, dict[str, bytes], Callable[[float, str], None]],
            None,
        ] | None,
        transport_kwargs: dict[str, object],
    ) -> DeployResult:
        """Run the shared connect → (pre-stage) → deploy_files → disconnect flow.

        :meth:`deploy` and :meth:`deploy_diff` share every step except
        the pre-stage phase: a plain deploy has no extra work
        (``pre_stage_hook=None`` — _run_deploy emits the 0.1 /
        0.2 milestones inline), while deploy_diff lists in-scope files
        and deletes the stale set (or wipes the filesystem outright)
        via its hook.  When supplied, *pre_stage_hook* receives the
        live transport plus the new payload's file map and the same
        progress reporter the outer flow uses; it owns its own milestones.

        *transport_kwargs* are passed straight through to
        ``transport.deploy_files`` after merging with the runtime-
        appropriate ``_deploy_files_kwargs`` (follow / tail_seconds).
        Callers that don't pass them get the transport defaults.
        """

        def _report(fraction: float, message: str) -> None:
            if on_progress is not None:
                on_progress(fraction, message)

        effective_device = self._effective_device_for_source(
            source,
            force_deploy_mode=force_deploy_mode,
            on_preflight_message=on_preflight_message,
        )

        if (
            effective_device.transport == Runtime.CIRCUITPYTHON
            and effective_device.deploy_mode == DeployMode.FLASH
        ):
            check_rsync_available()

        transport = effective_device.create_transport()
        _report(0.0, "connecting")
        transport.connect()
        try:
            files = source.files()
            entrypoint = source.entrypoint()
            if pre_stage_hook is None:
                _report(0.1, "collecting files")
                _report(0.2, "staging")
            else:
                pre_stage_hook(transport, files, _report)
            kwargs = _deploy_files_kwargs(
                effective_device, entrypoint, tail_seconds=tail_seconds,
            )
            kwargs.update(transport_kwargs)
            output = transport.deploy_files(
                files,
                entrypoint,
                on_file_staged=on_file_staged,
                on_execute_line=on_execute_line,
                **kwargs,
            )
            _report(0.9, "executing")
        finally:
            transport.disconnect()

        traceback_text = _extract_traceback(output)
        _report(1.0, "done")
        return DeployResult(
            success=traceback_text is None,
            staged_files=sorted(files.keys()),
            execute_output=output,
            traceback=traceback_text,
        )

    def deploy(
        self,
        source: FileSource,
        *,
        force_deploy_mode: str | None = None,
        on_progress: Callable[[float, str], None] | None = None,
        on_file_staged: Callable[[str], None] | None = None,
        on_execute_line: Callable[[str], None] | None = None,
        on_preflight_message: Callable[[str], None] | None = None,
        tail_seconds: float | None = None,
        clean: bool = False,
    ) -> DeployResult:
        """Deploy *source* to the configured device and run its entrypoint.

        Flow: ``create_transport`` -> ``connect`` -> ``deploy_files``
        -> ``disconnect``.  The transport-level ``deploy_files`` is
        responsible for the actual file-write and execute dance; this
        method layers progress callbacks and result packaging on top.

        Args:
            source: Any object satisfying
                :class:`~chumicro_deploy.sources.FileSource` —
                ``files()`` returns path -> bytes, ``entrypoint()``
                returns the boot file's on-device path.
            force_deploy_mode: Override the pre-flight requires_flash
                policy.  ``None`` (default) runs the pre-flight check
                that auto-promotes RAM → flash when a flagged library
                is in the graph; pass ``"ram"`` to keep RAM mode even
                when a library is flagged, or ``"flash"`` to force
                flash regardless.
            on_progress: Optional callback ``(fraction, message)``
                invoked at coarse milestones: 0.0 "connecting", 0.1
                "collecting files", 0.2 "staging", 0.9 "executing",
                1.0 "done".  Fractions are nominal — ``deploy_files``
                does not report incremental progress today.
            on_file_staged: Forwarded to
                :meth:`TransportProtocol.deploy_files`.
            on_execute_line: Forwarded to
                :meth:`TransportProtocol.deploy_files`.
            on_preflight_message: Optional callback for the
                "switching to flash mode" message the requires_flash
                pre-flight emits.  Defaults to ``sys.stderr``.
            tail_seconds: CP-only override for how long the transport
                captures serial output after the entrypoint's
                soft-reboot.  ``None`` keeps the transport's built-in
                default; ignored on MP transports.
            clean: Forwarded to :meth:`TransportProtocol.deploy_files`.
                In CP flash mode triggers ``rsync --delete`` (with
                ``settings.toml`` / ``boot.py`` / ``boot_out.txt``
                preserved); in MP copy mode triggers a
                ``mpremote fs rm -r :/lib`` before the new push.
                No-op for RAM / mount modes.

        Returns:
            :class:`DeployResult` with ``success``, ``staged_files``,
            ``execute_output``, and ``traceback`` populated.  ``success``
            is ``True`` when the output contains no detectable traceback.
        """
        return self._run_deploy(
            source,
            force_deploy_mode=force_deploy_mode,
            on_progress=on_progress,
            on_file_staged=on_file_staged,
            on_execute_line=on_execute_line,
            on_preflight_message=on_preflight_message,
            tail_seconds=tail_seconds,
            pre_stage_hook=None,
            transport_kwargs={"clean": clean},
        )

    def deploy_diff(
        self,
        source: FileSource,
        *,
        wipe: bool = False,
        force_deploy_mode: str | None = None,
        on_progress: Callable[[float, str], None] | None = None,
        on_file_staged: Callable[[str], None] | None = None,
        on_file_deleted: Callable[[str], None] | None = None,
        on_execute_line: Callable[[str], None] | None = None,
        on_preflight_message: Callable[[str], None] | None = None,
        tail_seconds: float | None = None,
    ) -> DeployResult:
        """Diff-deploy *source* — delete stale in-scope files, then deploy.

        1. Connect.
        2. Ask the transport for every in-scope file currently on the
           device (``list_files_in_scope``).
        3. Compute the stale set — paths on the device that aren't in
           the new payload.
        4. Delete the stale set (``delete_files``).
        5. Hand off to the normal :meth:`deploy_files` for the actual
           write + execute.

        Out-of-scope files (user-uploaded images, hand-edited
        ``settings.toml``, etc.) are never touched — see
        :func:`chumicro_deploy.protocol.is_in_deploy_scope` for the rule.

        Mode-aware: in RAM-mode deploys (CP RAM, MP mount) the
        transport's ``list_files_in_scope`` returns an empty list and
        the diff routine collapses to a plain :meth:`deploy_files`
        call — RAM mode never wrote to flash so there's nothing
        persistent to diff against.

        Args:
            source: :class:`FileSource` to deploy.
            wipe: When ``True``, call ``transport.wipe_filesystem()``
                before staging — destructive clean-slate path used by
                ``chumicro-workspace deploy --wipe``.  Skips the diff
                cleanup entirely (nothing left to diff against after a
                wipe).  RAM-mode transports treat the wipe as a no-op
                so callers don't need to gate on mode.
            force_deploy_mode: Override the pre-flight requires_flash
                policy.  Same semantics as :meth:`deploy`'s argument.
            on_progress: Optional ``(fraction, message)`` callback.
                Stages: ``connecting``, ``listing in-scope`` /
                ``wiping``, ``cleaning stale``, ``staging``,
                ``executing``, ``done``.
            on_file_staged: Forwarded to ``deploy_files``.
            on_file_deleted: Per-file callback invoked with each
                stale on-device path before deletion.  Lets the CLI
                surface "removed: /lib/old.py" lines for transparency.
            on_execute_line: Forwarded to ``deploy_files``.
            on_preflight_message: Forwarded to the same pre-flight
                message sink as :meth:`deploy`.  Defaults to stderr.
            tail_seconds: CP-only soft-reboot capture-window override.
                Same semantics as :meth:`deploy`'s argument.

        Returns:
            :class:`DeployResult` populated as in :meth:`deploy`.  The
            ``staged_files`` field carries the new payload's keys
            (the deletion list is observable via *on_file_deleted*
            during the call but not retained on the result).
        """

        def diff_pre_stage(
            transport: TransportProtocol,
            files: dict[str, bytes],
            report: Callable[[float, str], None],
        ) -> None:
            if wipe:
                report(0.1, "wiping filesystem")
                transport.wipe_filesystem()
            else:
                report(0.1, "listing in-scope")
                on_device = set(transport.list_files_in_scope())
                stale = sorted(on_device - set(files))
                if stale:
                    report(0.2, f"cleaning stale ({len(stale)})")
                    if on_file_deleted is not None:
                        for path in stale:
                            on_file_deleted(path)
                    transport.delete_files(stale)
            report(0.3, "staging")

        return self._run_deploy(
            source,
            force_deploy_mode=force_deploy_mode,
            on_progress=on_progress,
            on_file_staged=on_file_staged,
            on_execute_line=on_execute_line,
            on_preflight_message=on_preflight_message,
            tail_seconds=tail_seconds,
            pre_stage_hook=diff_pre_stage,
            transport_kwargs={},
        )
