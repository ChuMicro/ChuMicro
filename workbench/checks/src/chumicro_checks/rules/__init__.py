"""Rule registry.

Each rule module exposes a single :class:`Rule` subclass instance
named after the rule code (e.g. ``CHU011``).  :func:`registered_rules`
returns the canonical mapping that the CLI iterates.
"""

from __future__ import annotations

from chumicro_checks._rule import Rule
from chumicro_checks.rules.chu007 import CHU007
from chumicro_checks.rules.chu011 import CHU011
from chumicro_checks.rules.chu012 import CHU012


def registered_rules() -> dict[str, Rule]:
    """Return every rule the package ships, keyed by CHU code.

    The dict is rebuilt on every call so test code can stub
    individual rule modules without leaking state.
    """
    return {
        CHU007.code: CHU007,
        CHU011.code: CHU011,
        CHU012.code: CHU012,
    }
