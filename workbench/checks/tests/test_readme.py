"""README-vs-registry parity: the rule table must document every rule.

Guards the doc drift where the README's rule range and table lagged the
registry (CHU029-CHU033 were registered and gating but undocumented).
"""

from __future__ import annotations

import re
from pathlib import Path

from chumicro_checks import registered_rules

_README = Path(__file__).resolve().parents[1] / "README.md"


def _readme_text() -> str:
    return _README.read_text(encoding="utf-8")


def _documented_codes(text: str) -> set[str]:
    """Rule codes appearing as a ``| `CHUNNN` |`` table row."""
    return set(re.findall(r"^\|\s*`(CHU\d{3})`\s*\|", text, re.MULTILINE))


class TestReadmeRuleTable:
    def test_every_registered_rule_has_a_table_row(self) -> None:
        documented = _documented_codes(_readme_text())
        registered = set(registered_rules())
        missing = registered - documented
        assert not missing, f"rules registered but undocumented: {sorted(missing)}"

    def test_no_phantom_rows_for_unregistered_codes(self) -> None:
        documented = _documented_codes(_readme_text())
        registered = set(registered_rules())
        phantom = documented - registered
        assert not phantom, f"README documents unregistered rules: {sorted(phantom)}"
