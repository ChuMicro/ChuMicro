"""Device-facing probe: which ``partial`` did this runtime select, and
does the selected one round-trip.

The unit suite already exercises ``_PurePythonPartial`` exhaustively by
importing it directly.  What only a real runtime can answer is the
selection in ``chumicro_compat.functools``: whether ``functools.partial``
existed, whether it carried the full introspection surface, and whether
the polyfill stepped in.  So this file asserts the selected object works
once end to end and then probes which implementation won.
"""

from chumicro_compat.functools import _PurePythonPartial, partial


def test_selected_partial_round_trips() -> None:
    """The runtime-selected partial freezes positionals and keywords in
    one call and exposes the introspection trio the selector demands."""
    def tag(key: str, value: str = "b") -> str:
        return f"{key}={value}"

    tagged = partial(tag, "sensor", value="42")
    assert tagged() == "sensor=42"
    assert tagged.func is tag
    assert tagged.args == ("sensor",)
    assert tagged.keywords == {"value": "42"}


def test_selection_is_reportable() -> None:
    """The selection resolved to exactly one of the two candidates, and
    which one is visible in the failure message when this assert trips
    on an unexpected runtime."""
    try:
        from functools import partial as runtime_partial
    except ImportError:
        runtime_partial = None

    selected_polyfill = partial is _PurePythonPartial
    if runtime_partial is None:
        assert selected_polyfill, "no functools.partial, polyfill must win"
    else:
        probe = runtime_partial(int, 0)
        degraded = not (
            hasattr(probe, "func")
            and hasattr(probe, "args")
            and hasattr(probe, "keywords")
        )
        assert selected_polyfill == degraded, (
            f"selection mismatch: runtime partial degraded={degraded}, "
            f"polyfill selected={selected_polyfill}"
        )
