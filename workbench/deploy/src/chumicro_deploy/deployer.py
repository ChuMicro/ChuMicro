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

from .result import DeployResult

if TYPE_CHECKING:  # pragma: no cover — type-only
    from .device import Device

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
        self._device = device

    @property
    def device(self) -> Device:
        """The target :class:`Device` this Deployer was constructed with."""
        return self._device

    def deploy(
        self,
        source,  # noqa: ANN001 — FileSource is structural; see sources.py
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
