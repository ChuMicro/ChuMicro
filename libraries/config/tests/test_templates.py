"""CPython-only tests for ``chumicro_config.templates``.

The templates helper uses ``importlib.resources`` which doesn't
exist on MicroPython / CircuitPython; the module is host-side
workspace-tooling only and never imported on device.

Tests run only under CPython.  The cross-runtime harness collects
nothing from this file because the module-level import guard
short-circuits before any test functions are defined.
"""

import sys

_IS_CPYTHON = sys.implementation.name == "cpython"

if _IS_CPYTHON:
    import textwrap

    from chumicro_config.templates import (
        MissingTemplateError,
        get_section_template,
    )
    from chumicro_test_harness import raises

    def test_missing_library_raises_clear_error() -> None:
        """An uninstalled library name surfaces ``MissingTemplateError``."""
        with raises(MissingTemplateError):
            get_section_template("definitely_not_a_real_chumicro_library")

    def test_installed_library_without_template_raises_clear_error(
        tmp_path, monkeypatch,
    ) -> None:
        """A library that doesn't ship a template still raises cleanly.

        Stages a synthetic installable package with no
        ``_templates/config.toml`` so the assertion never depends on
        which real chumicro libraries happen to ship templates today.
        """
        fake_root = tmp_path / "fake_pkg_root"
        fake_pkg = fake_root / "chumicro_no_template"
        fake_pkg.mkdir(parents=True)
        (fake_pkg / "__init__.py").write_text("")

        monkeypatch.syspath_prepend(str(fake_root))
        monkeypatch.setitem(sys.modules, "chumicro_no_template", None)
        sys.modules.pop("chumicro_no_template", None)

        with raises(MissingTemplateError):
            get_section_template("no_template")

    def test_template_text_round_trips_when_present(tmp_path, monkeypatch) -> None:
        """A real template file under ``_templates/config.toml`` is returned verbatim.

        Stages a fake package on the fly so the helper has something
        to read against.  This is the success path that
        ``chumicro-wifi`` (Phase 3a Slice 0) will exercise once it
        ships its real template.
        """
        fake_root = tmp_path / "fake_pkg_root"
        fake_pkg = fake_root / "chumicro_fakelib"
        fake_pkg.mkdir(parents=True)
        (fake_pkg / "__init__.py").write_text("")
        (fake_pkg / "_templates").mkdir()
        template_text = textwrap.dedent(
            """
            # Fake-library configuration template.
            [fakelib]
            api_key = ""                   # required: account API key
            # endpoint = "https://api"     # optional: override endpoint
            """
        ).strip()
        (fake_pkg / "_templates" / "config.toml").write_text(template_text)

        # Inject the fake-package root onto sys.path so importlib.resources
        # can find it.  Cleanup happens via monkeypatch.
        monkeypatch.syspath_prepend(str(fake_root))
        # Make sure we don't pick up a cached import of the fake module
        # from a previous test invocation.
        monkeypatch.setitem(sys.modules, "chumicro_fakelib", None)
        sys.modules.pop("chumicro_fakelib", None)

        result = get_section_template("fakelib")
        assert result == template_text

    def test_missing_template_subclasses_config_error() -> None:
        """``MissingTemplateError`` is in the ``ConfigError`` hierarchy."""
        from chumicro_config import ConfigError
        with raises(ConfigError):
            get_section_template("definitely_not_a_real_chumicro_library")
