"""Shared types for the deploy-recovery layer.

:class:`DeployFailureKind` and :class:`RecoveryPlan` live here, not
in :mod:`recovery`, because they're imported by both consumers
(``recovery_plans`` populates the plans dict, ``recovery`` classifies
failures and looks them up).  Keeping the types in a leaf module
breaks the otherwise-cyclic graph cleanly.

Both names are re-exported from :mod:`chumicro_deploy.recovery` for
external consumers; this module is the canonical definition site.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DeployFailureKind(Enum):
    """Broad categories of deploy failures, keyed to recovery guidance.

    The classifier in :mod:`chumicro_deploy.recovery` collapses the
    ~20 distinct ``CircuitpythonTransportError`` sites and MP
    transport errors into these buckets.  Each bucket has a canned
    :class:`RecoveryPlan` in :mod:`chumicro_deploy.recovery_plans`;
    ``InteractiveDeployer`` consults the plan's ``retryable`` flag to
    decide whether to loop or bail.
    """

    PORT_UNAVAILABLE = "port_unavailable"
    RAW_REPL_UNRESPONSIVE = "raw_repl_unresponsive"
    NO_PYTHON_RUNTIME = "no_python_runtime"
    CIRCUITPY_DRIVE_MISSING = "circuitpy_drive_missing"
    MACOS_FSKIT_WEDGED = "macos_fskit_wedged"
    FLASH_COPY_FAILED = "flash_copy_failed"
    BOOTSTRAP_EXEC_FAILED = "bootstrap_exec_failed"
    INSUFFICIENT_MEMORY = "insufficient_memory"
    TRACEBACK_RETURNED = "traceback_returned"
    CONFIGURATION_ERROR = "configuration_error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RecoveryPlan:
    """User-facing guidance for a single :class:`DeployFailureKind`.

    Attributes:
        headline: One-line summary the user reads first.
        fix_steps: Ordered physical actions the user can take.  Each
            step is a short imperative sentence; the interactive
            deployer renders them as a bulleted list.
        retryable: ``True`` when retrying after the user takes the
            fix steps is worth attempting.  ``False`` for hard
            failures (wrong flags, runtime tracebacks, too-small
            boards) where a retry would change nothing.
    """

    headline: str
    fix_steps: tuple[str, ...]
    retryable: bool
