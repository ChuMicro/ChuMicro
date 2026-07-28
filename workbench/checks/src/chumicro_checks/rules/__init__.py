"""Rule registry.

Each rule module exposes a single :class:`Rule` subclass instance
named after the rule code (e.g. ``CHU011``).  :func:`registered_rules`
returns the mapping the CLI iterates.
"""

from __future__ import annotations

from chumicro_checks._rule import Rule
from chumicro_checks.rules.chu001 import CHU001
from chumicro_checks.rules.chu002to005_018 import (
    CHU002,
    CHU003,
    CHU004,
    CHU005,
    CHU018,
)
from chumicro_checks.rules.chu006 import CHU006
from chumicro_checks.rules.chu007 import CHU007
from chumicro_checks.rules.chu008 import CHU008
from chumicro_checks.rules.chu009_chu010 import CHU009, CHU010
from chumicro_checks.rules.chu011 import CHU011
from chumicro_checks.rules.chu012 import CHU012
from chumicro_checks.rules.chu013 import CHU013
from chumicro_checks.rules.chu014 import CHU014
from chumicro_checks.rules.chu015 import CHU015
from chumicro_checks.rules.chu016 import CHU016
from chumicro_checks.rules.chu017 import CHU017
from chumicro_checks.rules.chu019 import CHU019
from chumicro_checks.rules.chu020 import CHU020
from chumicro_checks.rules.chu024 import CHU024
from chumicro_checks.rules.chu025 import CHU025
from chumicro_checks.rules.chu026 import CHU026
from chumicro_checks.rules.chu027 import CHU027
from chumicro_checks.rules.chu028 import CHU028
from chumicro_checks.rules.chu029 import CHU029
from chumicro_checks.rules.chu030 import CHU030
from chumicro_checks.rules.chu031 import CHU031
from chumicro_checks.rules.chu032 import CHU032
from chumicro_checks.rules.chu033 import CHU033
from chumicro_checks.rules.chu034 import CHU034
from chumicro_checks.rules.chu035 import CHU035
from chumicro_checks.rules.chu036 import CHU036
from chumicro_checks.rules.chu037 import CHU037


def registered_rules() -> dict[str, Rule]:
    """Return every rule the package ships, keyed by CHU code.

    The dict is rebuilt on every call so test code can stub
    individual rule modules without leaking state.
    """
    return {
        CHU001.code: CHU001,
        CHU002.code: CHU002,
        CHU003.code: CHU003,
        CHU004.code: CHU004,
        CHU005.code: CHU005,
        CHU006.code: CHU006,
        CHU007.code: CHU007,
        CHU008.code: CHU008,
        CHU009.code: CHU009,
        CHU010.code: CHU010,
        CHU011.code: CHU011,
        CHU012.code: CHU012,
        CHU013.code: CHU013,
        CHU014.code: CHU014,
        CHU015.code: CHU015,
        CHU016.code: CHU016,
        CHU017.code: CHU017,
        CHU018.code: CHU018,
        CHU019.code: CHU019,
        CHU020.code: CHU020,
        CHU024.code: CHU024,
        CHU025.code: CHU025,
        CHU026.code: CHU026,
        CHU027.code: CHU027,
        CHU028.code: CHU028,
        CHU029.code: CHU029,
        CHU030.code: CHU030,
        CHU031.code: CHU031,
        CHU032.code: CHU032,
        CHU033.code: CHU033,
        CHU034.code: CHU034,
        CHU035.code: CHU035,
        CHU036.code: CHU036,
        CHU037.code: CHU037,
    }
