"""Loader for the shipped default CA bundle (MicroPython only).

The bundle itself is the sibling **data file** ``_ca_bundle.der`` —
concatenated DER, the format ``mbedtls_x509_crt_parse`` walks
natively and the lowest-common-denominator across MP ports (rp2's
mbedTLS lacks ``MBEDTLS_PEM_PARSE_C``).

Why a data file rather than a ``PEM_BYTES`` / ``DER_BYTES`` module
constant: a module constant is allocated at import time and pinned in
``sys.modules`` for the process lifetime; evicting it after the
context is built strands a multi-KB hole among the long-lived
``SSLContext`` / mbedTLS-chain objects (MicroPython's GC is
non-compacting).  Reading the file into a function-scoped buffer that
is dropped the moment :func:`read_der` returns lets the GC reclaim it
*before* the socket + handshake working set allocates — the freed
span is immediately reused by the next allocations in the same code
path instead of fragmenting.  Data-file deploys are forced flash-mode
(RAM-mode CP has no filesystem), so the sibling path is reliable.

Consulted only on MicroPython: CircuitPython attaches its
firmware-bundled ``x509-crt-bundle``; CPython uses the OS trust
store.  Override at runtime via
:func:`chumicro_sockets.set_default_ca_bundle`.

Roots shipped (17, covering the bulk of modern public HTTPS): ISRG
Root X1/X2 (Let's Encrypt), DigiCert Global Root CA/G2/G3, Amazon
Root CA 1, GTS Root R1/R4 (Google), GlobalSign Root CA, AAA
Certificate Services + USERTrust RSA/ECC (Sectigo — the largest CA
by certificate count), Go Daddy / Starfield Services G2, Entrust
Root G2, Microsoft RSA/ECC Root 2017.  A strict subset of
CircuitPython's firmware bundle, so a chain that validates here on
MP also validates against the CP firmware bundle on the same board.
~16 KB DER; ~500 B parsed-chain RAM per root (measured — see
``functional_tests/test_ca_bundle_ram_cost.py``), far below the
board headroom, so flash (~900 B/root) and bundle maintenance, not
RAM, bound the set size.  The set is a permanent curated subset, not
a stopgap: MicroPython's ``ssl`` only exposes
``load_verify_locations`` (parse-every-root-into-heap); it cannot
use a flash-resident verify callback the way CircuitPython's
firmware bundle does, so shipping all ~150 Mozilla roots is not
viable on a 256 KB board.
"""

__chumicro_runtimes__ = ("micropython",)

#: Canonical flash-deploy location, used only if ``__file__`` is
#: unavailable on a given MP build.
_FALLBACK_PATH = "/lib/chumicro_sockets/_ca_bundle.der"


def read_der():
    """Return the shipped bundle's concatenated DER bytes.

    The caller (``_adapters.mp._default_context``) feeds the result
    straight into ``ssl_context_with_ca`` and keeps no reference, so
    the buffer is collectable as soon as ``load_verify_locations`` has
    copied it into mbedTLS — the tight lifetime is the whole point of
    shipping a file (see module docstring).
    """
    try:
        here = __file__.rsplit("/", 1)[0]
        path = here + "/_ca_bundle.der"
    except (NameError, AttributeError):  # pragma: no cover - __file__ absent on some MP builds
        path = _FALLBACK_PATH
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:  # pragma: no cover - defensive: flash-deploy fallback
        with open(_FALLBACK_PATH, "rb") as handle:
            return handle.read()
