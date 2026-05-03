"""Deployer — orchestrate file staging + entrypoint execution on a Device.

The :class:`Deployer` owns the end-to-end "push code onto a board and
run it" flow.  It consumes a :class:`~chumicro_deploy.sources.FileSource`,
constructs a transport via :class:`~chumicro_deploy.device.Device`,
stages every file the source returns, executes the entrypoint, and
returns a :class:`~chumicro_deploy.result.DeployResult`.

The transport-level primitive this builds on is
:meth:`~chumicro_deploy.protocol.TransportProtocol.deploy_files`.
Test orchestrators like ``scripts/device_testing.py`` stick with the
richer ``stage()`` / ``execute()`` flow because they need per-file
iteration and per-group resets.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from .host_platform import check_rsync_available, check_supported_platform
from .protocol import DeployMode, Runtime
from .result import DeployResult

if TYPE_CHECKING:  # pragma: no cover — type-only
    from .device import Device
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

    def deploy_diff(
        self,
        source: FileSource,
        *,
        wipe: bool = False,
        on_progress: Callable[[float, str], None] | None = None,
        on_file_staged: Callable[[str], None] | None = None,
        on_file_deleted: Callable[[str], None] | None = None,
        on_execute_line: Callable[[str], None] | None = None,
    ) -> DeployResult:
        """Diff-deploy *source* — delete stale in-scope files, then deploy.

        Replaces the multi-project-staging flow retired in workspace-
        ecosystem Slice 7.  Per the design in ``plans/next-up.md``
        ("Replace multi-project staging with scoped diff-deploy"):

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
            on_progress: Optional ``(fraction, message)`` callback.
                Stages: ``connecting``, ``listing in-scope`` /
                ``wiping``, ``cleaning stale``, ``staging``,
                ``executing``, ``done``.
            on_file_staged: Forwarded to ``deploy_files``.
            on_file_deleted: Per-file callback invoked with each
                stale on-device path before deletion.  Lets the CLI
                surface "removed: /lib/old.py" lines for transparency.
            on_execute_line: Forwarded to ``deploy_files``.

        Returns:
            :class:`DeployResult` populated as in :meth:`deploy`.  The
            ``staged_files`` field carries the new payload's keys
            (the deletion list is observable via *on_file_deleted*
            during the call but not retained on the result).
        """

        def _report(fraction: float, message: str) -> None:
            if on_progress is not None:
                on_progress(fraction, message)

        if (
            self._device.transport == Runtime.CIRCUITPYTHON
            and self._device.deploy_mode == DeployMode.FLASH
        ):
            check_rsync_available()

        transport = self._device.create_transport()
        _report(0.0, "connecting")
        transport.connect()
        try:
            files = source.files()
            entrypoint = source.entrypoint()
            if wipe:
                _report(0.1, "wiping filesystem")
                transport.wipe_filesystem()
            else:
                _report(0.1, "listing in-scope")
                on_device = set(transport.list_files_in_scope())
                stale = sorted(on_device - set(files))
                if stale:
                    _report(0.2, f"cleaning stale ({len(stale)})")
                    if on_file_deleted is not None:
                        for path in stale:
                            on_file_deleted(path)
                    transport.delete_files(stale)
            _report(0.3, "staging")
            output = transport.deploy_files(
                files,
                entrypoint,
                on_file_staged=on_file_staged,
                on_execute_line=on_execute_line,
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
        on_progress: Callable[[float, str], None] | None = None,
        on_file_staged: Callable[[str], None] | None = None,
        on_execute_line: Callable[[str], None] | None = None,
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
            on_progress: Optional callback ``(fraction, message)``
                invoked at coarse milestones: 0.0 "connecting", 0.1
                "collecting files", 0.2 "staging", 0.9 "executing",
                1.0 "done".  Fractions are nominal — ``deploy_files``
                does not report incremental progress today.
            on_file_staged: Forwarded to
                :meth:`TransportProtocol.deploy_files`.
            on_execute_line: Forwarded to
                :meth:`TransportProtocol.deploy_files`.

        Returns:
            :class:`DeployResult` with ``success``, ``staged_files``,
            ``execute_output``, and ``traceback`` populated.  ``success``
            is ``True`` when the output contains no detectable traceback.
        """

        def _report(fraction: float, message: str) -> None:
            if on_progress is not None:
                on_progress(fraction, message)

        if (
            self._device.transport == Runtime.CIRCUITPYTHON
            and self._device.deploy_mode == DeployMode.FLASH
        ):
            check_rsync_available()

        transport = self._device.create_transport()
        _report(0.0, "connecting")
        transport.connect()
        try:
            _report(0.1, "collecting files")
            files = source.files()
            entrypoint = source.entrypoint()
            _report(0.2, "staging")
            output = transport.deploy_files(
                files,
                entrypoint,
                on_file_staged=on_file_staged,
                on_execute_line=on_execute_line,
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
