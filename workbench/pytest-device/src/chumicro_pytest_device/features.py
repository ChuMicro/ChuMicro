"""Per-board feature gating for functional tests.

Some functional tests need a runtime feature finer-grained than the
``__chumicro_runtimes__`` marker can express, e.g. "MicroPython on
an ESP32-family chip" (because ``import esp32`` only succeeds there).
A test file declares its requirements::

    __chumicro_runtimes__ = ("micropython",)
    __chumicro_features__ = ("esp32",)

The plugin reads both markers via AST (no execution) at collection
time and filters target devices.  Devices missing a required feature
get nothing collected for that file, the same shape as the runtime
filter, just driven by probe data rather than the device's declared
runtime.

Feature semantics:

* File-level marker, AND-of-features (test requires every listed
  feature), mirroring how :data:`__chumicro_runtimes__` is OR-of-
  runtimes.
* Features are derived per-device by running
  :data:`FEATURE_PROBE_SCRIPT` over the connected transport.  The
  script is small enough to inline via ``transport.execute`` and
  outputs one feature name per line between known sentinels.
* The currently-known feature set is :data:`KNOWN_FEATURES`.  Adding
  a new feature requires extending this set, the probe script, and
  :func:`parse_feature_probe_output`.

Why probe rather than maintaining a board-to-features table?  Boards
and their firmware change faster than a hand-maintained table can
keep up with.  Asking the device directly is authoritative and
costs one short ``transport.execute`` per target device per session.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: Known feature names that test files may declare via
#: ``__chumicro_features__``.  Adding a new feature requires:
#:
#: * extending this set,
#: * extending :data:`FEATURE_PROBE_SCRIPT` to detect it,
#: * extending :func:`parse_feature_probe_output` to recognize it.
#:
#: Every feature in this set must be detectable by an ``import``
#: probe.  The MicroPython REPL on the target board can do
#: ``try: import X`` cheaply.  Don't add features that need a
#: side-effecting probe (USB enumeration, hardware-register read).
KNOWN_FEATURES: frozenset[str] = frozenset({"esp32"})

_PROBE_BEGIN = "CHUMICRO_FEATURES_BEGIN"
_PROBE_END = "CHUMICRO_FEATURES_END"

#: Tiny Python script run on each target device to discover its
#: feature set.  Outputs one feature name per line between the
#: BEGIN / END sentinels so :func:`parse_feature_probe_output` can
#: find the section regardless of any boot or print noise.  Adding a
#: new feature here requires updating both :data:`KNOWN_FEATURES` and
#: :func:`parse_feature_probe_output`.
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

    Looks for the ``CHUMICRO_FEATURES_BEGIN`` / ``..._END`` sentinels
    and collects feature names between them.  Lines outside the
    sentinels (boot banners, ``print`` debug from other code) are
    ignored.

    Unknown feature strings between the sentinels are dropped.  The
    probe and the parser are kept in lockstep via
    :data:`KNOWN_FEATURES`, and treating an unknown name as a
    silently-acquired feature would let a typo in the probe script
    masquerade as a real capability.

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
    # No END sentinel: probe output truncated.  Return whatever we
    # accumulated so partial probes still skip-rather-than-include
    # feature-marked tests.
    return frozenset(features)
