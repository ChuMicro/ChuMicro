"""Deployer: orchestrate file staging + entrypoint execution on a Device.

The :class:`Deployer` owns the end-to-end "push code onto a board and
run it" flow.  It consumes a :class:`~chumicro_deploy.sources.FileSource`,
constructs a transport via :class:`~chumicro_deploy.device.Device`,
stages every file the source returns, executes the entrypoint, and
returns a :class:`~chumicro_deploy.result.DeployResult`.

The transport-level primitive this builds on is
:meth:`~chumicro_deploy.protocol.TransportProtocol.deploy_files`.
Per-file iteration and per-group resets are exposed through the
richer ``stage()`` / ``execute()`` flow instead.

Before each deploy, a pre-flight pass auto-promotes a RAM-mode device
to flash when the source ships a library marked
``[tool.chumicro] requires_flash = true``.  The promotion is announced
through ``on_preflight_message`` (stderr by default).  Pass
``force_deploy_mode`` to bypass pre-flight.
"""

from __future__ import annotations

import dataclasses
import re
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING

from .host_platform import check_rsync_available, check_supported_platform
from .preflight import (
    DeviceCaps,
    find_libraries_requiring_flash,
    resolve_deploy_mode,
)
from .protocol import DeployMode, Runtime
from .result import DeployResult

if TYPE_CHECKING:  # pragma: no cover - type-only
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
    flash with non-``/main.py`` entrypoints) keep transport defaults:
    CP doesn't accept ``follow``, and the other MP shapes want
    ``follow="exec"`` because their entrypoints return cleanly and
    the EOF marker fires.

    *tail_seconds* is CP-only, and it tunes how long the boot-time
    capture window stays open.  MP transports ignore it (mpremote
    follow mode owns its own timing).
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
            is called once per :meth:`deploy_diff` invocation.
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

        The deploy mode depends on what *source* ships: a RAM-mode
        device deploying a library marked ``requires_flash = true`` is
        promoted to flash for this run.  This method gathers the staged
        file set and the ``requires_flash`` closure (when *source*
        exposes ``host_paths()``) and hands the decision to
        :func:`chumicro_deploy.resolve_deploy_mode`.  An app deploy has
        no single owning library, so passes ``resolution_unit=None``
        (no "declare requires_flash" recommendation) and the default
        :class:`DeviceCaps`.

        Returns a :class:`Device` whose ``deploy_mode`` is the
        resolved mode.  ``self._device`` is never mutated, and when the
        mode changes, ``dataclasses.replace`` produces a fresh frozen
        copy.  Any override message is surfaced through
        *on_preflight_message* (or stderr when ``None``).  The deploy
        always continues, never silently skipped.
        """
        host_paths_method = getattr(source, "host_paths", None)
        requires_flash_libs = (
            find_libraries_requiring_flash(host_paths_method())
            if host_paths_method is not None
            else []
        )

        mode, message = resolve_deploy_mode(
            self._device.deploy_mode,
            staged_files=list(source.files()),
            device_caps=DeviceCaps(),
            requires_flash_libs=requires_flash_libs,
            resolution_unit=None,
            force=force_deploy_mode,
        )

        if message is not None:
            if on_preflight_message is not None:
                on_preflight_message(message)
            else:
                print(message, file=sys.stderr)

        if mode == self._device.deploy_mode:
            return self._device
        return dataclasses.replace(self._device, deploy_mode=mode)

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
        """Run the shared connect, then (pre-stage), then deploy_files, then disconnect flow.

        The pre-stage phase is the only branchable step: when
        *pre_stage_hook* is ``None`` the helper emits the 0.1 / 0.2
        milestones inline; otherwise the hook receives the live
        transport plus the new payload's file map and the same
        progress reporter the outer flow uses, and owns its own
        milestones.

        *transport_kwargs* are passed straight through to
        ``transport.deploy_files`` after merging with the runtime-
        appropriate ``_deploy_files_kwargs`` (follow / tail_seconds).
        Empty falls back to transport defaults.
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

    def deploy_diff(
        self,
        source: FileSource,
        *,
        clean: bool = True,
        wipe: bool = False,
        force_deploy_mode: str | None = None,
        on_progress: Callable[[float, str], None] | None = None,
        on_file_staged: Callable[[str], None] | None = None,
        on_file_deleted: Callable[[str], None] | None = None,
        on_execute_line: Callable[[str], None] | None = None,
        on_preflight_message: Callable[[str], None] | None = None,
        tail_seconds: float | None = None,
    ) -> DeployResult:
        """Diff-deploy *source*: delete stale in-scope files, then deploy.

        1. Connect.
        2. Ask the transport for every in-scope file currently on the
           device (``list_files_in_scope``).
        3. Compute the stale set, the paths on the device that aren't in
           the new payload.
        4. Delete the stale set (``delete_files``).
        5. Hand off to the normal :meth:`deploy_files` for the actual
           write + execute.

        Out-of-scope files (user-uploaded images, hand-edited
        ``settings.toml``, etc.) are never touched; see
        :func:`chumicro_deploy.protocol.is_in_deploy_scope` for the rule.

        Mode-aware: in RAM-mode deploys (CP RAM, MP mount) the
        transport's ``list_files_in_scope`` returns an empty list and
        the diff routine collapses to a plain :meth:`deploy_files`
        call, because RAM mode never wrote to flash so there's nothing
        persistent to diff against.

        Args:
            source: :class:`FileSource` to deploy.
            clean: Clean-slate reconcile (the default).  The diff
                scope is the whole device minus the closed keep set
                (:data:`flash_drive.DEVICE_KEEP_SET`) + device-managed
                noise, so a stale board ``settings.toml`` / leftover
                user file is removed and only payload + keep set
                remain.  ``False`` is the additive scope (the
                ``--no-wipe`` opt-out): only the entrypoint/state
                files + ``/lib`` are reconciled, other root files
                preserved.  Distinct from *wipe*: clean-slate keeps
                the keep set; *wipe* erases the whole filesystem
                including it.
            wipe: When ``True``, call ``transport.wipe_filesystem()``
                before staging, a full destructive erase (keep set
                included) for corruption-recovery flows.  Skips the
                diff cleanup entirely (nothing left to diff against
                after a wipe).  RAM-mode transports treat the wipe
                as a no-op, so no need to gate on mode at the call
                site.
            force_deploy_mode: Override the pre-flight requires_flash
                policy.  ``None`` (default) runs the pre-flight check
                that auto-promotes RAM → flash when a flagged library
                is in the graph; ``"ram"`` keeps RAM mode even when a
                library is flagged; ``"flash"`` forces flash.
            on_progress: Optional ``(fraction, message)`` callback.
                Stages: ``connecting``, ``listing in-scope`` /
                ``wiping``, ``cleaning stale``, ``staging``,
                ``executing``, ``done``.
            on_file_staged: Forwarded to ``deploy_files``.
            on_file_deleted: Per-file callback invoked with each
                stale on-device path before deletion.
            on_execute_line: Forwarded to ``deploy_files``.
            on_preflight_message: Optional callback for the
                "switching to flash mode" message the requires_flash
                pre-flight emits.  Defaults to ``sys.stderr``.
            tail_seconds: CP-only override for how long the transport
                captures serial output after the entrypoint's
                soft-reboot.  ``None`` keeps the transport's built-in
                default; ignored on MP transports.

        Returns:
            :class:`DeployResult` with ``success``, ``staged_files``,
            ``execute_output``, and ``traceback`` populated.  The
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
                on_device = set(
                    transport.list_files_in_scope(clean_slate=clean),
                )
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
