"""Loader for the shipped default CA bundle (MicroPython only).

The bundle is the sibling data file ``_ca_bundle.der`` (concatenated DER, the
format ``mbedtls_x509_crt_parse`` walks natively and the lowest common
denominator across MP ports). It is read into a short-lived buffer rather than a
module constant so the GC can reclaim it before the socket and handshake working
set allocates. Consulted only on MicroPython; CircuitPython uses its firmware
bundle and CPython the OS trust store. Override at runtime via
:func:`chumicro_sockets.set_default_ca_bundle`.
"""

__chumicro_runtimes__ = ("micropython",)

# Sibling data file this module opens at runtime. The deploy import-walker reads
# this marker (it cannot see the runtime ``open``) and stages the file alongside.
__chumicro_data_files__ = ("_ca_bundle.der",)

# Fallback flash-deploy location, used only when ``__file__`` is unavailable.
_FALLBACK_PATH = "/lib/chumicro_sockets/_ca_bundle.der"


def read_der():
    """Return the shipped bundle's concatenated DER bytes.

    The caller keeps no reference, so the buffer is collectable as soon as
    ``load_verify_locations`` copies it into mbedTLS (the short lifetime is why
    the bundle ships as a file, not a module constant).
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
