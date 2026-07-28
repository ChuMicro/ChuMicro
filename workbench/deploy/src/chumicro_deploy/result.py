"""DeployResult and DeployError: outcome types returned by the deployer.

Defined in their own module so callers can annotate against a stable
return type without pulling in the orchestration code.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class DeployError(Exception):
    """A deploy step failed in a way the caller should surface directly.

    Raised for deploy-specific failures (oversized payload, missing
    entrypoint, transport staging error after retries exhausted).
    Transport-level errors propagate as their own types (e.g.
    :class:`~chumicro_deploy.circuitpython_transport.CircuitpythonTransportError`)
    so callers can branch on the underlying cause.
    """


@dataclass(frozen=True)
class DeployResult:
    """Outcome of a single ``Deployer.deploy_diff()`` call.

    Attributes:
        success: ``True`` when the entrypoint executed and the board
            reported a clean exit (no traceback, no safe-mode banner).
        staged_files: On-device paths that were written (for flash
            mode) or the host-side staging paths that fed the RAM-mode
            inline execution.  Empty when staging never completed.
        execute_output: Combined stdout captured from the board while
            the entrypoint ran.  Empty when the execute step never
            fired.
        traceback: Traceback text extracted from ``execute_output``
            when the board reported one, otherwise ``None``.  A
            non-``None`` traceback implies ``success=False``.
    """

    success: bool
    staged_files: list[str] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    execute_output: str = ""
    traceback: str | None = None
