"""Tests for ``chumicro_pytest_device.features``."""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_pytest_device.features import (
    FEATURE_PROBE_SCRIPT,
    KNOWN_FEATURES,
    parse_feature_probe_output,
    read_features_marker,
)

# ---------------------------------------------------------------------------
# read_features_marker
# ---------------------------------------------------------------------------


def test_read_features_marker_returns_none_when_absent(tmp_path: Path) -> None:
    """Files without ``__chumicro_features__`` return None (universal)."""
    target = tmp_path / "test_universal.py"
    target.write_text("def test_anything() -> None:\n    pass\n")

    assert read_features_marker(target) is None


def test_read_features_marker_reads_tuple_form(tmp_path: Path) -> None:
    """A tuple-form ``__chumicro_features__`` parses to a frozenset."""
    target = tmp_path / "test_features_tuple.py"
    target.write_text(
        '__chumicro_features__ = ("esp32",)\n'
        "def test_anything() -> None:\n    pass\n",
    )

    result = read_features_marker(target)
    assert result == frozenset({"esp32"})


def test_read_features_marker_reads_list_form(tmp_path: Path) -> None:
    """List-form is also accepted (matches ``__chumicro_runtimes__`` parser)."""
    target = tmp_path / "test_features_list.py"
    target.write_text(
        '__chumicro_features__ = ["esp32"]\n'
        "def test_anything() -> None:\n    pass\n",
    )

    assert read_features_marker(target) == frozenset({"esp32"})


def test_read_features_marker_handles_multiple_names(tmp_path: Path) -> None:
    """Multiple feature strings produce a frozenset of all of them."""
    target = tmp_path / "test_features_multi.py"
    target.write_text(
        '__chumicro_features__ = ("esp32", "future_feature")\n'
        "def test_anything() -> None:\n    pass\n",
    )

    assert read_features_marker(target) == frozenset({"esp32", "future_feature"})


def test_read_features_marker_returns_empty_frozenset_when_explicitly_empty(
    tmp_path: Path,
) -> None:
    """An explicit empty tuple is distinct from an absent marker."""
    target = tmp_path / "test_features_empty.py"
    target.write_text(
        "__chumicro_features__ = ()\n"
        "def test_anything() -> None:\n    pass\n",
    )

    assert read_features_marker(target) == frozenset()


def test_read_features_marker_does_not_execute_module(tmp_path: Path) -> None:
    """The reader uses AST only, so device-only imports at top level
    don't break parsing on the host."""
    target = tmp_path / "test_features_device_imports.py"
    # ``import esp32`` would explode on CPython at import time. The
    # AST reader must skip past it.
    target.write_text(
        "__chumicro_features__ = ('esp32',)\n"
        "import esp32  # type: ignore[import-not-found]\n"
        "def test_anything() -> None:\n    pass\n",
    )

    assert read_features_marker(target) == frozenset({"esp32"})


def test_read_features_marker_returns_none_on_syntax_error(tmp_path: Path) -> None:
    """Unparseable files are treated as universal (fail-safe)."""
    target = tmp_path / "test_broken_syntax.py"
    target.write_text("def broken(:\n    pass\n")

    assert read_features_marker(target) is None


def test_read_features_marker_ignores_non_string_elements(tmp_path: Path) -> None:
    """Numeric / nested-tuple elements are silently dropped."""
    target = tmp_path / "test_features_mixed.py"
    target.write_text(
        '__chumicro_features__ = ("esp32", 42, ("nested",))\n'
        "def test_anything() -> None:\n    pass\n",
    )

    assert read_features_marker(target) == frozenset({"esp32"})


def test_read_features_marker_ignores_non_tuple_value(tmp_path: Path) -> None:
    """Non-tuple/list values produce None (treated as missing)."""
    target = tmp_path / "test_features_bad.py"
    target.write_text(
        "__chumicro_features__ = 'esp32'\n"
        "def test_anything() -> None:\n    pass\n",
    )

    assert read_features_marker(target) is None


# ---------------------------------------------------------------------------
# parse_feature_probe_output
# ---------------------------------------------------------------------------


def test_parse_feature_probe_output_finds_esp32() -> None:
    """The standard ESP32 path: BEGIN sentinel, ``esp32``, END sentinel."""
    output = (
        "boot noise line\n"
        "CHUMICRO_FEATURES_BEGIN\n"
        "esp32\n"
        "CHUMICRO_FEATURES_END\n"
    )

    assert parse_feature_probe_output(output) == frozenset({"esp32"})


def test_parse_feature_probe_output_returns_empty_when_no_features() -> None:
    """A board with no detected features yields the empty set."""
    output = (
        "CHUMICRO_FEATURES_BEGIN\n"
        "CHUMICRO_FEATURES_END\n"
    )

    assert parse_feature_probe_output(output) == frozenset()


def test_parse_feature_probe_output_drops_unknown_names() -> None:
    """A name that isn't in ``KNOWN_FEATURES`` is dropped (not silently accepted)."""
    output = (
        "CHUMICRO_FEATURES_BEGIN\n"
        "esp32\n"
        "made_up_feature\n"
        "CHUMICRO_FEATURES_END\n"
    )

    assert parse_feature_probe_output(output) == frozenset({"esp32"})


def test_parse_feature_probe_output_ignores_lines_outside_sentinels() -> None:
    """Print noise outside the section is ignored even if it names a known feature."""
    output = (
        "esp32\n"  # before BEGIN, ignored
        "CHUMICRO_FEATURES_BEGIN\n"
        "CHUMICRO_FEATURES_END\n"
        "esp32\n"  # after END, also ignored
    )

    assert parse_feature_probe_output(output) == frozenset()


def test_parse_feature_probe_output_handles_truncated_probe() -> None:
    """If the probe stream cuts off before END, return what was seen."""
    output = (
        "CHUMICRO_FEATURES_BEGIN\n"
        "esp32\n"
        # No END sentinel: connection dropped or device reset.
    )

    assert parse_feature_probe_output(output) == frozenset({"esp32"})


def test_parse_feature_probe_output_handles_no_sentinels_at_all() -> None:
    """A completely missing probe section yields the empty set, not a crash."""
    output = "boot banner\nready\n"

    assert parse_feature_probe_output(output) == frozenset()


# ---------------------------------------------------------------------------
# FEATURE_PROBE_SCRIPT shape
# ---------------------------------------------------------------------------


def test_probe_script_includes_known_feature_imports() -> None:
    """Every entry in ``KNOWN_FEATURES`` must be probed by the script.

    Catches the case where someone adds a feature name to ``KNOWN_FEATURES``
    without extending the probe script.  Without this gate, a typo
    in the script would silently report the new feature as absent on
    every device.
    """
    for feature_name in KNOWN_FEATURES:
        assert feature_name in FEATURE_PROBE_SCRIPT, (
            f"feature {feature_name!r} listed in KNOWN_FEATURES but "
            f"not mentioned in FEATURE_PROBE_SCRIPT — extend the probe."
        )


def test_probe_script_emits_begin_and_end_sentinels() -> None:
    """The probe script's output must bracket features with the sentinels
    ``parse_feature_probe_output`` looks for."""
    assert "CHUMICRO_FEATURES_BEGIN" in FEATURE_PROBE_SCRIPT
    assert "CHUMICRO_FEATURES_END" in FEATURE_PROBE_SCRIPT


def test_probe_script_compiles_under_cpython() -> None:
    """The probe script must be a valid Python program, caught here so a
    syntax error doesn't surface as a confusing device-side failure."""
    compile(FEATURE_PROBE_SCRIPT, "<feature-probe>", "exec")


@pytest.mark.parametrize("feature_name", sorted(KNOWN_FEATURES))
def test_known_features_round_trip_through_parser(feature_name: str) -> None:
    """A line containing a known feature between sentinels round-trips."""
    output = (
        f"CHUMICRO_FEATURES_BEGIN\n"
        f"{feature_name}\n"
        f"CHUMICRO_FEATURES_END\n"
    )
    assert parse_feature_probe_output(output) == frozenset({feature_name})
