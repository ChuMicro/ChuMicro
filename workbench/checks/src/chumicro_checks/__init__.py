"""``chumicro-checks``: workspace-internal lint rules.

Public API:

* :class:`Finding`: one rule violation (path, line, code, message).
* :class:`Rule`: abstract base; a rule walks a repo root and returns
  findings.
* :func:`registered_rules`: every rule the package ships, keyed by
  CHU code.
"""

from __future__ import annotations

from chumicro_checks._finding import Finding
from chumicro_checks._rule import Rule
from chumicro_checks.rules import registered_rules

__all__ = ["Finding", "Rule", "registered_rules"]
