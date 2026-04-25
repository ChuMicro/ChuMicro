"""Discover the TOML config-section templates each library ships.

Per Decision 0036 §5, every consumer library ships a starter TOML
snippet at::

    chumicro_<name>/_templates/config.toml

Workspace tooling collects these snippets when a user adds a
library to a thing — assembling a starter ``config.toml`` the user
fills in.

CPython-only behavior: ``importlib.resources`` doesn't exist on
MicroPython or CircuitPython, so calling :func:`get_section_template`
on device raises ``RuntimeError``.  The module itself imports
cleanly on device (the bundle deploy ships every ``.py`` under the
package, which is why this matters) — the ``importlib.resources``
import is deferred inside the function so a device that bundles the
file but never calls the function pays nothing.
"""

from chumicro_config.section import ConfigError


class MissingTemplateError(ConfigError):
    """The named library doesn't ship a ``_templates/config.toml``.

    Either the library isn't installed, or it doesn't consume runtime
    config (and so doesn't need a template).  Workspace tooling that
    walks installed libraries should treat this as "skip this one"
    rather than as a hard error.
    """


def get_section_template(library_name: str) -> str:
    """Return the TOML snippet a library ships for its config section.

    Args:
        library_name: Library basename without the ``chumicro-``
            prefix, e.g. ``"wifi"``.  Maps to package
            ``chumicro_<library_name>``.

    Returns:
        The contents of the library's ``_templates/config.toml``.

    Raises:
        MissingTemplateError: Library isn't installed or doesn't ship
            a template.
    """
    # importlib.resources is CPython-only; defer the import so the
    # module loads cleanly on devices that ship this file but never
    # call the function.
    try:
        from importlib.resources import files
    except ImportError as error:  # pragma: no cover - device-only path
        raise RuntimeError(
            "get_section_template requires importlib.resources (CPython); "
            "template collection is workspace-tooling, not device runtime."
        ) from error

    package = f"chumicro_{library_name}"
    try:
        template_resource = files(package) / "_templates" / "config.toml"
    except ModuleNotFoundError as error:
        raise MissingTemplateError(
            f"library {library_name!r} (package {package!r}) is not installed"
        ) from error
    if not template_resource.is_file():
        raise MissingTemplateError(
            f"library {library_name!r} does not ship a _templates/config.toml"
        )
    return template_resource.read_text()
