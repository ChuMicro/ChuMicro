"""Cross-runtime tests for chumicro_test_harness.network.

Exercises the inline msgpack decoder against the value types
``runtime_config`` actually sees on deployed boards, plus the
caller-facing error paths of ``wifi_up`` (placeholder ssid,
empty ssid, unsupported runtime).

Tests for the placeholder / empty-ssid raise paths assume the
host filesystem does not have ``/runtime_config.msgpack`` (the
deployed-config override would otherwise replace the caller's
empty default with a real ssid). Skipped when the file exists
so a freshly-reset board with no config still passes.
"""

import os
import sys

from chumicro_test_harness import raises, skip
from chumicro_test_harness.network import (
    _msgpack_unpack,
    runtime_config,
    wifi_up,
)

try:
    os.stat("/runtime_config.msgpack")
    _HAS_DEPLOYED_CONFIG = True
except OSError:
    _HAS_DEPLOYED_CONFIG = False


def test_msgpack_unpack_decodes_flat_dict_of_strings_and_ints():
    """A fixmap with str keys and mixed int values decodes to the matching dict."""
    # {"wifi.ssid": "ap", "wifi.port": 8}
    payload = (
        b"\x82"                                  # fixmap, 2 entries
        b"\xa9wifi.ssid"                         # fixstr "wifi.ssid"
        b"\xa2ap"                                # fixstr "ap"
        b"\xa9wifi.port"                         # fixstr "wifi.port"
        b"\x08"                                  # positive fixint 8
    )
    value, end = _msgpack_unpack(memoryview(payload), 0)
    assert value == {"wifi.ssid": "ap", "wifi.port": 8}
    assert end == len(payload)


def test_msgpack_unpack_decodes_nested_array_and_map():
    """Arrays nested inside maps round-trip with their element types preserved."""
    # {"items": [1, "two", True, None]}
    payload = (
        b"\x81"                  # fixmap, 1 entry
        b"\xa5items"             # fixstr "items"
        b"\x94"                  # fixarray, 4 entries
        b"\x01"                  # 1
        b"\xa3two"               # "two"
        b"\xc3"                  # true
        b"\xc0"                  # nil
    )
    value, _ = _msgpack_unpack(memoryview(payload), 0)
    assert value == {"items": [1, "two", True, None]}


def test_msgpack_unpack_handles_every_integer_width_runtime_config_uses():
    """Positive + negative integers across uint8/16/32 and int8/16/32 widths decode correctly."""
    cases = (
        (b"\xcc\xff", 255),                              # uint 8
        (b"\xcd\x01\x00", 256),                          # uint 16
        (b"\xce\x00\x01\x00\x00", 65536),                # uint 32
        (b"\xd0\x80", -128),                             # int 8
        (b"\xd1\xff\x00", -256),                         # int 16
        (b"\xd2\xff\xff\x00\x00", -65536),               # int 32
        (b"\x7f", 127),                                  # positive fixint
        (b"\xff", -1),                                   # negative fixint
    )
    for payload, expected in cases:
        value, end = _msgpack_unpack(memoryview(payload), 0)
        assert value == expected, f"failed for {payload!r}: got {value!r}"
        assert end == len(payload)


def test_msgpack_unpack_decodes_false_literal_and_64bit_ints_and_floats():
    """false / uint64 / int64 / float32 / float64 each round-trip with the right type and value."""
    cases = (
        (b"\xc2", False),                                              # false
        (b"\xcf\x00\x00\x00\x01\x00\x00\x00\x00", 1 << 32),            # uint 64 above uint32
        (b"\xd3\xff\xff\xff\xff\x00\x00\x00\x00", -(1 << 32)),         # int 64
        (b"\xca\x40\x49\x0f\xdb", 3.1415927410125732),                 # float 32 approx pi
        (b"\xcb\x40\x09\x21\xfb\x54\x44\x2d\x18", 3.141592653589793),  # float 64 pi
    )
    for payload, expected in cases:
        value, end = _msgpack_unpack(memoryview(payload), 0)
        assert value == expected, f"failed for {payload!r}: got {value!r}"
        assert end == len(payload)


def test_msgpack_unpack_decodes_length_prefixed_str_and_bin():
    """str8 / str16 / bin8 / bin16 round-trip with the length prefix the spec demands."""
    long_str = "x" * 64  # > 31 chars → forces str 8 rather than fixstr
    cases = (
        (b"\xd9\x40" + long_str.encode(), long_str),                       # str 8
        (b"\xda\x00\x40" + long_str.encode(), long_str),                   # str 16
        (b"\xc4\x03\x01\x02\x03", b"\x01\x02\x03"),                        # bin 8
        (b"\xc5\x00\x03\x01\x02\x03", b"\x01\x02\x03"),                    # bin 16
    )
    for payload, expected in cases:
        value, end = _msgpack_unpack(memoryview(payload), 0)
        assert value == expected, f"failed for {payload!r}: got {value!r}"
        assert end == len(payload)


def test_msgpack_unpack_decodes_extended_length_array_and_map():
    """array 16 / map 16 prefixes decode the same as their fix-* counterparts."""
    # array 16 of three integers
    array_payload = b"\xdc\x00\x03\x01\x02\x03"
    value, end = _msgpack_unpack(memoryview(array_payload), 0)
    assert value == [1, 2, 3]
    assert end == len(array_payload)
    # map 16 with one entry: {"k": "v"}
    map_payload = b"\xde\x00\x01\xa1k\xa1v"
    value, end = _msgpack_unpack(memoryview(map_payload), 0)
    assert value == {"k": "v"}
    assert end == len(map_payload)


def test_msgpack_unpack_raises_value_error_on_unknown_tag():
    """Tag bytes the decoder doesn't recognize raise ValueError with the hex tag in the message."""
    # 0xc1 is the spec's "never used" type tag.
    with raises(ValueError, match="0xc1"):
        _msgpack_unpack(memoryview(b"\xc1"), 0)


def test_runtime_config_returns_empty_dict_when_file_absent():
    """With no /runtime_config.msgpack on disk, runtime_config returns {} (not None, not raise)."""
    if _HAS_DEPLOYED_CONFIG:
        skip("/runtime_config.msgpack exists; absent-file path not testable here")
    assert runtime_config() == {}


def test_wifi_up_raises_runtime_error_for_empty_ssid():
    """An empty ssid trips the placeholder guard before any radio call fires."""
    if _HAS_DEPLOYED_CONFIG:
        skip("/runtime_config.msgpack would override the empty caller default")
    with raises(RuntimeError, match="WIFI_SSID"):
        wifi_up("", "password")


def test_wifi_up_raises_runtime_error_for_placeholder_ssid():
    """The shipped-template placeholder 'your-wifi-ssid' raises so a forgotten edit fails loud."""
    if _HAS_DEPLOYED_CONFIG:
        skip("/runtime_config.msgpack would override the placeholder caller default")
    with raises(RuntimeError, match="WIFI_SSID"):
        wifi_up("your-wifi-ssid", "password")


def test_wifi_up_raises_runtime_error_on_unsupported_runtime():
    """On CPython (no built-in wifi), wifi_up raises with the runtime name in the message."""
    if sys.implementation.name != "cpython":
        skip("only the CPython path exercises the unsupported-runtime branch")
    if _HAS_DEPLOYED_CONFIG:
        skip("/runtime_config.msgpack would override the caller-supplied real ssid")
    with raises(RuntimeError, match="cpython"):
        wifi_up("real-network", "password")
