__chumicro_runtimes__ = ("micropython",)

# The deploy import-walker reads this marker to stage the file (it cannot see the
# runtime open()).
__chumicro_data_files__ = ("_ca_bundle.der",)

_FALLBACK_PATH = "/lib/chumicro_sockets/_ca_bundle.der"


def read_der():
    """Return the shipped bundle's concatenated DER bytes."""
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
