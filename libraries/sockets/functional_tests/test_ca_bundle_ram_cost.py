"""On-device RAM cost of the shipped CA bundle (MicroPython only).

Measures the resident heap of the default ``ssl.SSLContext`` built
from ``_ca_bundle.read_der()``, and confirms releasing the context
releases ~all of it (no pinned DER buffer, no double-parse).  Pure —
no wifi, no sockets — so it's deterministic and fast.

Two jobs:

1. **Regression guard.**  A sudden jump in resident cost means a
   double-parse or a retained DER buffer crept in.
2. **The numbers behind the curated-subset size.**  MicroPython's
   ``ssl`` only exposes ``load_verify_locations`` →
   ``mbedtls_x509_crt_parse(make_copy=1)``, which copies + parses
   *every* root into heap for the context's lifetime (CP's firmware
   bundle uses a flash-resident verify callback instead — pure-Python
   MP cannot match it).  So the root count is bounded by this
   measured per-bundle resident cost against the board's working
   heap — a permanent architectural ceiling, not a stopgap.

CircuitPython uses its firmware ``x509-crt-bundle`` and never reads
this file, so the test is MicroPython-scoped via the runtime marker.

Transient peak is minimised by construction and not separately
asserted: the bundle ships as DER (no ``_pem_to_der`` base64 decode
on the default path) and ``read_der()``'s buffer is a function-scoped
temporary freed before any long-lived TLS allocation.
"""

__chumicro_runtimes__ = ("micropython",)

import gc

from chumicro_sockets import _ca_bundle, ssl_context_with_ca

#: Resident-cost ceiling for the shipped bundle.  Generous — this is
#: a regression trip-wire (sudden ~2x ⇒ double-parse / retained
#: buffer), not a tight fit.  Re-derive if the curated root set grows
#: materially; the printed ``resident=`` is the real datum.
_RESIDENT_CEILING_BYTES = 60_000


#: Post-release retention tolerance.  The parsed chain frees with the
#: context; what remains is allocator entropy (MP's mark-sweep + 16 B
#: blocks), not a leak.  A pinned DER buffer or leaked chain would
#: retain on the order of the resident cost, far above this.
_RETENTION_TOLERANCE_BYTES = 2_048


def test_default_bundle_resident_cost_and_release() -> None:
    """Build the default context from the shipped DER; assert the
    *incremental* resident heap is bounded and fully released on
    ``del``.

    A warm-up context is built and discarded first so the baseline
    already includes the one-time costs every TLS program pays once —
    the ``ssl`` module import, the mbedTLS Python bindings, any
    interned globals.  ``del`` cannot reclaim those (they live in
    ``sys.modules``); measuring against a cold baseline would
    misattribute ~5 KB of module-load overhead to the bundle and look
    like a leak.  The warmed measurement isolates the per-context
    parsed-chain cost, which is what scales with the root count and
    what must free cleanly.
    """
    der_len = len(_ca_bundle.read_der())

    warmup = ssl_context_with_ca(_ca_bundle.read_der())
    del warmup
    gc.collect()
    baseline = gc.mem_free()

    context = ssl_context_with_ca(_ca_bundle.read_der())
    gc.collect()
    resident = baseline - gc.mem_free()

    del context
    gc.collect()
    retained = baseline - gc.mem_free()

    print(
        f"BUNDLE der_bytes={der_len} baseline={baseline} "
        f"resident={resident} retained={retained}",
    )

    assert resident > 0, "building the context must cost resident heap"
    assert resident < _RESIDENT_CEILING_BYTES, (
        f"shipped-bundle parsed-chain resident heap {resident} B "
        f"exceeds the {_RESIDENT_CEILING_BYTES} B ceiling — likely a "
        f"double-parse or a retained DER buffer regression"
    )
    # The parsed chain must free with the context — no pinned DER
    # buffer (a module constant would retain ~der_len), no leaked
    # chain.  Only allocator entropy should remain.
    assert retained < _RETENTION_TOLERANCE_BYTES, (
        f"releasing the context retained {retained} B (resident was "
        f"{resident} B) — the DER buffer or parsed chain is being held"
    )
