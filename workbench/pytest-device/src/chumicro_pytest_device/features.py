"""Per-board feature gating for functional tests.

Lets a test file declare hardware-feature requirements finer-grained
than ``__chumicro_runtimes__``, e.g. "MicroPython on an ESP32-family
chip" where ``import esp32`` only succeeds on the right silicon::

    __chumicro_runtimes__ = ("micropython",)
    __chumicro_features__ = ("esp32",)

A device's feature set is discovered at session start by running
:data:`FEATURE_PROBE_SCRIPT` over the transport and parsing the
output through :func:`parse_feature_probe_output`.  At collection,
the plugin reads ``__chumicro_features__`` from each test file via
AST, and a device that doesn't carry every listed feature gets that
file dropped from its plan.  ``__chumicro_features__`` is AND-of-
features (every entry required), where ``__chumicro_runtimes__`` is
OR-of-runtimes.

Adding a feature touches three sites: :data:`KNOWN_FEATURES`,
:data:`FEATURE_PROBE_SCRIPT`, and :func:`parse_feature_probe_output`.
Features must be detectable via a cheap ``import`` probe, never
something side-effecting.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: Feature names that test files may declare via ``__chumicro_features__``.
#: See the module docstring for the three-site update protocol when adding
#: a new feature.
KNOWN_FEATURES: frozenset[str] = frozenset({"esp32"})

_PROBE_BEGIN = "CHUMICRO_FEATURES_BEGIN"
_PROBE_END = "CHUMICRO_FEATURES_END"

#: Python script run on each target device to discover its feature
#: set.  Each detected feature prints on its own line between the
#: BEGIN / END sentinels so the parser can locate the section under
#: arbitrary boot or print noise.
FEATURE_PROBE_SCRIPT = (
    "_chumicro_features = []\n"
    "try:\n"
    "    import esp32 as _probe_esp32\n"
    "    _chumicro_features.append('esp32')\n"
    "except ImportError:\n"
    "    pass\n"
    f"print('{_PROBE_BEGIN}')\n"
    "for _feature in _chumicro_features:\n"
    "    print(_feature)\n"
    f"print('{_PROBE_END}')\n"
)


def read_features_marker(python_file: Path) -> frozenset[str] | None:
    """Return the ``__chumicro_features__`` set declared in *python_file*.

    Uses an AST-only read so feature-marked files can import
    device-only modules at top level without breaking host-side
    parsing.

    Returns ``None`` when the marker is absent (file makes no
    feature claim, runs on every target the runtime filter
    accepted).  Returns a (possibly empty) frozenset when present.

    Args:
        python_file: Path to the test file to inspect.
    """
    try:
        tree = ast.parse(python_file.read_text(), filename=str(python_file))
    except (SyntaxError, OSError):
        return None  # Treat unreadable files as universal, fail-safe.
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [
            target.id for target in node.targets if isinstance(target, ast.Name)
        ]
        if "__chumicro_features__" not in targets:
            continue
        if not isinstance(node.value, (ast.Tuple, ast.List)):
            continue
        names: list[str] = []
        for element in node.value.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                names.append(element.value)
        return frozenset(names)
    return None


def parse_feature_probe_output(output: str) -> frozenset[str]:
    """Extract the device's feature set from :data:`FEATURE_PROBE_SCRIPT` output.

    Collects feature names emitted between the ``CHUMICRO_FEATURES_BEGIN``
    and ``..._END`` sentinels.  Lines outside the sentinels are ignored
    (boot banners, unrelated prints).  Names inside the sentinels that
    aren't in :data:`KNOWN_FEATURES` are dropped, so a probe typo can't
    quietly grant a fake capability.

    Args:
        output: Raw stdout captured from running
            :data:`FEATURE_PROBE_SCRIPT` via ``transport.execute``.
    """
    in_section = False
    features: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line == _PROBE_BEGIN:
            in_section = True
            continue
        if line == _PROBE_END:
            return frozenset(features)
        if in_section and line in KNOWN_FEATURES:
            features.append(line)
    # Truncated probe output (no END sentinel reached).  Return what
    # we have so partial probes still favour skipping a feature-marked
    # test over claiming an unverified capability.
    return frozenset(features)
