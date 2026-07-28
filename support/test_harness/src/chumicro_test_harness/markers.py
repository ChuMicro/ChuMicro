"""Board-side helper for host-parsed marker lines.

A board signals checkpoints to the host by printing ``NAME key=value
key=value ...`` lines; the host's marker parser
(``chumicro_workspace.markers``) drops the *entire* line when any
value contains whitespace or ``=``.  A demo lost its ``ECHO_RECEIVED``
marker to exactly that and burned a 10 s wait budget with no
diagnostic.  :func:`marker` makes the constraint structural instead of
documented: ``bytes`` values ride as hex, everything else must
stringify clean or the call raises at develop time.
"""

#: Names owned by the result parser (PASS / FAIL / SKIP / SUMMARY /
#: HEAP lines); the host never parses them as markers, so emitting one
#: as a marker is always a mistake.
_RESERVED_NAMES = ("PASS", "FAIL", "SKIP", "SUMMARY", "HEAP")

#: Characters that make the host drop the whole marker line.
_FORBIDDEN = (" ", "\t", "\n", "\r", "=")


def marker(name, **values):
    """Print one host-parsed marker line: ``NAME key=value ...``.

    Args:
        name: Uppercase marker identifier (``ECHO_RECEIVED``).  The
            result-parser names (``PASS`` / ``FAIL`` / ``SKIP`` /
            ``SUMMARY`` / ``HEAP``) are rejected, since the host never
            reads them as markers.
        **values: Marker values.  ``bytes`` / ``bytearray`` /
            ``memoryview`` are hex-encoded (the only whitespace-safe
            way to carry arbitrary payloads); everything else is
            ``str()``-ed and must contain no whitespace and no ``=``.
            Keys are emitted sorted, since dict ordering is not
            guaranteed on MicroPython.

    Raises:
        ValueError: *name* is reserved or not uppercase-led, or a
            value stringifies with whitespace / ``=`` in it.  This is
            loud at develop time instead of a silently dropped marker
            at run time.
    """
    if not name or not ("A" <= name[0] <= "Z"):
        raise ValueError(f"marker name must be uppercase-led: {name!r}")
    if name in _RESERVED_NAMES:
        raise ValueError(f"marker name {name!r} is reserved for the result parser")
    parts = [name]
    for key in sorted(values):
        value = values[key]
        if isinstance(value, (bytes, bytearray, memoryview)):
            text = bytes(value).hex()
        else:
            text = str(value)
        if not text:
            raise ValueError(
                f"marker value {key}= is empty; the host parser needs at "
                f"least one character",
            )
        for forbidden in _FORBIDDEN:
            if forbidden in text:
                raise ValueError(
                    f"marker value {key}={text!r} contains {forbidden!r}; "
                    f"values must be whitespace-free and '='-free "
                    f"(pass bytes to hex-encode)",
                )
        parts.append(f"{key}={text}")
    print(" ".join(parts))
