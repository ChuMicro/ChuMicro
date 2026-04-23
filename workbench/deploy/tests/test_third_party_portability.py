"""End-to-end portability test for a standalone non-chumicro template.

Drives the ``tests/fixtures/third_party_template/`` fixture through
chumicro-deploy's public API only — no ``libraries/``, ``support/``,
or ``scripts/`` imports.  Proves Slice 1a–1f ship a public surface
third parties can actually build on.

If chumicro ever grows a hidden coupling that leaks mono-repo
internals into the public API (``chumicro_deploy`` alone no longer
suffices for a real template), this test fails and the fixture is
the proof.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from chumicro_deploy import (
    Deployer,
    DeployResult,
    Device,
    FakeTransport,
    FileSource,
)

#: Template root — deliberately reached via a relative path under
#: the test file rather than any chumicro discovery helper.  A real
#: third party would ``pip install`` their template separately.
_TEMPLATE_ROOT = Path(__file__).parent / "fixtures" / "third_party_template"


@pytest.fixture
def _import_template(monkeypatch: pytest.MonkeyPatch):
    """Make the fixture's ``my_template`` package importable.

    Appends the template root to sys.path for the duration of the
    test.  A real third-party package would be importable after
    ``pip install .`` from the template directory; this test-only
    shortcut lets us skip the install step.
    """
    monkeypatch.syspath_prepend(str(_TEMPLATE_ROOT))
    yield
    # monkeypatch undoes syspath on teardown.


class TestThirdPartyPortability:
    def test_custom_file_source_satisfies_protocol(self, _import_template) -> None:
        from my_template import CustomLayoutFileSource

        source = CustomLayoutFileSource(_TEMPLATE_ROOT)
        # Duck-typed check — custom class was not declared to inherit
        # from FileSource.  runtime_checkable Protocol confirms the
        # .files() / .entrypoint() shape is enough.
        assert isinstance(source, FileSource)

    def test_files_and_entrypoint_match_manifest(
        self, _import_template,
    ) -> None:
        from my_template import CustomLayoutFileSource

        source = CustomLayoutFileSource(_TEMPLATE_ROOT)
        files = source.files()
        assert set(files.keys()) == {"/code.py", "/lib/greeter.py"}
        assert b"from greeter import greet" in files["/code.py"]
        assert b"hello," in files["/lib/greeter.py"]
        assert source.entrypoint() == "/code.py"

    def test_deploy_via_fake_transport_end_to_end(
        self, _import_template,
    ) -> None:
        from my_template import CustomLayoutFileSource

        fake = FakeTransport(execute_output="hello, third-party\n")

        class _DeviceWithFake(Device):
            def create_transport(self):  # type: ignore[override]
                return fake

        device = _DeviceWithFake(
            transport="micropython", address="/dev/third-party",
        )
        deployer = Deployer(device)
        source = CustomLayoutFileSource(_TEMPLATE_ROOT)

        result = deployer.deploy(source)
        assert isinstance(result, DeployResult)
        assert result.success is True
        assert result.execute_output == "hello, third-party\n"
        assert result.staged_files == ["/code.py", "/lib/greeter.py"]

        # Inspect what the transport actually received — the custom
        # layout's files landed at the correct on-device paths.
        deploy_call = next(
            call for call in fake.calls if call[0] == "deploy_files"
        )
        files_arg, entrypoint_arg = deploy_call[1]
        assert entrypoint_arg == "/code.py"
        assert "/code.py" in files_arg
        assert "/lib/greeter.py" in files_arg

    def test_public_api_alone_is_sufficient(self, _import_template) -> None:
        """The fixture touches only chumicro_deploy — never mono-repo paths.

        Walks sys.modules after the imports above and asserts nothing
        from ``chumicro.`` mono-repo namespaces like
        ``chumicro_timing`` or ``chumicro_test_harness`` got pulled
        in.  Those would indicate a hidden coupling the public API
        should not require.
        """
        from my_template import CustomLayoutFileSource  # noqa: F401

        # Drop the fixture package from module namespace inspection —
        # it only touches chumicro_deploy and stdlib.
        leaked = [
            module_name for module_name in sys.modules
            if module_name.startswith(
                ("chumicro_timing", "chumicro_runner", "chumicro_test_harness")
            )
        ]
        assert leaked == [], f"Mono-repo modules leaked into fixture: {leaked}"
