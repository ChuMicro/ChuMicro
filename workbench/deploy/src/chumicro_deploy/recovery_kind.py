"""Shared types for the deploy-recovery layer.

:class:`DeployFailureKind` and :class:`RecoveryPlan` live in a leaf
module so the plans registry and the classifier can both import them
without forming a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DeployFailureKind(Enum):
    """Broad categories of deploy failures, keyed to recovery guidance.

    The dozens of ``CircuitpythonTransportError`` sites and MP
    transport errors all collapse into these buckets.  Each bucket
    has a canned :class:`RecoveryPlan` in
    :mod:`chumicro_deploy.recovery_plans` whose ``retryable`` flag
    drives whether the recovery loop continues or bails.
    """

    PORT_UNAVAILABLE = "port_unavailable"
    RAW_REPL_UNRESPONSIVE = "raw_repl_unresponsive"
    COMMAND_TIMED_OUT = "command_timed_out"
    NO_PYTHON_RUNTIME = "no_python_runtime"
    CIRCUITPY_DRIVE_MISSING = "circuitpy_drive_missing"
    MACOS_FSKIT_WEDGED = "macos_fskit_wedged"
    FAT_VOLUME_CORRUPT = "fat_volume_corrupt"
    FLASH_COPY_FAILED = "flash_copy_failed"
    BOOTSTRAP_EXEC_FAILED = "bootstrap_exec_failed"
    INSUFFICIENT_MEMORY = "insufficient_memory"
    TRACEBACK_RETURNED = "traceback_returned"
    CONFIGURATION_ERROR = "configuration_error"
    UNRESOLVED_IMPORT = "unresolved_import"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RecoveryPlan:
    """User-facing guidance for a single :class:`DeployFailureKind`.

    Attributes:
        headline: One-line summary the user reads first.
        fix_steps: Ordered physical actions the user can take.  Each
            step is a short imperative sentence, rendered as a
            bulleted list.
        retryable: ``True`` when retrying after the user takes the
            fix steps is worth attempting.  ``False`` for hard
            failures (wrong flags, runtime tracebacks, too-small
            boards) where a retry would change nothing.
    """

    headline: str
    fix_steps: tuple[str, ...]
    retryable: bool
