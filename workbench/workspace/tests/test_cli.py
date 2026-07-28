"""Tests for the chumicro-workspace CLI dispatcher.

Covers command parsing, dispatch routing, and the subcommand handlers
via mocked underlying APIs.
"""

import argparse
import sys
from pathlib import Path
from typing import Any

import pytest
from chumicro_deploy import (
    Device,
    FlashFirmwareError,
    MicropythonTransportError,
)
from chumicro_deploy.protocol import TransportProtocol
from chumicro_deploy.testing import FakeTransport
from chumicro_workspace import cli
from chumicro_workspace.cli import examples as cli_examples
from chumicro_workspace.testing import (
    FakePort,
    FakeSubprocessRunner,
    fake_probe_info,
    seed_project,
    seed_workspace,
)
from msgpack import unpackb


def _install_fake_transport(
    monkeypatch: pytest.MonkeyPatch,
    transport: TransportProtocol | None = None,
    *,
    factory: Any = None,
) -> None:
    """Route every ``Device.create_transport()`` to a test fake.

    Workspace tests drive ``cli.main([...])`` end-to-end, so they
    don't own ``Device`` construction — ``_resolve_device`` builds it
    from ``devices.yml`` deep inside the dispatch flow.  Install a
    process-wide hook on :meth:`Device.create_transport` so every
    constructed ``Device`` yields the supplied fake when its transport
    is built.  Reverts after the test via ``monkeypatch``.

    Pass either *transport* (one fake for every device) or *factory*
    (a callable ``factory(device) -> transport`` — for multi-device
    deploys and recording closures).
    """
    if (transport is None) == (factory is None):
        raise TypeError(
            "_install_fake_transport requires exactly one of "
            "*transport* or *factory*",
        )
    if factory is None:
        captured = transport
        factory = lambda _device: captured  # noqa: E731
    monkeypatch.setattr(Device, "create_transport", factory)


# ---------------------------------------------------------------------------
# Parser construction — every command registers
# ---------------------------------------------------------------------------


class TestParser:
    """Each documented command must register on the top-level parser."""

    EXPECTED_COMMANDS = (
        "setup", "update", "new", "add-device", "probe",
        "discover", "devices", "deploy", "projects", "status", "doctor",
        "demo", "bootstrap", "test", "repl",
        "rename", "install-firmware", "upgrade-firmware",
        "reset-board", "config-validate", "dump-config",
    )

    def test_all_commands_register(self) -> None:
        parser = cli.build_parser()
        subparsers_action = next(
            action for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        registered = set(subparsers_action.choices)
        missing = set(self.EXPECTED_COMMANDS) - registered
        assert not missing, f"missing CLI commands: {sorted(missing)}"

    def test_top_level_help_does_not_crash(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        with pytest.raises(SystemExit) as caught:
            cli.main(["--help"])
        assert caught.value.code == 0
        captured = capsys.readouterr()
        assert "deploy" in captured.out
        assert "probe" in captured.out


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------


class TestSetup:
    def test_no_pyproject_is_a_no_op(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        seed_workspace(tmp_path)
        exit_code = cli.main(["setup", "--workspace-dir", str(tmp_path)])
        assert exit_code == 0
        assert "skipping editable install" in capsys.readouterr().out

    def test_runs_pip_install_when_pyproject_present(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = seed_workspace(tmp_path)
        (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n")

        runner = FakeSubprocessRunner()
        exit_code = cli.main(
            ["setup", "--workspace-dir", str(root)],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 0
        # No `dev` extra declared → bare editable install.
        assert [call.args for call in runner.calls] == [
            [sys.executable, "-m", "pip", "install", "-e", str(root)],
        ]

    def test_installs_dev_extra_when_pyproject_declares_it(
        self,
        tmp_path: Path,
    ) -> None:
        """A workspace whose pyproject carries a ``[dev]`` extra must be
        installed as ``.[dev]`` so ``lint`` / ``test`` get ruff /
        chumicro-checks / pytest — otherwise the very tools those
        commands shell out to are absent."""
        root = seed_workspace(tmp_path)
        (root / "pyproject.toml").write_text(
            "[project]\n"
            "name = 'demo'\n"
            "dependencies = []\n"
            "\n"
            "[project.optional-dependencies]\n"
            'dev = ["pytest", "ruff", "chumicro-checks"]\n',
        )

        runner = FakeSubprocessRunner()
        exit_code = cli.main(
            ["setup", "--workspace-dir", str(root)],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 0
        assert [call.args for call in runner.calls] == [
            [sys.executable, "-m", "pip", "install", "-e", f"{root}[dev]"],
        ]

    def test_setup_succeeds_without_existing_workspace_yml(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Setup must work on a fresh-clone workspace where ``workspace.yml``
        does not exist yet.  Regression test for the chicken-and-egg
        bug where ``_cmd_setup`` called ``_resolve_workspace`` (which
        walks up looking for the ``workspace.yml`` marker and raises
        when absent) before the materializer could create the marker.

        The fix resolves the workspace root from ``--workspace-dir`` /
        ``cwd`` directly for the setup command, bypassing the
        marker-required walk-up.  Every other command keeps the
        marker-based discovery so they still work from any
        subdirectory inside an already-set-up workspace.
        """
        # Empty tmp_path — no workspace.yml, no devices.yml, no pyproject.
        exit_code = cli.main(["setup", "--workspace-dir", str(tmp_path)])
        assert exit_code == 0
        # Workspace templates must materialize even when no
        # workspace.yml existed at start.
        assert (tmp_path / "workspace.yml").is_file()
        assert (tmp_path / "devices.yml").is_file()
        captured = capsys.readouterr().out
        assert "materialized 3 workspace template(s)" in captured
        assert (tmp_path / "secrets.toml").is_file()


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdateCommand:
    def test_dispatches_to_template_apply_update(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from chumicro_workspace import template_apply

        recorded: dict[str, object] = {}

        def fake_update(
            target: Path, *, template_url: str, git_reference: str | None,
        ) -> Any:
            recorded["target"] = target
            recorded["url"] = template_url
            recorded["git_reference"] = git_reference
            return template_apply.ApplyReport()

        monkeypatch.setattr(template_apply, "update", fake_update)
        root = seed_workspace(tmp_path)
        exit_code = cli.main([
            "update", "--workspace-dir", str(root),
            "--from", "https://example.com/fork",
            "--ref", "v1.2.3",
        ])
        assert exit_code == 0
        assert recorded["target"] == root
        assert recorded["url"] == "https://example.com/fork"
        assert recorded["git_reference"] == "v1.2.3"


class TestNew:
    def test_copies_template_to_named_dir(self, tmp_path: Path) -> None:
        root = seed_workspace(tmp_path)
        template = root / "projects" / "_template"
        template.mkdir(parents=True)
        (template / "code.py").write_text("# template\n")
        (template / "project_config.toml").write_text("[app]\n")

        exit_code = cli.main(
            ["new", "--workspace-dir", str(root), "kitchen_sensor"],
        )
        assert exit_code == 0

        target = root / "projects" / "kitchen_sensor"
        assert (target / "code.py").read_text() == "# template\n"
        assert (target / "project_config.toml").read_text() == "[app]\n"

    def test_missing_template_raises(self, tmp_path: Path) -> None:
        root = seed_workspace(tmp_path)
        with pytest.raises(SystemExit) as caught:
            cli.main(["new", "--workspace-dir", str(root), "anything"])
        assert "template" in str(caught.value)

    def test_existing_target_raises(self, tmp_path: Path) -> None:
        root = seed_workspace(tmp_path)
        template = root / "projects" / "_template"
        template.mkdir(parents=True)
        (template / "code.py").write_text("\n")
        (root / "projects" / "exists").mkdir()
        with pytest.raises(SystemExit) as caught:
            cli.main(["new", "--workspace-dir", str(root), "exists"])
        assert "already exists" in str(caught.value)

    @pytest.mark.parametrize(
        ("bad_name", "match"),
        [
            # Single-segment violations.
            ("kitchen-sensor", "valid Python identifier"),
            ("1sensor", "valid Python identifier"),
            ("kitchen sensor", "valid Python identifier"),
            ("_template", "leading"),
            ("_private", "leading"),
            ("class", "keyword"),
            ("import", "keyword"),
            # Per-segment violations on slash/dotted paths.
            ("upstairs/kitchen-sensor", "valid Python identifier"),
            ("garage/_private", "leading"),
            ("garage/sensors/class", "keyword"),
            ("kitchen..sensor", "empty path segment"),
            ("garage//door_open", "empty path segment"),
        ],
    )
    def test_rejects_invalid_project_names(
        self,
        tmp_path: Path,
        bad_name: str,
        match: str,
    ) -> None:
        # Validation runs before the template lookup, so we deliberately
        # don't pre-create projects/_template — that lets us verify the
        # filesystem is untouched on rejection.
        root = seed_workspace(tmp_path)
        with pytest.raises(SystemExit) as caught:
            cli.main(["new", "--workspace-dir", str(root), bad_name])
        assert match in str(caught.value)
        assert not (root / "projects").exists()

    @pytest.mark.parametrize(
        "good_name",
        [
            "upstairs/bedroom_sensor",
            "garage/sensors/door_open",
            "upstairs.bedroom_sensor",
        ],
    )
    def test_accepts_nested_path_segments(
        self,
        tmp_path: Path,
        good_name: str,
    ) -> None:
        """Slash- and dotted-form paths pass validation when each segment is valid.

        Validation alone — ``_cmd_new`` still requires the template to
        exist, so we only assert the validator doesn't bail before the
        template lookup raises its own (more specific) ``SystemExit``.
        """
        root = seed_workspace(tmp_path)
        with pytest.raises(SystemExit) as caught:
            cli.main(["new", "--workspace-dir", str(root), good_name])
        # Past validation → template-missing message, not identifier message.
        message = str(caught.value)
        assert "valid Python identifier" not in message
        assert "leading" not in message

    def test_rejects_empty_project_name(self, tmp_path: Path) -> None:
        root = seed_workspace(tmp_path)
        with pytest.raises(SystemExit) as caught:
            cli.main(["new", "--workspace-dir", str(root), ""])
        assert "empty" in str(caught.value)


class TestNewNested:
    """`new` accepts nested paths and auto-creates namespaces."""

    def _seed_template(self, root: Path) -> Path:
        template = root / "projects" / "_template"
        template.mkdir(parents=True)
        (template / "code.py").write_text("# template\n")
        (template / "project_config.toml").write_text("[app]\n")
        return template

    def test_creates_nested_project_with_intermediate_dirs(
        self, tmp_path: Path,
    ) -> None:
        root = seed_workspace(tmp_path)
        self._seed_template(root)

        exit_code = cli.main([
            "new", "--workspace-dir", str(root),
            "garage/sensors/door_open",
        ])
        assert exit_code == 0

        target = root / "projects" / "garage" / "sensors" / "door_open"
        assert (target / "code.py").read_text() == "# template\n"
        assert (target / "project_config.toml").read_text() == "[app]\n"

    def test_emits_namespace_inits_at_each_level(
        self, tmp_path: Path,
    ) -> None:
        """Auto-created namespace dirs get empty ``__init__.py`` markers.

        Lets host-side tests do ``from projects.garage.sensors.door_open.app
        import run`` without PEP 420 namespace-package surprises.
        """
        root = seed_workspace(tmp_path)
        self._seed_template(root)

        exit_code = cli.main([
            "new", "--workspace-dir", str(root),
            "garage/sensors/door_open",
        ])
        assert exit_code == 0

        assert (root / "projects" / "garage" / "__init__.py").is_file()
        assert (
            root / "projects" / "garage" / "sensors" / "__init__.py"
        ).is_file()
        # The leaf is the project dir itself; no synthetic __init__.py
        # written inside the project — that's the template's territory.

    def test_dotted_form_creates_same_layout_as_slash_form(
        self, tmp_path: Path,
    ) -> None:
        root = seed_workspace(tmp_path)
        self._seed_template(root)

        exit_code = cli.main([
            "new", "--workspace-dir", str(root),
            "garage.sensors.door_open",
        ])
        assert exit_code == 0
        # Dotted form normalizes to the slash-form filesystem layout.
        assert (
            root / "projects" / "garage" / "sensors" / "door_open" / "code.py"
        ).is_file()

    def test_existing_intermediate_namespace_reused(
        self, tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A pre-existing ``projects/garage/`` is left in place."""
        root = seed_workspace(tmp_path)
        self._seed_template(root)
        # Pre-create the namespace (e.g. user previously created
        # garage/heater) — the second `new garage/door_open` reuses it.
        (root / "projects" / "garage").mkdir(parents=True)
        (root / "projects" / "garage" / "__init__.py").write_text("")
        (root / "projects" / "garage" / "marker.txt").write_text("preserved\n")

        exit_code = cli.main([
            "new", "--workspace-dir", str(root), "garage/door_open",
        ])
        assert exit_code == 0
        # Old namespace marker survives; new project exists alongside.
        assert (root / "projects" / "garage" / "marker.txt").read_text() == (
            "preserved\n"
        )
        assert (
            root / "projects" / "garage" / "door_open" / "code.py"
        ).is_file()
        out = capsys.readouterr().out
        # Existing namespace dir didn't trigger a creation trace.
        assert "creating namespace projects/garage/" not in out

    def test_creating_new_namespace_traces(
        self, tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        self._seed_template(root)

        cli.main([
            "new", "--workspace-dir", str(root),
            "upstairs/bedroom_sensor",
        ])
        out = capsys.readouterr().out
        assert "creating namespace projects/upstairs/" in out


class TestNewLibrary:
    """`new --library <name>` scaffolds a chumicro-style library."""

    def test_default_target_is_workspace_libraries_dir(
        self, tmp_path: Path,
    ) -> None:
        root = seed_workspace(tmp_path)
        exit_code = cli.main([
            "new", "--workspace-dir", str(root),
            "--library", "gpio",
        ])
        assert exit_code == 0
        library_dir = root / "libraries" / "gpio"
        assert library_dir.is_dir()
        # Downstream `new --library` is neutral: no chumicro- prefix.
        assert (library_dir / "src" / "gpio" / "__init__.py").is_file()
        assert (library_dir / "VERSION").read_text() == "0.1.0\n"

    def test_into_overrides_target(
        self, tmp_path: Path,
    ) -> None:
        root = seed_workspace(tmp_path)
        custom_target = tmp_path / "elsewhere"
        exit_code = cli.main([
            "new", "--workspace-dir", str(root),
            "--library", "gpio", "--into", str(custom_target),
        ])
        assert exit_code == 0
        assert (custom_target / "gpio" / "VERSION").is_file()
        assert not (root / "libraries").exists()

    def test_existing_target_returns_systemexit(
        self, tmp_path: Path,
    ) -> None:
        root = seed_workspace(tmp_path)
        # First call succeeds.
        cli.main([
            "new", "--workspace-dir", str(root),
            "--library", "gpio",
        ])
        # Second call collides.
        with pytest.raises(SystemExit) as caught:
            cli.main([
                "new", "--workspace-dir", str(root),
                "--library", "gpio",
            ])
        assert "gpio" in str(caught.value)

    def test_library_with_from_is_mutually_exclusive(
        self, tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        exit_code = cli.main([
            "new", "--workspace-dir", str(root),
            "--library", "gpio", "--from", "examples/wifi_only",
        ])
        assert exit_code == 2
        captured_stderr = capsys.readouterr().err
        assert "mutually exclusive" in captured_stderr


class TestNewFromFlag:
    """`new --from <example-path>` copies an alternate source."""

    def _seed_workspace_with_example(self, tmp_path: Path) -> Path:
        root = seed_workspace(tmp_path)
        # Seed a fake examples/ tree.
        example_root = root / "examples" / "two_projects" / "server"
        example_root.mkdir(parents=True)
        (example_root / "app.py").write_text(
            "def run():\n    print('server')\n",
        )
        (example_root / "project_config.toml").write_text("[server]\n")
        (example_root / "README.md").write_text("# example server\n")
        return root

    def test_copies_example_into_target(self, tmp_path: Path) -> None:
        root = self._seed_workspace_with_example(tmp_path)

        exit_code = cli.main([
            "new", "--workspace-dir", str(root),
            "garage/heater",
            "--from", "examples/two_projects/server",
        ])
        assert exit_code == 0

        target = root / "projects" / "garage" / "heater"
        assert (target / "app.py").read_text().startswith("def run")
        assert (target / "project_config.toml").read_text() == "[server]\n"
        assert (target / "README.md").read_text() == "# example server\n"

    def test_rejects_source_without_entry_point(
        self, tmp_path: Path,
    ) -> None:
        root = seed_workspace(tmp_path)
        # Make a directory that's not a project — README only.
        notes_dir = root / "examples" / "design_notes"
        notes_dir.mkdir(parents=True)
        (notes_dir / "wiring.md").write_text("\n")

        with pytest.raises(SystemExit) as caught:
            cli.main([
                "new", "--workspace-dir", str(root),
                "kitchen", "--from", "examples/design_notes",
            ])
        assert "no entry-point file" in str(caught.value)
        assert not (root / "projects" / "kitchen").exists()

    def test_rejects_missing_source_dir(self, tmp_path: Path) -> None:
        root = seed_workspace(tmp_path)
        with pytest.raises(SystemExit) as caught:
            cli.main([
                "new", "--workspace-dir", str(root),
                "kitchen", "--from", "nonexistent/source",
            ])
        assert "is not a directory" in str(caught.value)

    def test_rejects_source_outside_workspace(
        self, tmp_path: Path,
    ) -> None:
        """Defense against ``--from ../../etc/passwd``-style escapes."""
        root = seed_workspace(tmp_path)
        with pytest.raises(SystemExit) as caught:
            cli.main([
                "new", "--workspace-dir", str(root),
                "kitchen", "--from", "../outside",
            ])
        assert "outside" in str(caught.value)


# ---------------------------------------------------------------------------
# discover
# ---------------------------------------------------------------------------


class TestDiscover:
    def test_lists_ports(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from serial.tools import list_ports

        monkeypatch.setattr(
            list_ports,
            "comports",
            lambda: [FakePort("/dev/cu.b", "Board B"), FakePort("/dev/cu.a", "Board A")],
        )
        exit_code = cli.main(["discover"])
        assert exit_code == 0
        out = capsys.readouterr().out.splitlines()
        assert out == ["/dev/cu.a\tBoard A", "/dev/cu.b\tBoard B"]

    def test_no_ports_message(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from serial.tools import list_ports

        monkeypatch.setattr(list_ports, "comports", list)
        exit_code = cli.main(["discover"])
        assert exit_code == 0
        assert "no serial ports detected" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# devices
# ---------------------------------------------------------------------------


class TestDevices:
    def test_prints_entries(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        exit_code = cli.main(["devices", "--workspace-dir", str(root)])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "lolin-s2" in out
        assert "micropython" in out
        assert "/dev/cu.fake" in out

    def test_missing_devices_yml_message(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')
        exit_code = cli.main(["devices", "--workspace-dir", str(tmp_path)])
        assert exit_code == 0
        assert "does not exist yet" in capsys.readouterr().out

    def test_no_entries_message(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')
        (tmp_path / "devices.yml").write_text("devices: []\n")
        exit_code = cli.main(["devices", "--workspace-dir", str(tmp_path)])
        assert exit_code == 0
        assert "no entries" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# deploy
# ---------------------------------------------------------------------------


class TestDeploy:
    def test_ships_project_through_fake_transport(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = seed_workspace(tmp_path)
        seed_project(root)

        transport = FakeTransport(execute_output="")
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main(
            ["deploy", "--workspace-dir", str(root), "back-porch"],
        )
        assert exit_code == 0

        deploy_calls = [call for call in transport.calls if call[0] == "deploy_files"]
        assert len(deploy_calls) == 1
        files, entrypoint, _follow = deploy_calls[0][1]
        assert entrypoint == "/main.py"  # MP default per Device.effective_entrypoint
        decoded = unpackb(files["/runtime_config.msgpack"])
        assert decoded["wifi.password"] == "shh"

    def test_missing_project_raises(self, tmp_path: Path) -> None:
        root = seed_workspace(tmp_path)
        with pytest.raises(SystemExit) as caught:
            cli.main(["deploy", "--workspace-dir", str(root), "ghost"])
        assert "ghost" in str(caught.value)

    def test_empty_devices_yml_coaches_instead_of_tracebacks(
        self, tmp_path: Path,
    ) -> None:
        """An empty ``devices: []`` (the fresh-clone default) makes deploy
        exit with a coached add-device pointer that quotes
        ``load_devices_yml``'s "No devices configured" reason, rather than
        letting that ``ValueError`` reach the user as a raw traceback.
        """
        root = seed_workspace(tmp_path)
        seed_project(root)
        (root / "devices.yml").write_text("devices: []\n")
        with pytest.raises(SystemExit) as caught:
            cli.main([
                "deploy", "--workspace-dir", str(root),
                "--dry-run", "back-porch",
            ])
        message = str(caught.value)
        assert "No devices configured" in message
        assert "add-device" in message

    def test_traceback_returns_exit_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        seed_project(root)
        # FakeTransport returns whatever ``execute_output`` it's
        # carrying — supply a synthetic traceback so the deployer's
        # success heuristic flips to False.
        transport = FakeTransport(
            execute_output=(
                "Traceback (most recent call last):\n"
                "  File \"/code.py\", line 1\n"
                "RuntimeError: boom\n"
            ),
        )
        _install_fake_transport(monkeypatch, transport)
        exit_code = cli.main(
            ["deploy", "--workspace-dir", str(root), "back-porch"],
        )
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "RuntimeError: boom" in captured.err

    def test_explicit_entrypoint_override(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = seed_workspace(tmp_path)
        project_dir = seed_project(root)
        (project_dir / "boot.py").write_text("print('boot')\n")

        transport = FakeTransport(execute_output="")
        _install_fake_transport(monkeypatch, transport)

        cli.main([
            "deploy", "--workspace-dir", str(root),
            "--entrypoint", "/boot.py", "back-porch",
        ])
        deploy_calls = [call for call in transport.calls if call[0] == "deploy_files"]
        assert deploy_calls[0][1][1] == "/boot.py"

    def test_boot_shim_flag_uses_boot_pattern(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--boot-shim`` routes through project_boot_source.

        Verifies the simplified layout: synthesised shim at the
        runtime-matching path, project files at the device root,
        no ``active.py`` / ``workspace_runtime`` / ``lib/projects``.
        """
        root = seed_workspace(tmp_path)
        project_dir = root / "projects" / "back-porch"
        project_dir.mkdir(parents=True)
        (project_dir / "project_config.toml").write_text(
            "[wifi]\nssid = 'HomeNet'\n"
        )
        (project_dir / "app.py").write_text("def run(): print('hi')\n")

        transport = FakeTransport(execute_output="")
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "--boot-shim", "back-porch",
        ])
        assert exit_code == 0
        deploy_calls = [call for call in transport.calls if call[0] == "deploy_files"]
        files, entrypoint, _follow = deploy_calls[0][1]
        # Boot-shim layout: synthesised entrypoint at root, project at root.
        assert entrypoint == "/main.py"  # MP runtime in seed
        assert "/main.py" in files
        assert "/app.py" in files
        # Legacy multi-project artefacts must not appear.
        assert "/active.py" not in files
        assert not any(path.startswith("/lib/workspace_runtime/") for path in files)
        assert not any(path.startswith("/lib/projects/") for path in files)

    def test_boot_shim_and_import_graph_compose(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The two flags compose via project_boot_with_import_graph_source.

        Dry-run output proves the combined layout shipped: synthesised
        entrypoint shim, project files at the device root, AND a library
        the project imports from ``shared/`` at ``/lib/<name>.py``.
        """
        root = seed_workspace(tmp_path)
        # Library the project will import — must reach the device under /lib/.
        shared = root / "shared"
        shared.mkdir()
        (shared / "external_lib.py").write_text("def helper(): pass\n")
        project_dir = root / "projects" / "back-porch"
        project_dir.mkdir(parents=True)
        (project_dir / "project_config.toml").write_text("[wifi]\nssid = 'x'\n")
        (project_dir / "app.py").write_text(
            "import external_lib\ndef run(): pass\n",
        )

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "--boot-shim", "--import-graph", "back-porch",
            "--dry-run",
        ])
        assert exit_code == 0
        captured = capsys.readouterr().out
        # Layout label proves the new dispatch branch fired.
        assert "boot-shim+import-graph" in captured
        # Boot-shim layer present (seed defaults to MP, so /main.py
        # is the entrypoint shim).
        assert "/main.py" in captured
        assert "/app.py" in captured
        # Import-graph contribution present.
        assert "/lib/external_lib.py" in captured
        # Legacy multi-project artefacts must not appear.
        assert "/active.py" not in captured
        assert "workspace_runtime" not in captured
        assert "/lib/projects/" not in captured

    def test_shared_package_form_import_is_refused_with_hint(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A project importing ``shared.foo`` is refused with the bare-name fix.

        A ``shared/`` module is imported by its bare stem (``import foo``);
        the package form ``from shared.foo import bar`` resolves to no
        deployed file, so deploy refuses before sending bytes and appends
        the one-line fix instead of dumping a raw traceback.
        """
        root = seed_workspace(tmp_path)
        shared = root / "shared"
        shared.mkdir()
        (shared / "external_lib.py").write_text("def helper(): pass\n")
        project_dir = root / "projects" / "back-porch"
        project_dir.mkdir(parents=True)
        (project_dir / "project_config.toml").write_text("[wifi]\nssid = 'x'\n")
        (project_dir / "app.py").write_text(
            "from shared.external_lib import helper\ndef run(): pass\n",
        )

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "--boot-shim", "--import-graph", "back-porch",
            "--dry-run",
        ])
        assert exit_code == 2
        captured = capsys.readouterr().err
        assert "unresolved import" in captured.lower()
        assert "shared/ modules import by bare name" in captured

    def test_import_graph_flag_uses_ast_walker(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--import-graph routes through project_import_graph_source."""
        root = seed_workspace(tmp_path)
        # Stage a shared/ module alongside the project's main.py.
        shared = root / "shared"
        shared.mkdir()
        (shared / "imported_module.py").write_text("def helper(): pass\n")
        (shared / "unimported_module.py").write_text("# never reached\n")

        project_dir = root / "projects" / "back-porch"
        project_dir.mkdir(parents=True)
        (project_dir / "project_config.toml").write_text(
            "[wifi]\nssid = 'HomeNet'\n"
        )
        # MP runtime in seed → effective_entrypoint == 'main.py'.
        (project_dir / "main.py").write_text(
            "import imported_module\nprint('hi')\n"
        )

        transport = FakeTransport(execute_output="")
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "--import-graph", "back-porch",
        ])
        assert exit_code == 0
        deploy_calls = [call for call in transport.calls if call[0] == "deploy_files"]
        files, _entrypoint, _follow = deploy_calls[0][1]
        # AST walker shipped main.py + the imported helper, NOT the
        # unimported one.
        assert "/lib/imported_module.py" in files
        assert "/lib/unimported_module.py" not in files


class TestProjects:
    def test_lists_workspace_projects(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        seed_project(root, name="weather")
        seed_project(root, name="heater")
        exit_code = cli.main([
            "projects", "--workspace-dir", str(root), "--flat",
        ])
        assert exit_code == 0
        out = capsys.readouterr().out.splitlines()
        assert sorted(out) == ["heater", "weather"]

    def test_empty_workspace_prints_marker(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        # projects/ exists if any project was seeded; without seeding it doesn't.
        # Either way list_projects() returns [].
        exit_code = cli.main([
            "projects", "--workspace-dir", str(root), "--flat",
        ])
        assert exit_code == 0
        assert "no projects" in capsys.readouterr().out

    def test_skips_underscore_dirs(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """_template / leading-underscore dirs aren't shown as projects."""
        root = seed_workspace(tmp_path)
        seed_project(root, name="back-porch")
        (root / "projects" / "_template").mkdir()
        (root / "projects" / "_template" / "project_config.toml").write_text("\n")
        exit_code = cli.main([
            "projects", "--workspace-dir", str(root), "--flat",
        ])
        assert exit_code == 0
        out = capsys.readouterr().out.splitlines()
        assert "_template" not in out
        assert "back-porch" in out


class TestDeployAllDevices:
    """`deploy --all-devices` loops over devices.yml entries."""

    def _seed_two_device_workspace(self, tmp_path: Path) -> Path:
        """Seed a workspace with two registered devices."""
        (tmp_path / "workspace.yml").write_text("# machinery only\n")
        (tmp_path / "secrets.toml").write_text(
            '[wifi]\nhostname_prefix = "chu-"\npassword = "shh"\n',
        )
        (tmp_path / "devices.yml").write_text(
            "defaults:\n"
            "  micropython: lolin-s2\n"
            "devices:\n"
            "  - id: lolin-s2\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.fake-mp\n"
            "  - id: pico-w\n"
            "    runtime: circuitpython\n"
            "    address: /dev/cu.fake-cp\n",
        )
        return tmp_path

    def test_loops_over_each_device(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = self._seed_two_device_workspace(tmp_path)
        seed_project(root, name="back-porch")

        addresses_seen: list[str] = []

        def factory(device: Any) -> FakeTransport:
            addresses_seen.append(device.address)
            return FakeTransport(execute_output="")

        _install_fake_transport(monkeypatch, factory=factory)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "back-porch", "--all-devices",
        ])
        assert exit_code == 0
        # Each device was reached via its own create_transport call,
        # in devices.yml declaration order.
        assert addresses_seen == ["/dev/cu.fake-mp", "/dev/cu.fake-cp"]
        # Per-device header lines appear in stdout.
        out = capsys.readouterr().out
        assert "/dev/cu.fake-mp" in out
        assert "/dev/cu.fake-cp" in out

    def test_failure_continues_to_next_device(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """One bad device doesn't short-circuit the loop; exit code is 1."""
        root = self._seed_two_device_workspace(tmp_path)
        seed_project(root, name="back-porch")

        addresses_seen: list[str] = []

        def factory(self: Any) -> FakeTransport:
            addresses_seen.append(self.address)
            if self.address == "/dev/cu.fake-mp":
                return FakeTransport(
                    execute_output=(
                        "Traceback (most recent call last):\n"
                        "RuntimeError: bad-device\n"
                    ),
                )
            return FakeTransport(execute_output="")

        _install_fake_transport(monkeypatch, factory=factory)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "back-porch", "--all-devices",
        ])
        assert exit_code == 1
        # Both devices were tried.
        assert addresses_seen == ["/dev/cu.fake-mp", "/dev/cu.fake-cp"]

    def test_mutually_exclusive_with_device_id(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = self._seed_two_device_workspace(tmp_path)
        seed_project(root, name="back-porch")
        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "back-porch", "--all-devices", "--device", "lolin-s2",
        ])
        assert exit_code == 2
        assert "mutually exclusive" in capsys.readouterr().err

    def test_no_devices_registered_errors(self, tmp_path: Path) -> None:
        root = seed_workspace(tmp_path)
        # Overwrite the seeded devices.yml with an empty list.
        (root / "devices.yml").write_text("devices: []\n")
        seed_project(root, name="back-porch")
        with pytest.raises(SystemExit) as caught:
            cli.main([
                "deploy", "--workspace-dir", str(root),
                "back-porch", "--all-devices",
            ])
        assert "no devices" in str(caught.value)


class TestDeployTargetsMapping:
    """`deploy_targets:` per-project → per-device mapping."""

    def _seed_two_device_workspace(
        self, tmp_path: Path, deploy_targets_block: str = "",
    ) -> Path:
        """Workspace with two registered devices + optional deploy_targets."""
        workspace_yaml_body = "# machinery only\n"
        if deploy_targets_block:
            workspace_yaml_body += deploy_targets_block
        (tmp_path / "workspace.yml").write_text(workspace_yaml_body)
        (tmp_path / "secrets.toml").write_text(
            "[wifi]\nhostname_prefix = 'chu-'\npassword = 'shh'\n",
        )
        (tmp_path / "devices.yml").write_text(
            "defaults:\n"
            "  micropython: lolin-s2\n"
            "devices:\n"
            "  - id: lolin-s2\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.fake-mp\n"
            "  - id: pico-w\n"
            "    runtime: circuitpython\n"
            "    address: /dev/cu.fake-cp\n",
        )
        return tmp_path

    def test_single_project_picks_mapped_device(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`deploy <project>` (no --device) picks the project's mapped target."""
        root = self._seed_two_device_workspace(
            tmp_path,
            deploy_targets_block=(
                "deploy_targets:\n"
                "  back-porch: pico-w\n"
            ),
        )
        seed_project(root, name="back-porch")

        addresses_seen: list[str] = []

        def factory(device: Any) -> FakeTransport:
            addresses_seen.append(device.address)
            return FakeTransport(execute_output="")

        _install_fake_transport(monkeypatch, factory=factory)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root), "back-porch",
        ])
        assert exit_code == 0
        # Mapped device wins over devices.yml's "defaults.micropython".
        assert addresses_seen == ["/dev/cu.fake-cp"]

    def test_single_project_falls_back_when_unmapped(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A project not in deploy_targets still uses devices.yml defaults."""
        root = self._seed_two_device_workspace(
            tmp_path,
            deploy_targets_block=(
                "deploy_targets:\n"
                "  other-project: pico-w\n"
            ),
        )
        seed_project(root, name="back-porch")

        addresses_seen: list[str] = []
        _install_fake_transport(
            monkeypatch,
            factory=lambda device: (
                addresses_seen.append(device.address) or FakeTransport()
            ),
        )

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root), "back-porch",
        ])
        assert exit_code == 0
        # Falls back to devices.yml's defaults.micropython → lolin-s2.
        assert addresses_seen == ["/dev/cu.fake-mp"]

    def test_explicit_device_overrides_mapping(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`--device` always wins, even when deploy_targets has an entry."""
        root = self._seed_two_device_workspace(
            tmp_path,
            deploy_targets_block=(
                "deploy_targets:\n"
                "  back-porch: pico-w\n"
            ),
        )
        seed_project(root, name="back-porch")

        addresses_seen: list[str] = []
        _install_fake_transport(
            monkeypatch,
            factory=lambda device: (
                addresses_seen.append(device.address) or FakeTransport()
            ),
        )

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "back-porch", "--device", "lolin-s2",
        ])
        assert exit_code == 0
        # Explicit --device overrode the mapping.
        assert addresses_seen == ["/dev/cu.fake-mp"]

    def test_mapped_to_multiple_devices_loops(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A list-valued mapping deploys to every device in declaration order."""
        root = self._seed_two_device_workspace(
            tmp_path,
            deploy_targets_block=(
                "deploy_targets:\n"
                "  back-porch:\n"
                "    - pico-w\n"
                "    - lolin-s2\n"
            ),
        )
        seed_project(root, name="back-porch")

        addresses_seen: list[str] = []
        _install_fake_transport(
            monkeypatch,
            factory=lambda device: (
                addresses_seen.append(device.address) or FakeTransport()
            ),
        )

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root), "back-porch",
        ])
        assert exit_code == 0
        assert addresses_seen == ["/dev/cu.fake-cp", "/dev/cu.fake-mp"]

    def test_mapping_with_unknown_device_id_errors(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = self._seed_two_device_workspace(
            tmp_path,
            deploy_targets_block=(
                "deploy_targets:\n"
                "  back-porch: ghost-board\n"
            ),
        )
        seed_project(root, name="back-porch")
        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root), "back-porch",
        ])
        assert exit_code == 2
        captured_stderr = capsys.readouterr().err
        assert "deploy_targets" in captured_stderr
        assert "ghost-board" in captured_stderr


class TestDeployAllProjects:
    """`deploy --all-projects` walks the deploy_targets mapping."""

    def _seed_three_project_workspace(self, tmp_path: Path) -> Path:
        """Two devices, three projects, full deploy_targets coverage."""
        (tmp_path / "workspace.yml").write_text(
            "deploy_targets:\n"
            "  back-porch: pico-w\n"
            "  garage/door: lolin-s2\n"
            "  garage/window:\n"
            "    - lolin-s2\n"
            "    - pico-w\n",
        )
        (tmp_path / "secrets.toml").write_text(
            "[wifi]\nhostname_prefix = 'chu-'\npassword = 'shh'\n",
        )
        (tmp_path / "devices.yml").write_text(
            "defaults:\n"
            "  micropython: lolin-s2\n"
            "devices:\n"
            "  - id: lolin-s2\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.fake-mp\n"
            "  - id: pico-w\n"
            "    runtime: circuitpython\n"
            "    address: /dev/cu.fake-cp\n",
        )
        for name in ("back-porch", "garage/door", "garage/window"):
            seed_project(tmp_path, name=name)
        return tmp_path

    def test_walks_each_mapped_project(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = self._seed_three_project_workspace(tmp_path)

        deploy_calls: list[str] = []
        _install_fake_transport(
            monkeypatch,
            factory=lambda device: (
                deploy_calls.append(device.address) or FakeTransport()
            ),
        )

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root), "--all-projects",
        ])
        assert exit_code == 0
        # back-porch → pico-w; garage/door → lolin-s2;
        # garage/window → [lolin-s2, pico-w].
        assert deploy_calls == [
            "/dev/cu.fake-cp",
            "/dev/cu.fake-mp",
            "/dev/cu.fake-mp",
            "/dev/cu.fake-cp",
        ]
        out = capsys.readouterr().out
        # Per-project header lines fire when more than one project in flight.
        assert "=== back-porch ===" in out
        assert "=== garage/door ===" in out
        assert "=== garage/window ===" in out

    def test_mutually_exclusive_with_positional(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = self._seed_three_project_workspace(tmp_path)
        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "back-porch", "--all-projects",
        ])
        assert exit_code == 2
        assert "mutually exclusive" in capsys.readouterr().err

    def test_mutually_exclusive_with_all_devices(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = self._seed_three_project_workspace(tmp_path)
        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "--all-projects", "--all-devices",
        ])
        assert exit_code == 2
        assert "mutually exclusive" in capsys.readouterr().err

    def test_missing_deploy_targets_block_errors(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No deploy_targets at all → exit 2 with a hint."""
        root = seed_workspace(tmp_path)
        seed_project(root, name="back-porch")
        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root), "--all-projects",
        ])
        assert exit_code == 2
        captured_stderr = capsys.readouterr().err
        assert "deploy_targets" in captured_stderr
        assert "Map each project" in captured_stderr

    def test_unknown_project_in_mapping_errors(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A project in the mapping that doesn't exist on disk fails fast."""
        (tmp_path / "workspace.yml").write_text(
            "defaults:\n  wifi:\n    password: shh\n"
            "deploy_targets:\n"
            "  ghost-project: lolin-s2\n",
        )
        (tmp_path / "devices.yml").write_text(
            "defaults:\n  micropython: lolin-s2\n"
            "devices:\n"
            "  - id: lolin-s2\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.fake-mp\n",
        )
        exit_code = cli.main([
            "deploy", "--workspace-dir", str(tmp_path), "--all-projects",
        ])
        assert exit_code == 2
        captured_stderr = capsys.readouterr().err
        assert "unknown project" in captured_stderr
        assert "ghost-project" in captured_stderr

    def test_failure_continues_to_next_project(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """One bad deploy doesn't short-circuit the loop; exit code is 1."""
        root = self._seed_three_project_workspace(tmp_path)

        deploy_calls: list[str] = []

        def factory(self: Any) -> FakeTransport:
            deploy_calls.append(self.address)
            if self.address == "/dev/cu.fake-mp":
                return FakeTransport(
                    execute_output=(
                        "Traceback (most recent call last):\n"
                        "RuntimeError: bad-device\n"
                    ),
                )
            return FakeTransport(execute_output="")

        _install_fake_transport(monkeypatch, factory=factory)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root), "--all-projects",
        ])
        assert exit_code == 1
        # Every (project, device) pair was attempted despite the failures.
        assert deploy_calls == [
            "/dev/cu.fake-cp",
            "/dev/cu.fake-mp",
            "/dev/cu.fake-mp",
            "/dev/cu.fake-cp",
        ]


class TestDeployFailureHints:
    """Failed deploys carry app-level recovery hints to stderr."""

    def test_missing_config_key_traceback_prints_hint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A KeyError on a config section flags the missing key with workspace context."""
        root = seed_workspace(tmp_path)
        seed_project(root)
        transport = FakeTransport(
            execute_output=(
                "Traceback (most recent call last):\n"
                "  File \"/code.py\", ...\n"
                "KeyError: 'wifi_password'\n"
            ),
        )
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root), "back-porch",
        ])
        assert exit_code == 1
        captured_stderr = capsys.readouterr().err
        assert "--- hints ---" in captured_stderr
        assert "wifi_password" in captured_stderr
        assert "project_config.toml" in captured_stderr
        assert "secrets.toml" in captured_stderr

    def test_no_hints_section_when_no_pattern_matches(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Generic ZeroDivisionError carries no hint — no empty section."""
        root = seed_workspace(tmp_path)
        seed_project(root)
        transport = FakeTransport(
            execute_output=(
                "Traceback (most recent call last):\n"
                "  File \"/code.py\", line 1\n"
                "ZeroDivisionError: division by zero\n"
            ),
        )
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root), "back-porch",
        ])
        assert exit_code == 1
        captured_stderr = capsys.readouterr().err
        assert "--- hints ---" not in captured_stderr

    def test_deploy_tail_failure_skips_tail_and_hints(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """`deploy --tail` failures route through the hint pass, no tail.

        `deploy --tail` is the one deploy-then-watch path (the old
        `repl <project>` shortcut, retired).  A failed deploy must
        not fall through to tail and must surface the same coached
        hints any `deploy` failure does.
        """
        root = seed_workspace(tmp_path)
        project_dir = seed_project(root, name="back-porch")
        (project_dir / "app.py").write_text("def run(): pass\n")
        transport = FakeTransport(
            execute_output=(
                "Traceback (most recent call last):\n"
                "  ...\n"
                "ImportError: no module named 'chumicro_wifi'\n"
            ),
        )
        _install_fake_transport(monkeypatch, transport)

        # Tail must NOT be reached; stub it to ensure no call.
        import chumicro_repl
        monkeypatch.setattr(
            chumicro_repl,
            "tail",
            lambda *args, **kwargs: pytest.fail("tail called on failed deploy"),
        )

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root), "back-porch", "--tail",
        ])
        assert exit_code == 1
        captured_stderr = capsys.readouterr().err
        assert "--- hints ---" in captured_stderr
        assert "chumicro_wifi" in captured_stderr


class TestDeployDiffCleanup:
    """`python3 run.py deploy <project>` runs a scoped diff-deploy by default.

    The CLI routes through `Deployer.deploy_diff()` — the one stage
    primitive — so stale `/lib/*` from a previous deploy gets cleaned
    and a "removed stale" line surfaces in the CLI output for
    transparency.
    """

    def test_stale_files_are_deleted_and_logged(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        seed_project(root, name="back-porch")

        # Pre-populate the fake device's flash with a stale file the
        # new payload won't include — the diff routine should remove it.
        transport = FakeTransport(
            mode="copy",
            execute_output="",
            device_files={
                "/main.py": b"# previous main.py",
                "/lib/old_project.py": b"old-content",
            },
        )
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root), "back-porch",
        ])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "removed stale /lib/old_project.py" in out
        # Transport saw both the listing primitive + the delete primitive.
        labels = [call[0] for call in transport.calls]
        assert "list_files_in_scope" in labels
        assert "delete_files" in labels
        assert "deploy_files" in labels

    def test_no_stale_files_no_log_lines(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Empty stale set → no `removed stale` lines in CLI output."""
        root = seed_workspace(tmp_path)
        seed_project(root, name="back-porch")

        transport = FakeTransport(mode="copy", execute_output="")
        _install_fake_transport(monkeypatch, transport)

        cli.main(["deploy", "--workspace-dir", str(root), "back-porch"])
        out = capsys.readouterr().out
        assert "removed stale" not in out
        labels = [call[0] for call in transport.calls]
        # list call still happens (the diff routine queries first);
        # delete should NOT have fired since nothing was stale.
        assert "list_files_in_scope" in labels
        assert "delete_files" not in labels


class TestDeployWipeFlag:
    """`deploy --wipe` calls wipe_filesystem before staging the new payload."""

    def test_wipe_runs_and_clears_out_of_scope_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        seed_project(root, name="back-porch")

        transport = FakeTransport(
            mode="copy",
            execute_output="",
            device_files={
                "/main.py": b"# previous main.py",
                "/lib/old_project.py": b"old",
                "/settings.toml": b"WIFI = '...'",  # out of scope
                "/photo.jpg": b"<jpeg>",            # out of scope
            },
        )
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root), "back-porch", "--wipe",
        ])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "wiping filesystem" in out
        # No "removed stale" lines — wipe replaces the diff cleanup.
        assert "removed stale" not in out

        labels = [call[0] for call in transport.calls]
        assert "wipe_filesystem" in labels
        assert "deploy_files" in labels
        # Diff primitives skipped (the wipe makes them redundant).
        assert "list_files_in_scope" not in labels
        assert "delete_files" not in labels
        # Out-of-scope files are gone (the whole point of --wipe).
        assert "/settings.toml" not in transport.device_files
        assert "/photo.jpg" not in transport.device_files

    def test_dry_run_with_wipe_shows_wipe_line(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """`deploy --wipe --dry-run` surfaces the wipe in the dry-run summary."""
        root = seed_workspace(tmp_path)
        seed_project(root, name="back-porch")

        transport = FakeTransport(execute_output="")
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "back-porch", "--wipe", "--dry-run",
        ])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "would wipe filesystem before deploy" in out
        # Dry-run still doesn't touch the transport.
        assert not any(call[0] == "wipe_filesystem" for call in transport.calls)
        assert not any(call[0] == "deploy_files" for call in transport.calls)


class TestDeployModeFlags:
    """`--deploy-mode` / `--force-deploy-mode` override the device's mode per run."""

    def test_deploy_mode_overrides_device_but_preflight_still_applies(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """`--deploy-mode ram` starts the run in RAM mode; the staged
        config msgpack then triggers the documented auto-switch back to
        flash — proof the override reached pre-flight (a default flash
        run prints no switch message)."""
        root = seed_workspace(tmp_path)
        seed_project(root, name="back-porch")

        def build_fake(device: Any) -> FakeTransport:
            fake_mode = "mount" if device.deploy_mode == "ram" else "copy"
            return FakeTransport(mode=fake_mode, execute_output="")

        _install_fake_transport(monkeypatch, factory=build_fake)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root), "back-porch",
            "--deploy-mode", "ram",
        ])
        assert exit_code == 0
        assert "switching to flash mode" in capsys.readouterr().err

    def test_force_deploy_mode_also_sets_the_run_mode(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`--force-deploy-mode ram` sets the mode and bypasses pre-flight."""
        root = seed_workspace(tmp_path)
        seed_project(root, name="back-porch")

        seen_modes: list[str] = []

        def record_mode(device: Any) -> FakeTransport:
            seen_modes.append(device.deploy_mode)
            fake_mode = "mount" if device.deploy_mode == "ram" else "copy"
            return FakeTransport(mode=fake_mode, execute_output="")

        _install_fake_transport(monkeypatch, factory=record_mode)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root), "back-porch",
            "--force-deploy-mode", "ram",
        ])
        assert exit_code == 0
        assert seen_modes == ["ram"]

    def test_deploy_mode_and_force_are_mutually_exclusive(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Passing both flags is an argparse error, not a silent pick."""
        root = seed_workspace(tmp_path)
        seed_project(root, name="back-porch")

        with pytest.raises(SystemExit) as exit_info:
            cli.main([
                "deploy", "--workspace-dir", str(root), "back-porch",
                "--deploy-mode", "ram", "--force-deploy-mode", "flash",
            ])
        assert exit_info.value.code == 2
        assert "not allowed with" in capsys.readouterr().err


class TestDeployDryRun:
    """`deploy --dry-run` shows the file map without writing."""

    def test_does_not_call_transport(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        seed_project(root, name="back-porch")

        transport = FakeTransport(execute_output="")
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "back-porch", "--dry-run",
        ])
        assert exit_code == 0
        # Transport must NOT see deploy_files in dry-run mode.
        assert not any(call[0] == "deploy_files" for call in transport.calls)
        # Header + file table appear in stdout.
        out = capsys.readouterr().out
        assert "would deploy back-porch" in out
        assert "device files" in out

    def test_boot_shim_layout_classifies_paths(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Boot-shim dry-run shows shim + project files at the device root.

        Verifies the simplified layout: synthesised shim at the runtime-
        matching path, project files at root, no ``/lib/projects/<name>/``
        nesting.
        """
        root = seed_workspace(tmp_path)
        project_dir = root / "projects" / "back-porch"
        project_dir.mkdir(parents=True)
        (project_dir / "project_config.toml").write_text("[wifi]\nssid = 'x'\n")
        (project_dir / "app.py").write_text("def run(): pass\n")

        transport = FakeTransport(execute_output="")
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "--boot-shim", "back-porch", "--dry-run",
        ])
        assert exit_code == 0
        out = capsys.readouterr().out
        # Layout label flagged.
        assert "boot-shim layout" in out
        # Synthesised shim at runtime-matching path (seed defaults to MP).
        assert "/main.py" in out
        # Project's app.py at the device root (no /lib/projects/ prefix).
        assert "/app.py" in out
        # Categories appear.
        assert "shim" in out
        assert "config" in out
        # Legacy multi-project artefacts must not appear.
        assert "/active.py" not in out
        assert "workspace_runtime" not in out
        assert "/lib/projects/" not in out

    def test_flat_layout_skips_namespace_inits(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Flat layout (no --boot-shim) ships at the device root."""
        root = seed_workspace(tmp_path)
        seed_project(root, name="back-porch")

        transport = FakeTransport(execute_output="")
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "back-porch", "--dry-run",
        ])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "flat layout" in out
        # Flat layout puts code.py + main.py at the device root.
        assert "/code.py" in out or "/main.py" in out


class TestStatus:
    """`status` workspace health snapshot."""

    def test_prints_workspace_path_first(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        exit_code = cli.main(["status", "--workspace-dir", str(root)])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert out.startswith("WORKSPACE")
        assert str(root) in out

    def test_ok_findings_render_with_check_glyph(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        seed_project(root, name="back-porch")
        exit_code = cli.main(["status", "--workspace-dir", str(root)])
        assert exit_code == 0
        out = capsys.readouterr().out
        # All three labels appear; OK findings get the check glyph.
        for label in ("WORKSPACE.YML", "DEVICES.YML", "PROJECTS"):
            assert label in out
        assert "✓" in out

    def test_warn_finding_prints_hint_below(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A devices.yml warning (no devices registered) carries a remediation hint."""
        root = seed_workspace(tmp_path)
        # Overwrite the seeded devices.yml with an empty registry to trigger the warn.
        (root / "devices.yml").write_text("devices: []\n")
        exit_code = cli.main(["status", "--workspace-dir", str(root)])
        # A warning alone keeps exit 0 — only ERROR flips it.
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "⚠" in out
        assert "no devices" in out
        assert "hint:" in out
        assert "add-device" in out

    def test_error_finding_returns_exit_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A malformed workspace.yml is an error → exit 1."""
        # Seed a workspace.yml that parses but isn't a top-level mapping —
        # the loaders.WorkspaceConfigError path the check exercises.
        (tmp_path / "workspace.yml").write_text("[a, list]\n")
        exit_code = cli.main(["status", "--workspace-dir", str(tmp_path)])
        assert exit_code == 1
        out = capsys.readouterr().out
        assert "✗" in out
        assert "WORKSPACE.YML" in out


class TestDoctor:
    """`doctor` runs status's checks plus AST + config-merge."""

    @pytest.fixture(autouse=True)
    def _stub_fskit_detector(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Default the FSKit detector to False for every test in this class.

        Without this, a wedged dev machine running the suite would
        surface as a doctor ERROR finding and flip exit codes for
        tests that aren't trying to test FSKit at all.  Tests that do
        care about the FSKit branch live in
        :class:`TestDoctorFixFskitWedge` and stub the detector
        explicitly.
        """
        from chumicro_workspace import health
        monkeypatch.setattr(health, "detect_fskit_wedge", lambda: False)

    def test_includes_python_and_project_run_labels(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        project_dir = seed_project(root, name="back-porch")
        (project_dir / "app.py").write_text("def run(): pass\n")
        exit_code = cli.main(["doctor", "--workspace-dir", str(root)])
        assert exit_code == 0
        out = capsys.readouterr().out
        for label in (
            "PYTHON",
            "WORKSPACE.YML",
            "DEVICES.YML",
            "PROJECTS",
            "PROJECT run() defs",
            "MACOS FSKIT",
        ):
            assert label in out

    def test_missing_run_function_flips_exit_to_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        project_dir = seed_project(root, name="back-porch")
        (project_dir / "app.py").write_text(
            "def something_else(): pass\n",
        )
        exit_code = cli.main(["doctor", "--workspace-dir", str(root)])
        assert exit_code == 1
        out = capsys.readouterr().out
        assert "✗" in out
        assert "back-porch" in out

    def test_wedge_detected_flips_exit_to_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Override the autouse stub: a wedge during plain `doctor` (no
        # --fix flag) should surface as an ERROR finding, flip exit to
        # 1, and tell the user about --fix-fskit-wedge.
        from chumicro_workspace import health
        # The health check gates on sys.platform before consulting the
        # detector, so fake darwin too — the wedge logic under test is
        # host-independent (first live CI run failed here on Linux).
        monkeypatch.setattr(health.sys, "platform", "darwin")
        monkeypatch.setattr(health, "detect_fskit_wedge", lambda: True)
        root = seed_workspace(tmp_path)
        project_dir = seed_project(root, name="back-porch")
        (project_dir / "app.py").write_text("def run(): pass\n")
        exit_code = cli.main(["doctor", "--workspace-dir", str(root)])
        assert exit_code == 1
        out = capsys.readouterr().out
        assert "MACOS FSKIT" in out
        assert "wedged" in out
        assert "doctor --fix-fskit-wedge" in out


class TestDoctorFixFskitWedge:
    """`doctor --fix-fskit-wedge` is the opt-in sudo wrapper around
    `MACOS_FSKIT_RECOVERY_COMMAND`.  Refuse rules cover non-darwin /
    not-wedged / no-tty / no-sudo; happy path runs the killall and
    re-checks; persisting wedge after killall surfaces a reboot hint.
    """

    def _patch_environment(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        platform: str = "darwin",
        wedge_states: list[bool] | None = None,
        sudo_on_path: bool = True,
        stdin_tty: bool = True,
        stderr_tty: bool = True,
        run_returncode: int = 0,
    ) -> tuple[FakeSubprocessRunner, list[bool]]:
        """Stub everything the wrapper touches.

        Returns ``(subprocess_runner, detect_calls)`` so tests can
        assert the killall was invoked with the expected argv (via
        ``runner.calls[i].args``) and the detector was polled the
        expected number of times (refuse paths poll once; the happy
        path polls twice — pre + post killall).  Pass the returned
        runner to :func:`cli.main` via ``env=cli.CliEnv(subprocess_runner=...)``.
        """
        monkeypatch.setattr(cli.health.sys, "platform", platform)
        states = list(wedge_states) if wedge_states is not None else [False]
        detect_calls: list[bool] = []

        def fake_detect() -> bool:
            value = states.pop(0) if states else False
            detect_calls.append(value)
            return value

        monkeypatch.setattr(cli.health, "detect_fskit_wedge", fake_detect)
        monkeypatch.setattr(
            cli.health.shutil, "which",
            lambda name: "/usr/bin/sudo" if sudo_on_path else None,
        )
        # Patch isatty in place on whatever pytest has installed — it
        # may be the real terminal, capsys's CaptureFixture wrapper, or
        # a regular file.  Replacing the whole stream object breaks
        # pytest's stderr capture and the wrapper's print-to-stderr
        # error paths.
        monkeypatch.setattr(cli.health.sys.stdin, "isatty", lambda: stdin_tty)
        monkeypatch.setattr(cli.health.sys.stderr, "isatty", lambda: stderr_tty)

        # Skip the 2-second settle.
        monkeypatch.setattr(cli.health.time, "sleep", lambda _seconds: None)

        return FakeSubprocessRunner(returncode=run_returncode), detect_calls

    def test_refuses_on_non_darwin(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        runner, detect_calls = self._patch_environment(
            monkeypatch, platform="linux",
        )
        exit_code = cli.main(
            ["doctor", "--fix-fskit-wedge"],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 2
        assert runner.calls == []  # no killall on non-mac
        assert detect_calls == []  # detector never even queried
        assert "macOS-only" in capsys.readouterr().err

    def test_refuses_when_no_wedge_detected(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Wedge detector returns False — running the recovery on a
        # healthy system damages mounted volumes.
        runner, detect_calls = self._patch_environment(
            monkeypatch, wedge_states=[False],
        )
        exit_code = cli.main(
            ["doctor", "--fix-fskit-wedge"],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 3
        assert runner.calls == []
        assert detect_calls == [False]
        stderr_text = capsys.readouterr().err
        assert "No FSKit wedge detected" in stderr_text
        assert "physical replug" in stderr_text

    def test_refuses_when_stdin_not_tty(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        runner, _ = self._patch_environment(
            monkeypatch, wedge_states=[True], stdin_tty=False,
        )
        exit_code = cli.main(
            ["doctor", "--fix-fskit-wedge"],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 4
        assert runner.calls == []
        stderr_text = capsys.readouterr().err
        assert "non-interactive" in stderr_text
        # The paste fallback must surface the literal recovery
        # constant so the user can copy it into a Terminal tab.
        assert "sudo killall -9" in stderr_text

    def test_refuses_when_sudo_not_on_path(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        runner, _ = self._patch_environment(
            monkeypatch, wedge_states=[True], sudo_on_path=False,
        )
        exit_code = cli.main(
            ["doctor", "--fix-fskit-wedge"],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 5
        assert runner.calls == []
        assert "`sudo` is not on PATH" in capsys.readouterr().err

    def test_happy_path_runs_killall_and_clears(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Wedge detected first call (gate), cleared on second (post-killall).
        runner, detect_calls = self._patch_environment(
            monkeypatch, wedge_states=[True, False],
        )
        exit_code = cli.main(
            ["doctor", "--fix-fskit-wedge"],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 0
        # killall invoked with the literal constant's argv form.
        assert len(runner.calls) == 1
        assert runner.calls[0].args[0] == "sudo"
        assert runner.calls[0].args[1] == "killall"
        assert "diskarbitrationd" in runner.calls[0].args
        assert "DiskArbitrationAgent" in runner.calls[0].args
        assert detect_calls == [True, False]
        out = capsys.readouterr().out
        assert "FSKit wedge detected" in out
        assert "FSKit wedge cleared" in out

    def test_persists_after_killall_surfaces_reboot_hint(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Wedge stays True both before and after the killall.
        runner, detect_calls = self._patch_environment(
            monkeypatch, wedge_states=[True, True],
        )
        exit_code = cli.main(
            ["doctor", "--fix-fskit-wedge"],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 6
        assert len(runner.calls) == 1  # killall did run
        assert detect_calls == [True, True]
        stderr_text = capsys.readouterr().err
        assert "persists" in stderr_text
        assert "Reboot" in stderr_text

    def test_killall_failure_propagates_exit_code(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # subprocess.run returns 130 (sudo password cancel) — propagate
        # without claiming the wedge cleared.
        runner, detect_calls = self._patch_environment(
            monkeypatch, wedge_states=[True], run_returncode=130,
        )
        exit_code = cli.main(
            ["doctor", "--fix-fskit-wedge"],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 130
        assert len(runner.calls) == 1
        # Detector polled once (the gate).  Failed killall short-
        # circuits before the post-settle re-check.
        assert detect_calls == [True]
        assert "Recovery command failed" in capsys.readouterr().err


class TestProjectsTreeView:
    """`projects` defaults to a Unicode tree, `--flat` keeps the list."""

    def test_default_renders_tree_with_namespaces(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        seed_project(root, name="thermostat")
        seed_project(root, name="upstairs/bedroom_sensor")
        seed_project(root, name="upstairs/nightstand_lamp")
        seed_project(root, name="garage/sensors/door_open")

        exit_code = cli.main(["projects", "--workspace-dir", str(root)])
        assert exit_code == 0
        out = capsys.readouterr().out
        # Root marker.
        assert out.startswith("projects/\n")
        # Top-level alpha order: garage/, thermostat, upstairs/.
        assert "├── garage/" in out
        assert "├── thermostat" in out
        assert "└── upstairs/" in out
        # Namespace branches preserve nesting.
        assert "│   └── sensors/" in out or "    └── sensors/" in out
        assert "door_open" in out
        assert "bedroom_sensor" in out
        assert "nightstand_lamp" in out

    def test_flat_one_line_per_project(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        seed_project(root, name="thermostat")
        seed_project(root, name="upstairs/bedroom_sensor")
        seed_project(root, name="garage/sensors/door_open")
        exit_code = cli.main([
            "projects", "--workspace-dir", str(root), "--flat",
        ])
        assert exit_code == 0
        out_lines = [
            line for line in capsys.readouterr().out.splitlines() if line
        ]
        assert sorted(out_lines) == [
            "garage/sensors/door_open",
            "thermostat",
            "upstairs/bedroom_sensor",
        ]

    def test_default_on_empty_workspace_shows_marker(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        exit_code = cli.main(["projects", "--workspace-dir", str(root)])
        assert exit_code == 0
        assert "no projects" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# demo — built-in payload
# ---------------------------------------------------------------------------


class TestDemo:
    """Built-in `chumicro-workspace demo` payload deploy."""

    def test_ships_demo_payload_through_fake_transport(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = seed_workspace(tmp_path)

        transport = FakeTransport(execute_output="Hello from ChuMicro!\n")
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main(["demo", "--workspace-dir", str(root)])
        assert exit_code == 0

        deploy_calls = [
            call for call in transport.calls if call[0] == "deploy_files"
        ]
        assert len(deploy_calls) == 1
        files, entrypoint, _follow = deploy_calls[0][1]
        # MP runtime in the seed → /main.py.
        assert entrypoint == "/main.py"
        assert "/main.py" in files
        body = files["/main.py"].decode("utf-8")
        assert "Hello from ChuMicro" in body
        assert "demo complete" in body

    def test_prints_execute_output_to_user(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The captured execute output reaches stdout so the user
        sees the demo's prints."""
        root = seed_workspace(tmp_path)

        transport = FakeTransport(
            execute_output="Hello from ChuMicro!\ndemo complete!\n",
        )
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main(["demo", "--workspace-dir", str(root)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Hello from ChuMicro" in captured.out
        assert "demo complete" in captured.out

    def test_traceback_returns_exit_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Same failure-surfacing shape as `deploy`."""
        root = seed_workspace(tmp_path)

        transport = FakeTransport(
            execute_output=(
                "Traceback (most recent call last):\n"
                "  File \"/main.py\", line 1\n"
                "RuntimeError: boom\n"
            ),
        )
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main(["demo", "--workspace-dir", str(root)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "RuntimeError: boom" in captured.err

    def test_demo_payload_is_runtime_agnostic(self) -> None:
        """The baked-in payload uses no `board` / `machine` imports.

        Guards against a future regression where someone adds a
        hardware-touching line and the demo silently breaks on
        boards that don't expose the imported module.
        """
        from chumicro_workspace.cli.examples import DEMO_PAYLOAD

        assert "import board" not in DEMO_PAYLOAD
        assert "import machine" not in DEMO_PAYLOAD
        assert "import digitalio" not in DEMO_PAYLOAD
        # Only stdlib imports allowed in the demo.
        assert "import time" in DEMO_PAYLOAD


# ---------------------------------------------------------------------------
# bootstrap + add-device — interactive port-picker + onboarding wizard
# ---------------------------------------------------------------------------


class TestBootstrapHelpers:
    """Unit-level tests for the device-id suggestion + port-picker helpers."""

    def test_suggest_device_id_strips_with_chip_tail(self) -> None:
        from chumicro_deploy import DeviceImplementation
        from chumicro_workspace.cli.devices import _suggest_device_id

        result = _suggest_device_id(DeviceImplementation(
            name="circuitpython",
            version="10.1.4",
            machine="Raspberry Pi Pico W with rp2040",
            uid="ABCD",
        ))
        assert result == "raspberry-pi-pico-w"

    def test_suggest_device_id_handles_blank_machine(self) -> None:
        from chumicro_deploy import DeviceImplementation
        from chumicro_workspace.cli.devices import _suggest_device_id

        result = _suggest_device_id(DeviceImplementation(
            name="micropython", version="1.27.0", machine="", uid="",
        ))
        # Blank machine → neutral "board" fallback (the user can
        # rename via ``rename --device``).  Avoiding the runtime
        # name keeps the add-device suffix layer from producing
        # confusing results like "micropython-mp".
        assert result == "board"

    def test_suggest_device_id_strips_chip_with_hyphen(self) -> None:
        """F4: chip variants with hyphens (``ESP32S2-S2FN4R2``) must
        not survive into the slug as ``s2mini-with-esp32s2-s2fn4r2``.
        The strip pattern matches `` with .*$`` (anchored at EOL).
        """
        from chumicro_deploy import DeviceImplementation
        from chumicro_workspace.cli.devices import _suggest_device_id

        result = _suggest_device_id(DeviceImplementation(
            name="circuitpython",
            version="10.1.4",
            machine="S2Mini with ESP32S2-S2FN4R2",
            uid="84722E7490C3",
        ))
        assert result == "s2mini"

        result = _suggest_device_id(DeviceImplementation(
            name="micropython",
            version="1.28.0",
            machine="LOLIN_S2_MINI with ESP32-S2FN4R2",
            uid="4827E24708D2",
        ))
        assert result == "lolin-s2-mini"

    def test_suggest_device_id_falls_back_to_board(self) -> None:
        from chumicro_deploy import DeviceImplementation
        from chumicro_workspace.cli.devices import _suggest_device_id

        result = _suggest_device_id(DeviceImplementation(
            name="", version="0.0.0", machine="!@#$%", uid="",
        ))
        assert result == "board"

    def test_resolve_serial_port_explicit_wins(self) -> None:
        from chumicro_workspace.cli._common import _resolve_serial_port

        result = _resolve_serial_port("/dev/cu.fake")
        assert result == "/dev/cu.fake"

    def test_resolve_serial_port_no_ports_returns_none(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from chumicro_workspace.cli._common import _resolve_serial_port
        from serial.tools import list_ports

        monkeypatch.setattr(list_ports, "comports", lambda: [])
        result = _resolve_serial_port(None)
        assert result is None

    def test_resolve_serial_port_single_port_auto_picks(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from chumicro_workspace.cli._common import _resolve_serial_port
        from serial.tools import list_ports

        monkeypatch.setattr(
            list_ports,
            "comports",
            lambda: [FakePort("/dev/cu.only", "Pi Pico W")],
        )
        result = _resolve_serial_port(None)
        assert result == "/dev/cu.only"

    def test_resolve_serial_port_multiple_ports_prompts(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from chumicro_workspace.cli._common import _resolve_serial_port
        from serial.tools import list_ports

        monkeypatch.setattr(
            list_ports,
            "comports",
            lambda: [FakePort("/dev/cu.a"), FakePort("/dev/cu.b")],
        )
        result = _resolve_serial_port(None, prompt_func=lambda _: "2")
        assert result == "/dev/cu.b"

    def test_resolve_serial_port_invalid_choice_returns_none(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from chumicro_workspace.cli._common import _resolve_serial_port
        from serial.tools import list_ports

        monkeypatch.setattr(
            list_ports,
            "comports",
            lambda: [FakePort("/dev/cu.a"), FakePort("/dev/cu.b")],
        )
        # Out-of-range numeric choice.
        result = _resolve_serial_port(
            None, prompt_func=lambda _: "99",
        )
        assert result is None
        # Non-numeric choice.
        result = _resolve_serial_port(
            None, prompt_func=lambda _: "garbage",
        )
        assert result is None

    def test_resolve_serial_port_command_name_in_messages(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``command_name`` keyword tunes the user-facing log prefix."""
        from chumicro_workspace.cli._common import _resolve_serial_port
        from serial.tools import list_ports

        monkeypatch.setattr(list_ports, "comports", lambda: [])
        _resolve_serial_port(None, command_name="bootstrap")
        assert "bootstrap: no serial ports detected" in capsys.readouterr().err


class TestSuggestAddDeviceId:
    """``add-device`` derives a sensible default device id from the
    probe when the user omits the positional id.
    """

    def _impl(self, machine: str, runtime: str) -> "DeviceImplementation":  # noqa: F821 — quoted forward ref; impl imports inline below
        from chumicro_deploy import DeviceImplementation  # noqa: PLC0415

        return DeviceImplementation(
            name=runtime, version="0.0.0", machine=machine, uid="",
        )

    def test_pi_pico_w_circuitpython(self) -> None:
        from chumicro_workspace.cli.devices import _suggest_add_device_id  # noqa: PLC0415

        result = _suggest_add_device_id(
            implementation=self._impl(
                "Raspberry Pi Pico W with rp2040", "circuitpython",
            ),
            existing_ids=set(),
        )
        assert result == "raspberry-pi-pico-w-cp"

    def test_lolin_s2_micropython(self) -> None:
        from chumicro_workspace.cli.devices import _suggest_add_device_id  # noqa: PLC0415

        result = _suggest_add_device_id(
            implementation=self._impl(
                "LOLIN_S2_MINI with ESP32-S2FN4R2", "micropython",
            ),
            existing_ids=set(),
        )
        assert result == "lolin-s2-mini-mp"

    def test_collision_appends_numeric_suffix(self) -> None:
        from chumicro_workspace.cli.devices import _suggest_add_device_id  # noqa: PLC0415

        impl = self._impl(
            "Raspberry Pi Pico W with rp2040", "micropython",
        )
        # First registration: base id.
        assert _suggest_add_device_id(
            implementation=impl, existing_ids=set(),
        ) == "raspberry-pi-pico-w-mp"
        # Second board, same model: ``-2``.
        assert _suggest_add_device_id(
            implementation=impl,
            existing_ids={"raspberry-pi-pico-w-mp"},
        ) == "raspberry-pi-pico-w-mp-2"
        # Third board: ``-3``.
        assert _suggest_add_device_id(
            implementation=impl,
            existing_ids={
                "raspberry-pi-pico-w-mp", "raspberry-pi-pico-w-mp-2",
            },
        ) == "raspberry-pi-pico-w-mp-3"

    def test_blank_machine_falls_back_to_board_runtime(self) -> None:
        """Empty machine → ``"board-cp"`` / ``"board-mp"`` — neutral
        default the user can rename.  Avoids confusing slugs like
        ``"micropython-mp"`` that the suffix layer would produce if
        the underlying helper still used the runtime name as fallback.
        """
        from chumicro_workspace.cli.devices import _suggest_add_device_id  # noqa: PLC0415

        assert _suggest_add_device_id(
            implementation=self._impl("", "circuitpython"),
            existing_ids=set(),
        ) == "board-cp"
        assert _suggest_add_device_id(
            implementation=self._impl("", "micropython"),
            existing_ids=set(),
        ) == "board-mp"

    def test_unknown_runtime_uses_runtime_name_as_suffix(self) -> None:
        """Forward-compat: a third runtime probes its own name as
        the suffix (no map entry).  Won't be reached today since
        the probe only returns ``circuitpython`` / ``micropython``,
        but kept defensive.
        """
        from chumicro_workspace.cli.devices import _suggest_add_device_id  # noqa: PLC0415

        result = _suggest_add_device_id(
            implementation=self._impl(
                "Some Board with chip", "wasipython",
            ),
            existing_ids=set(),
        )
        assert result == "some-board-wasipython"


class TestBootstrapWizard:
    """End-to-end CLI tests for `chumicro-workspace bootstrap`.

    The bootstrap shim delegates to ``add-device`` for the probe +
    register flow, then prints a "next steps" footer for first-time
    users.  Demo deploy is opt-in via ``--demo``.
    """

    def _seed(self, tmp_path: Path) -> Path:
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')
        return tmp_path

    def test_full_flow_with_explicit_flags(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """All flags set → no prompts, full registration, footer printed."""
        root = self._seed(tmp_path)

        from chumicro_workspace import cli as workspace_cli
        from chumicro_workspace import onboarding

        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=fake_probe_info(
                    runtime="micropython",
                    machine="Raspberry Pi Pico W with rp2040",
                    version="1.27.0",
                ),
                runtime="micropython",
            )

        monkeypatch.setattr(
            workspace_cli.devices, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )

        exit_code = cli.main([
            "bootstrap", "--workspace-dir", str(root),
            "--address", "/dev/cu.fake",
            "pico",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "auto-detected runtime = micropython" in captured.out
        assert "registered pico" in captured.out
        # Next-steps footer (the bootstrap shim's only addition over add-device).
        assert "new <project-name>" in captured.out
        assert "deploy" in captured.out
        assert "repl" in captured.out

        body = (root / "devices.yml").read_text()
        assert "pico" in body
        assert "/dev/cu.fake" in body
        assert "firmware_version: 1.27.0" in body

    def test_inference_failure_prints_diagnosis(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = self._seed(tmp_path)

        from chumicro_workspace import cli as workspace_cli
        from chumicro_workspace import onboarding

        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=None, runtime=None,
                last_exception=OSError("could not open port /dev/cu.x"),
            )

        monkeypatch.setattr(
            workspace_cli.devices, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )

        # detect_board_state runs its own probe — stub it.
        import chumicro_deploy
        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _d: (_ for _ in ()).throw(
                OSError("could not open port /dev/cu.x"),
            ),
        )

        exit_code = cli.main(
            [
                "bootstrap", "--workspace-dir", str(root),
                "--address", "/dev/cu.x",
                "pico",
            ],
            env=cli.CliEnv(uf2_search_paths=[]),
        )
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "auto-detect failed" in captured.err
        # Diagnosis next-steps suggest discover/replug for SERIAL_UNREACHABLE.
        assert "discover" in captured.err

    def test_old_firmware_warning_does_not_block(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = self._seed(tmp_path)

        from chumicro_workspace import cli as workspace_cli
        from chumicro_workspace import onboarding

        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=fake_probe_info(
                    runtime="micropython", version="1.26.0",
                ),
                runtime="micropython",
            )

        monkeypatch.setattr(
            workspace_cli.devices, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )

        exit_code = cli.main([
            "bootstrap", "--workspace-dir", str(root),
            "--address", "/dev/cu.x",
            "pico",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        # Warning emitted to stderr but registration proceeded.
        assert "1.26.0" in captured.err
        assert "1.27.0" in captured.err  # the floor
        body = (root / "devices.yml").read_text()
        assert "pico" in body

    def test_duplicate_device_id_returns_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Bootstrapping a second board onto an existing id should fail
        cleanly, not silently overwrite.  ``--force`` is the documented
        opt-in for the swap-board case (same as add-device)."""
        root = self._seed(tmp_path)
        # Pre-seed devices.yml with the conflicting id.
        (root / "devices.yml").write_text(
            "defaults: {}\n"
            "devices:\n"
            "  - id: pico\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.old\n",
        )

        from chumicro_workspace import cli as workspace_cli
        from chumicro_workspace import onboarding

        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=fake_probe_info(version="1.27.0"),
                runtime="micropython",
            )

        monkeypatch.setattr(
            workspace_cli.devices, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )

        exit_code = cli.main([
            "bootstrap", "--workspace-dir", str(root),
            "--address", "/dev/cu.new",
            "pico",
        ])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "already exists" in captured.err

    def test_demo_does_not_run_by_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Bootstrap registers without chaining into demo unless ``--demo`` is passed.

        The opt-in flip (was opt-out via ``--no-demo``) keeps the
        common path quiet — most onboarding flows want the user to
        deploy their own code next, not see a demo first.
        """
        root = self._seed(tmp_path)

        from chumicro_workspace import cli as workspace_cli
        from chumicro_workspace import onboarding

        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=fake_probe_info(version="1.27.0"),
                runtime="micropython",
            )

        monkeypatch.setattr(
            workspace_cli.devices, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )

        # If demo ran, this transport would be invoked; spy on construction.
        constructed: list[bool] = []
        def spy_transport(self):  # noqa: ANN001
            constructed.append(True)
            return FakeTransport(execute_output="should not run")
        _install_fake_transport(monkeypatch, factory=spy_transport)

        exit_code = cli.main([
            "bootstrap", "--workspace-dir", str(root),
            "--address", "/dev/cu.fake",
            "pico",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "registered pico" in captured.out
        # Demo deploy never ran, so transport was never constructed.
        assert constructed == []
        assert "should not run" not in captured.out

    def test_demo_runs_with_demo_flag(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--demo`` chains into the built-in demo deploy after register."""
        root = self._seed(tmp_path)

        from chumicro_workspace import cli as workspace_cli
        from chumicro_workspace import onboarding

        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=fake_probe_info(version="1.27.0"),
                runtime="micropython",
            )

        monkeypatch.setattr(
            workspace_cli.devices, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )

        # Stub the deploy transport so the demo step doesn't need
        # real hardware.
        transport = FakeTransport(
            execute_output="Hello from ChuMicro!\ndemo complete!\n",
        )
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "bootstrap", "--workspace-dir", str(root),
            "--address", "/dev/cu.fake",
            "--demo",
            "pico",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "registered pico" in captured.out
        assert "Hello from ChuMicro" in captured.out


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------


class TestProbe:
    def test_prints_implementation_marker(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)

        import chumicro_deploy

        info = fake_probe_info(
            runtime="micropython", version="1.26.0",
            machine="Lolin S2", uid="ABCD", board_id="lolin_s2",
        )
        monkeypatch.setattr(chumicro_deploy, "probe_device", lambda _device: info)
        exit_code = cli.main(["probe", "--workspace-dir", str(root)])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "runtime: micropython" in out
        assert "version: 1.26.0" in out
        assert "uid: ABCD" in out

    def test_no_implementation_returns_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        import chumicro_deploy

        info = fake_probe_info(with_implementation=False)
        monkeypatch.setattr(chumicro_deploy, "probe_device", lambda _device: info)
        exit_code = cli.main(["probe", "--workspace-dir", str(root)])
        assert exit_code == 1
        assert "no implementation marker" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# repl
# ---------------------------------------------------------------------------


class TestDeployTail:
    """`deploy <project> --tail` deploys then tails in one command.

    This is the one deploy-then-watch path.  The old
    `repl <project>` shortcut owned a *second* deploy orchestration
    that drifted and shipped a board-dead library regression; it was
    retired and the convenience moved onto `deploy` as a flag, so
    exactly one mechanism puts code on a board.
    """

    def test_deploys_then_tails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = seed_workspace(tmp_path)
        project_dir = seed_project(root, name="back-porch")
        (project_dir / "app.py").write_text("def run(): print('back-porch')\n")

        transport = FakeTransport(execute_output="back-porch\n")
        _install_fake_transport(monkeypatch, transport)
        captured: dict[str, Any] = {}

        def fake_tail(device: Device, seconds: float, **kwargs: Any) -> int:
            captured["seconds"] = seconds
            return 0

        import chumicro_repl
        monkeypatch.setattr(chumicro_repl, "tail", fake_tail)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root), "back-porch", "--tail",
        ])
        assert exit_code == 0
        # `--tail` with no value applies the default window.
        assert captured["seconds"] == 30.0
        deploy_calls = [
            call for call in transport.calls if call[0] == "deploy_files"
        ]
        assert len(deploy_calls) == 1
        files, _entrypoint, _follow = deploy_calls[0][1]
        # seed_project ships code.py + main.py → flat layout; project
        # files land at the device root.
        assert "/app.py" in files
        assert "/main.py" in files
        assert "/active.py" not in files
        assert not any(path.startswith("/lib/projects/") for path in files)

    def test_deploy_tail_ships_imported_libraries(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Regression lock: the deploy-then-watch path ships imports.

        The retired `repl <project>` hardcoded `project_boot_source`
        (shim + project files, ZERO library payload), so on an
        app.py+import project `deploy_diff` wholesale-deleted the
        prior deploy's `/lib/<pkg>/` tree and left the board dead
        (bench-reproduced on Pico W CP).  `deploy --tail` routes
        through `resolve_project_deploy_source` like every deploy, so
        an app.py+run() project auto-resolves boot-shim+import-graph
        and the imported module reaches `/lib/`.  There is no second
        path to drift.
        """
        root = seed_workspace(tmp_path)
        shared = root / "shared"
        shared.mkdir()
        (shared / "external_lib.py").write_text("def helper(): pass\n")
        # app.py + run() with NO code.py/main.py → auto
        # boot-shim+import-graph (the shape the regression hit).
        project_dir = root / "projects" / "back-porch"
        project_dir.mkdir(parents=True)
        (project_dir / "project_config.toml").write_text(
            "[wifi]\nssid = 'HomeNet'\n",
        )
        (project_dir / "app.py").write_text(
            "import external_lib\ndef run(): print('back-porch')\n",
        )

        transport = FakeTransport(execute_output="back-porch\n")
        _install_fake_transport(monkeypatch, transport)

        import chumicro_repl
        monkeypatch.setattr(chumicro_repl, "tail", lambda *args, **kwargs: 0)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root), "back-porch", "--tail",
        ])
        assert exit_code == 0
        deploy_calls = [
            call for call in transport.calls if call[0] == "deploy_files"
        ]
        assert len(deploy_calls) == 1
        files, _entrypoint, _follow = deploy_calls[0][1]
        # Boot-shim layer (seed defaults to MP → /main.py shim).
        assert "/main.py" in files
        assert "/app.py" in files
        # The fix: the import-graph contribution reaches the device.
        assert "/lib/external_lib.py" in files

    def test_explicit_tail_seconds(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`deploy <project> --tail 5` overrides the default window."""
        root = seed_workspace(tmp_path)
        project_dir = seed_project(root, name="back-porch")
        (project_dir / "app.py").write_text("def run(): print('back-porch')\n")

        transport = FakeTransport(execute_output="")
        _install_fake_transport(monkeypatch, transport)
        captured: dict[str, Any] = {}

        def fake_tail(device: Device, seconds: float, **kwargs: Any) -> int:
            captured["seconds"] = seconds
            return 0

        import chumicro_repl
        monkeypatch.setattr(chumicro_repl, "tail", fake_tail)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "back-porch", "--tail", "5",
        ])
        assert exit_code == 0
        assert captured["seconds"] == 5.0

    def test_nested_project_name_resolves(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = seed_workspace(tmp_path)
        project_dir = seed_project(root, name="garage/sensors/door_open")
        (project_dir / "app.py").write_text("def run(): print('door_open')\n")

        transport = FakeTransport(execute_output="")
        _install_fake_transport(monkeypatch, transport)

        import chumicro_repl
        monkeypatch.setattr(
            chumicro_repl, "tail", lambda *args, **kwargs: 0,
        )

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "garage/sensors/door_open", "--tail",
        ])
        assert exit_code == 0
        deploy_calls = [
            call for call in transport.calls if call[0] == "deploy_files"
        ]
        files, _entrypoint, _follow = deploy_calls[0][1]
        # Slash-form project name resolves; files land at the device
        # root regardless of host-side nesting depth.
        assert "/app.py" in files
        assert "/main.py" in files
        assert "/active.py" not in files
        assert not any(path.startswith("/lib/projects/") for path in files)

    def test_failed_deploy_returns_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Tail is skipped when the deploy traceback marks failure."""
        root = seed_workspace(tmp_path)
        project_dir = seed_project(root, name="back-porch")
        (project_dir / "app.py").write_text("def run(): pass\n")

        transport = FakeTransport(
            execute_output=(
                "Traceback (most recent call last):\n"
                "  File \"/code.py\", line 1\n"
                "RuntimeError: deploy-failed\n"
            ),
        )
        _install_fake_transport(monkeypatch, transport)

        tail_called = [False]

        def fake_tail(*args: Any, **kwargs: Any) -> int:
            tail_called[0] = True
            return 0

        import chumicro_repl
        monkeypatch.setattr(chumicro_repl, "tail", fake_tail)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root), "back-porch", "--tail",
        ])
        assert exit_code == 1
        assert tail_called[0] is False
        assert "deploy-failed" in capsys.readouterr().err

    def test_transport_error_surfaces_message_not_traceback(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A transport error during deploy exits 1 with its message on stderr, not a traceback."""
        root = seed_workspace(tmp_path)
        project_dir = seed_project(root, name="back-porch")
        (project_dir / "app.py").write_text("def run(): pass\n")
        transport = FakeTransport(
            connect_raises=MicropythonTransportError(
                "serial port /dev/cu.fake is busy",
            ),
        )
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root), "back-porch",
        ])
        assert exit_code == 1
        assert "serial port /dev/cu.fake is busy" in capsys.readouterr().err

    def test_all_devices_continues_past_a_failing_device(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """deploy --all-devices reports both devices' transport errors, not just the first."""
        root = seed_workspace(tmp_path)
        (root / "devices.yml").write_text(
            "defaults:\n"
            "  micropython: board-a\n"
            "devices:\n"
            "  - id: board-a\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.fake-a\n"
            "  - id: board-b\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.fake-b\n",
        )
        project_dir = seed_project(root, name="back-porch")
        (project_dir / "app.py").write_text("def run(): pass\n")
        transport = FakeTransport(
            connect_raises=MicropythonTransportError("port busy"),
        )
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root), "back-porch", "--all-devices",
        ])
        assert exit_code == 1
        # Both addresses appear, so the loop continued past board-a's failure
        # instead of aborting the whole run on the first device.
        stderr_text = capsys.readouterr().err
        assert "/dev/cu.fake-a" in stderr_text
        assert "/dev/cu.fake-b" in stderr_text

    def test_tail_requires_single_target(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """`--tail` follows one board — multi-target plans are refused.

        The guard runs before any transport, so two registered
        devices + `--all-devices` is enough to exercise it.
        """
        root = seed_workspace(tmp_path)
        (root / "devices.yml").write_text(
            "defaults:\n"
            "  micropython: board-a\n"
            "devices:\n"
            "  - id: board-a\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.fake-a\n"
            "  - id: board-b\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.fake-b\n",
        )
        project_dir = seed_project(root, name="back-porch")
        (project_dir / "app.py").write_text("def run(): pass\n")
        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "back-porch", "--all-devices", "--tail", "--non-interactive",
        ])
        assert exit_code == 2
        assert "exactly one" in capsys.readouterr().err

    def test_repl_no_longer_accepts_a_project(
        self, tmp_path: Path,
    ) -> None:
        """CLI surface lock: `repl <project>` was retired.

        repl owns only interactive / tail; deploy-then-watch is
        `deploy <project> --tail`.  A stray positional must be a
        clean argparse rejection, not a silent second deploy path.
        """
        root = seed_workspace(tmp_path)
        with pytest.raises(SystemExit) as caught:
            cli.main(["repl", "--workspace-dir", str(root), "back-porch"])
        # argparse "unrecognized arguments" exits 2.
        assert caught.value.code == 2


class TestRepl:
    def test_passthrough_mode(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`repl --mode passthrough` forwards keystrokes byte-by-byte."""
        root = seed_workspace(tmp_path)
        captured: dict[str, Any] = {}

        def fake_interactive(device: Device) -> int:
            captured["device"] = device
            return 0

        import chumicro_repl
        monkeypatch.setattr(chumicro_repl, "interactive", fake_interactive)
        exit_code = cli.main([
            "repl", "--workspace-dir", str(root), "--mode", "passthrough",
        ])
        assert exit_code == 0
        assert captured["device"].address == "/dev/cu.fake"

    def test_line_mode(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`repl --mode line` opens the host-side line editor (default for TTYs)."""
        root = seed_workspace(tmp_path)
        captured: dict[str, Any] = {}

        def fake_interactive_line(device: Device) -> int:
            captured["device"] = device
            return 0

        import chumicro_repl
        monkeypatch.setattr(
            chumicro_repl, "interactive_line", fake_interactive_line,
        )
        exit_code = cli.main([
            "repl", "--workspace-dir", str(root), "--mode", "line",
        ])
        assert exit_code == 0
        assert captured["device"].address == "/dev/cu.fake"

    def test_tail_path(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = seed_workspace(tmp_path)
        captured: dict[str, Any] = {}

        def fake_tail(device: Device, seconds: float, **kwargs: Any) -> int:
            captured["seconds"] = seconds
            captured["fail_on_traceback"] = kwargs["fail_on_traceback"]
            return 0

        import chumicro_repl
        monkeypatch.setattr(chumicro_repl, "tail", fake_tail)
        exit_code = cli.main([
            "repl", "--workspace-dir", str(root),
            "--tail", "1.5", "--no-fail-on-traceback",
        ])
        assert exit_code == 0
        assert captured["seconds"] == 1.5
        assert captured["fail_on_traceback"] is False

    def test_session_failure_routes_through_coaching(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Port-not-found on `repl` enters the coaching loop, not a bare traceback."""
        import errno

        root = seed_workspace(tmp_path)
        attempts: list[int] = []

        def fake_interactive_line(_device: Device) -> int:
            attempts.append(1)
            if len(attempts) == 1:
                raise OSError(errno.ENOENT, "No such file or directory")
            return 0

        outputs: list[str] = []

        def fake_coached(callable_, **_kwargs: Any) -> int:
            # Pretend the user retried once and succeeded — capture
            # that we routed through the coaching wrapper rather than
            # checking the raw stdin/stdout flow at the unit-test
            # level.
            try:
                return callable_()
            except OSError:
                outputs.append("coached")
                return callable_()

        import chumicro_repl
        monkeypatch.setattr(
            chumicro_repl, "interactive_line", fake_interactive_line,
        )
        monkeypatch.setattr(
            chumicro_repl, "coached_session_start", fake_coached,
        )
        exit_code = cli.main([
            "repl", "--workspace-dir", str(root), "--mode", "line",
        ])
        assert exit_code == 0
        assert outputs == ["coached"]
        assert len(attempts) == 2

    def test_non_interactive_skips_coaching(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`--non-interactive` bypasses the coaching wrapper entirely."""
        root = seed_workspace(tmp_path)
        coached_called: list[bool] = []

        def fake_interactive_line(_device: Device) -> int:
            return 0

        def fake_coached(*_args: Any, **_kwargs: Any) -> int:
            coached_called.append(True)
            return 0

        import chumicro_repl
        monkeypatch.setattr(
            chumicro_repl, "interactive_line", fake_interactive_line,
        )
        monkeypatch.setattr(
            chumicro_repl, "coached_session_start", fake_coached,
        )
        exit_code = cli.main([
            "repl", "--workspace-dir", str(root),
            "--mode", "line", "--non-interactive",
        ])
        assert exit_code == 0
        assert coached_called == []  # coaching wrapper never invoked


class TestResolveReplMode:
    """`_resolve_repl_mode` picks line for TTY stdin, passthrough otherwise."""

    def test_explicit_line_passes_through(self) -> None:
        from chumicro_workspace.cli.repl import _resolve_repl_mode

        # Caller-specified value wins over the auto check.
        assert _resolve_repl_mode("line", stdin=_StubStdin(isatty=False)) == "line"

    def test_explicit_passthrough_passes_through(self) -> None:
        from chumicro_workspace.cli.repl import _resolve_repl_mode

        assert _resolve_repl_mode(
            "passthrough", stdin=_StubStdin(isatty=True),
        ) == "passthrough"

    def test_auto_picks_line_on_tty(self) -> None:
        from chumicro_workspace.cli.repl import _resolve_repl_mode

        assert _resolve_repl_mode("auto", stdin=_StubStdin(isatty=True)) == "line"

    def test_auto_picks_passthrough_otherwise(self) -> None:
        from chumicro_workspace.cli.repl import _resolve_repl_mode

        assert _resolve_repl_mode(
            "auto", stdin=_StubStdin(isatty=False),
        ) == "passthrough"

    def test_auto_picks_passthrough_when_stdin_lacks_isatty(self) -> None:
        """A non-stream stdin (e.g. None / a stub without isatty) falls back."""
        from chumicro_workspace.cli.repl import _resolve_repl_mode

        class _Bare:
            pass

        assert _resolve_repl_mode("auto", stdin=_Bare()) == "passthrough"


class _StubStdin:
    """Tiny stand-in for ``sys.stdin`` exposing only ``isatty()``."""

    def __init__(self, *, isatty: bool) -> None:
        self._isatty = isatty

    def isatty(self) -> bool:
        return self._isatty


# ---------------------------------------------------------------------------
# install-firmware / upgrade-firmware
# ---------------------------------------------------------------------------


class TestInstallFirmware:
    def test_invokes_flash_firmware(
        self,
        tmp_path: Path,
    ) -> None:
        root = seed_workspace(tmp_path)
        captured: dict[str, Any] = {}

        def fake_flash(url: str, device: Device, **kwargs: Any) -> None:
            captured["url"] = url
            captured["device_address"] = device.address
            captured["method"] = kwargs["reflash_method"]

        exit_code = cli.main(
            [
                "install-firmware", "--workspace-dir", str(root),
                "--url", "https://example.com/fw.uf2", "--method", "uf2",
            ],
            env=cli.CliEnv(flash_firmware_fn=fake_flash),
        )
        assert exit_code == 0
        assert captured["url"] == "https://example.com/fw.uf2"
        assert captured["method"] == "uf2"

    def test_flash_failure_surfaces_message_not_traceback(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A FlashFirmwareError exits 1 with its guidance on stderr, not a traceback."""
        root = seed_workspace(tmp_path)

        def fake_flash(_url: str, _device: Device, **_kwargs: Any) -> None:
            raise FlashFirmwareError(
                "UF2 bootloader drive did not appear; hold BOOTSEL and replug",
            )

        exit_code = cli.main(
            [
                "install-firmware", "--workspace-dir", str(root),
                "--url", "https://example.com/fw.uf2", "--method", "uf2",
            ],
            env=cli.CliEnv(flash_firmware_fn=fake_flash),
        )
        assert exit_code == 1
        assert "hold BOOTSEL and replug" in capsys.readouterr().err

    def test_upgrade_firmware_uses_same_handler(
        self,
        tmp_path: Path,
    ) -> None:
        """upgrade-firmware aliases install-firmware — same flash flow."""
        root = seed_workspace(tmp_path)
        called: list[str] = []

        def fake_flash(url: str, _device: Device, **_kwargs: Any) -> None:
            called.append(url)

        exit_code = cli.main(
            [
                "upgrade-firmware", "--workspace-dir", str(root),
                "--url", "https://example.com/fw.bin", "--method", "esptool",
            ],
            env=cli.CliEnv(flash_firmware_fn=fake_flash),
        )
        assert exit_code == 0
        assert called == ["https://example.com/fw.bin"]

    def test_url_omitted_derives_from_device_entry(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--url optional, derived from hardware.firmware_source."""
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')
        (tmp_path / "devices.yml").write_text(
            "defaults:\n"
            "  micropython: pico\n"
            "devices:\n"
            "  - id: pico\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.fake\n"
            "    hardware:\n"
            "      firmware_source: https://my-mirror/firmware.bin\n"
        )

        captured: list[str] = []

        def fake_flash(url: str, _device: Device, **_kwargs: Any) -> None:
            captured.append(url)

        exit_code = cli.main(
            [
                "install-firmware", "--workspace-dir", str(tmp_path),
                "--method", "esptool",
            ],
            env=cli.CliEnv(flash_firmware_fn=fake_flash),
        )
        assert exit_code == 0
        assert captured == ["https://my-mirror/firmware.bin"]
        assert "resolved https://my-mirror/firmware.bin" in capsys.readouterr().out

    def test_url_omitted_unknown_device_returns_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No --url + no --device id → can't derive, exit 2."""
        root = seed_workspace(tmp_path)
        # Default-resolution lands on lolin-s2, which has no
        # hardware block → derive raises UnresolvedFirmwareError.
        exit_code = cli.main([
            "install-firmware", "--workspace-dir", str(root),
            "--method", "uf2",
        ])
        assert exit_code == 2
        captured_stderr = capsys.readouterr().err
        assert "install-firmware" in captured_stderr

    def test_url_omitted_unresolvable_returns_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A device with no resolvable hardware fields → exit 2 with a hint."""
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')
        (tmp_path / "devices.yml").write_text(
            "devices:\n"
            "  - id: orphan\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.fake\n"
        )
        exit_code = cli.main([
            "install-firmware", "--workspace-dir", str(tmp_path),
            "--device", "orphan", "--method", "esptool",
        ])
        assert exit_code == 2
        assert "hardware.machine" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# test
# ---------------------------------------------------------------------------


class TestTestCommand:
    def test_shells_out_to_pytest(
        self,
        tmp_path: Path,
    ) -> None:
        root = seed_workspace(tmp_path)
        runner = FakeSubprocessRunner()
        exit_code = cli.main(
            ["test", "--workspace-dir", str(root), "--", "-k", "sanity"],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 0
        assert runner.calls[0].args == [
            sys.executable, "-m", "pytest", "--", "-k", "sanity",
        ]
        assert runner.calls[0].cwd == root

    def test_fails_loudly_when_pytest_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When pytest isn't installed, ``test`` must exit nonzero with a
        ``python3 run.py setup`` pointer instead of shelling out to a raw
        "No module named pytest" traceback."""
        root = seed_workspace(tmp_path)
        runner = FakeSubprocessRunner()

        import builtins
        original_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any):
            if name == "pytest":
                raise ImportError("pytest not installed")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        exit_code = cli.main(
            ["test", "--workspace-dir", str(root)],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code != 0
        # pytest never got shelled out to.
        assert runner.calls == []
        captured = capsys.readouterr()
        assert "pytest is not installed" in captured.err
        assert "python3 run.py setup" in captured.err


class TestLintCommand:
    def test_shells_out_to_ruff_then_chumicro_checks(
        self,
        tmp_path: Path,
    ) -> None:
        root = seed_workspace(tmp_path)
        runner = FakeSubprocessRunner()
        exit_code = cli.main(
            ["lint", "--workspace-dir", str(root)],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 0
        # First call: ruff.
        assert runner.calls[0].args == [
            sys.executable, "-m", "ruff", "check", ".",
        ]
        assert runner.calls[0].cwd == root
        # Second call: chumicro-checks.
        assert runner.calls[1].args == [
            sys.executable, "-m", "chumicro_checks", "--root", str(root),
        ]
        assert runner.calls[1].cwd == root

    def test_forwards_extra_args_to_ruff(
        self,
        tmp_path: Path,
    ) -> None:
        root = seed_workspace(tmp_path)
        runner = FakeSubprocessRunner()
        exit_code = cli.main(
            ["lint", "--workspace-dir", str(root), "--", "--fix"],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 0
        ruff_args = runner.calls[0].args
        assert "--fix" in ruff_args
        # The trailing "." anchors ruff to the workspace root regardless
        # of any extra args the user passed.
        assert ruff_args[-1] == "."

    def test_ruff_failure_short_circuits_chumicro_checks(
        self,
        tmp_path: Path,
    ) -> None:
        root = seed_workspace(tmp_path)
        # Ruff fails — chumicro-checks should not be invoked.
        runner = FakeSubprocessRunner(returncode=1)
        exit_code = cli.main(
            ["lint", "--workspace-dir", str(root)],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 1
        # Only ruff ran; chumicro-checks didn't get a turn.
        assert len(runner.calls) == 1
        assert runner.calls[0].args[2] == "ruff"

    def test_fails_loudly_when_chumicro_checks_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When chumicro-checks isn't installed, ruff still runs but lint
        must fail nonzero — a green lint that skips a whole tool would
        report success on a workspace that never installed ``[dev]``."""
        root = seed_workspace(tmp_path)
        runner = FakeSubprocessRunner()

        import builtins
        original_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any):
            if name == "chumicro_checks":
                raise ImportError("chumicro-checks not installed")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        exit_code = cli.main(
            ["lint", "--workspace-dir", str(root)],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code != 0
        # Ruff ran; chumicro-checks didn't (the probe short-circuited).
        assert len(runner.calls) == 1
        captured = capsys.readouterr()
        assert "chumicro-checks is not installed" in captured.err
        assert "python3 run.py setup" in captured.err

    def test_fails_loudly_when_ruff_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When ruff isn't installed, lint must exit nonzero with a
        ``python3 run.py setup`` pointer rather than green-washing."""
        root = seed_workspace(tmp_path)

        # Force the import probe inside _cmd_lint to fail.
        import builtins

        original_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any):
            if name == "ruff":
                raise ImportError("ruff not installed")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        exit_code = cli.main([
            "lint", "--workspace-dir", str(root),
        ])
        assert exit_code != 0
        captured = capsys.readouterr()
        assert "ruff is not installed" in captured.err
        assert "python3 run.py setup" in captured.err


class TestQualityKnobsLint:
    """workspace.yml `quality.lint` flows through _cmd_lint."""

    def test_disabled_skips_ruff(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        # Append a quality block disabling lint.
        (root / "workspace.yml").write_text(
            (root / "workspace.yml").read_text()
            + "quality:\n  lint:\n    enabled: false\n",
        )

        runner = FakeSubprocessRunner()
        exit_code = cli.main(
            ["lint", "--workspace-dir", str(root)],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 0
        assert runner.calls == []
        assert "disabled" in capsys.readouterr().out

    def test_select_prepended_before_user_args(
        self,
        tmp_path: Path,
    ) -> None:
        root = seed_workspace(tmp_path)
        (root / "workspace.yml").write_text(
            (root / "workspace.yml").read_text()
            + 'quality:\n  lint:\n    select: ["E", "F", "I"]\n',
        )

        runner = FakeSubprocessRunner()
        exit_code = cli.main(
            ["lint", "--workspace-dir", str(root), "--", "--fix"],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 0
        # Workspace --select goes BEFORE user passthrough so the user's
        # later --select (if any) wins.  Inspect the ruff call (first).
        ruff_args = runner.calls[0].args
        select_index = ruff_args.index("--select")
        fix_index = ruff_args.index("--fix")
        assert select_index < fix_index
        assert ruff_args[select_index + 1] == "E,F,I"

    def test_tools_ruff_only_skips_chumicro_checks(
        self,
        tmp_path: Path,
    ) -> None:
        root = seed_workspace(tmp_path)
        (root / "workspace.yml").write_text(
            (root / "workspace.yml").read_text()
            + 'quality:\n  lint:\n    tools: ["ruff"]\n',
        )

        runner = FakeSubprocessRunner()
        exit_code = cli.main(
            ["lint", "--workspace-dir", str(root)],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 0
        assert len(runner.calls) == 1
        assert runner.calls[0].args[2] == "ruff"

    def test_tools_chumicro_checks_only_skips_ruff(
        self,
        tmp_path: Path,
    ) -> None:
        root = seed_workspace(tmp_path)
        (root / "workspace.yml").write_text(
            (root / "workspace.yml").read_text()
            + 'quality:\n  lint:\n    tools: ["chumicro-checks"]\n',
        )

        runner = FakeSubprocessRunner()
        exit_code = cli.main(
            ["lint", "--workspace-dir", str(root)],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 0
        assert len(runner.calls) == 1
        assert runner.calls[0].args[1] == "-m"
        assert runner.calls[0].args[2] == "chumicro_checks"

    def test_tools_empty_list_skips_phase(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        (root / "workspace.yml").write_text(
            (root / "workspace.yml").read_text()
            + "quality:\n  lint:\n    tools: []\n",
        )

        runner = FakeSubprocessRunner()
        exit_code = cli.main(
            ["lint", "--workspace-dir", str(root)],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 0
        assert runner.calls == []
        assert "no tools selected" in capsys.readouterr().out

    def test_tools_chumicro_checks_failure_returned(
        self,
        tmp_path: Path,
    ) -> None:
        """A failing chumicro-checks run propagates its exit code."""
        root = seed_workspace(tmp_path)
        (root / "workspace.yml").write_text(
            (root / "workspace.yml").read_text()
            + 'quality:\n  lint:\n    tools: ["chumicro-checks"]\n',
        )

        exit_code = cli.main(
            ["lint", "--workspace-dir", str(root)],
            env=cli.CliEnv(subprocess_runner=FakeSubprocessRunner(returncode=7)),
        )
        assert exit_code == 7


class TestQualityKnobsTest:
    """workspace.yml `quality.coverage_threshold` flows through _cmd_test."""

    def test_threshold_prepended_to_pytest(
        self,
        tmp_path: Path,
    ) -> None:
        root = seed_workspace(tmp_path)
        (root / "workspace.yml").write_text(
            (root / "workspace.yml").read_text()
            + "quality:\n  coverage_threshold: 90\n",
        )

        runner = FakeSubprocessRunner()
        exit_code = cli.main(
            ["test", "--workspace-dir", str(root), "--", "-x"],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 0
        last_args = runner.calls[-1].args
        assert "--cov-fail-under=90" in last_args
        # Workspace flag comes before user passthrough; pytest's
        # last-occurrence-wins lets the user override.
        gate_index = last_args.index("--cov-fail-under=90")
        x_index = last_args.index("-x")
        assert gate_index < x_index

    def test_no_threshold_no_extra_flags(
        self,
        tmp_path: Path,
    ) -> None:
        root = seed_workspace(tmp_path)

        runner = FakeSubprocessRunner()
        exit_code = cli.main(
            ["test", "--workspace-dir", str(root)],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 0
        assert not any(
            arg.startswith("--cov-fail-under") for arg in runner.calls[-1].args
        )


# ---------------------------------------------------------------------------
# Workspace-not-found
# ---------------------------------------------------------------------------


class TestWorkspaceResolution:
    def test_missing_workspace_yields_systemexit(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as caught:
            cli.main(["devices", "--workspace-dir", str(tmp_path)])
        assert "workspace.yml" in str(caught.value)


# ---------------------------------------------------------------------------
# add-device — three-zone YAML writer wired in
# ---------------------------------------------------------------------------


class TestAddDevice:
    def test_writes_new_entry_to_devices_yml(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Start with no devices.yml — typical fresh-workspace case.
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')
        import chumicro_deploy
        monkeypatch.setattr(
            chumicro_deploy, "probe_device", lambda _device: fake_probe_info(),
        )
        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.fake", "--runtime", "micropython",
            "--description", "Test board", "lolin-s2",
        ])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "registered lolin-s2" in out
        body = (tmp_path / "devices.yml").read_text()
        assert "lolin-s2" in body
        assert "/dev/cu.fake" in body
        assert "ABCD1234" in body  # hardware-once UID landed
        assert "Test board" in body  # user-owned description

    def test_re_register_without_force_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')
        import chumicro_deploy
        monkeypatch.setattr(
            chumicro_deploy, "probe_device", lambda _device: fake_probe_info(),
        )

        first = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.fake", "--runtime", "micropython", "lolin-s2",
        ])
        assert first == 0
        capsys.readouterr()

        second = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.fake", "--runtime", "micropython", "lolin-s2",
        ])
        assert second == 1
        assert "already exists" in capsys.readouterr().err

    def test_re_register_with_force_refreshes_address(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')
        import chumicro_deploy
        monkeypatch.setattr(
            chumicro_deploy, "probe_device", lambda _device: fake_probe_info(),
        )
        cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.old", "--runtime", "micropython", "lolin-s2",
        ])
        # Re-probe with --force at a different port.
        result = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.new", "--runtime", "micropython",
            "--force", "lolin-s2",
        ])
        assert result == 0
        body = (tmp_path / "devices.yml").read_text()
        assert "/dev/cu.new" in body
        assert "/dev/cu.old" not in body

    def test_force_swap_with_changed_uid_succeeds(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--force allows hardware.uid to change ('I swapped boards')."""
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')
        import chumicro_deploy

        first_info = fake_probe_info(uid="ORIGINAL")
        monkeypatch.setattr(chumicro_deploy, "probe_device", lambda _d: first_info)
        cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "--runtime", "micropython", "lolin",
        ])

        second_info = fake_probe_info(uid="DIFFERENT")
        monkeypatch.setattr(chumicro_deploy, "probe_device", lambda _d: second_info)
        result = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "--runtime", "micropython",
            "--force", "lolin",
        ])
        assert result == 0
        assert "DIFFERENT" in (tmp_path / "devices.yml").read_text()

    def test_probe_no_marker_returns_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')

        class _NoMarker:
            implementation = None
            board_id = ""
            uid = ""

        import chumicro_deploy

        monkeypatch.setattr(chumicro_deploy, "probe_device", lambda _d: _NoMarker())
        # Force "no UF2 drive on the dev box" so the diagnosis lands on
        # NO_PROBE_RESPONSE (the esptool branch) rather than UF2_BOOTLOADER.
        exit_code = cli.main(
            [
                "add-device", "--workspace-dir", str(tmp_path),
                "--address", "/dev/cu.x", "--runtime", "micropython", "lolin",
            ],
            env=cli.CliEnv(uf2_search_paths=[]),
        )
        assert exit_code == 1
        captured_stderr = capsys.readouterr().err
        assert "did not return implementation" in captured_stderr
        # Onboarding diagnosis follows on subsequent lines.
        assert "esptool" in captured_stderr.lower()

    def test_probe_raises_emits_onboarding_diagnosis(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A probe exception falls through to detect_board_state for help."""
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')

        def raising_probe(_device):
            raise OSError("could not open port /dev/cu.absent")

        import chumicro_deploy

        monkeypatch.setattr(chumicro_deploy, "probe_device", raising_probe)
        exit_code = cli.main(
            [
                "add-device", "--workspace-dir", str(tmp_path),
                "--address", "/dev/cu.absent", "--runtime", "micropython", "lolin",
            ],
            env=cli.CliEnv(uf2_search_paths=[]),
        )
        assert exit_code == 1
        captured_stderr = capsys.readouterr().err
        assert "probe failed" in captured_stderr
        assert "discover" in captured_stderr  # SERIAL_UNREACHABLE recommendation

    def test_uf2_bootloader_message_when_drive_present(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A board in UF2 bootloader gets the install-firmware --method uf2 hint."""
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')
        # Stage a fake UF2 mount under tmp_path.
        uf2_mount_root = tmp_path / "Volumes"
        uf2_mount_root.mkdir()
        drive = uf2_mount_root / "RPI-RP2"
        drive.mkdir()
        (drive / "INFO_UF2.TXT").write_text("UF2 Bootloader\n")

        class _NoMarker:
            implementation = None
            board_id = ""
            uid = ""

        import chumicro_deploy

        monkeypatch.setattr(chumicro_deploy, "probe_device", lambda _d: _NoMarker())
        exit_code = cli.main(
            [
                "add-device", "--workspace-dir", str(tmp_path),
                "--address", "/dev/cu.x", "--runtime", "micropython", "lolin",
            ],
            env=cli.CliEnv(uf2_search_paths=[uf2_mount_root]),
        )
        assert exit_code == 1
        captured_stderr = capsys.readouterr().err
        assert "UF2 bootloader" in captured_stderr
        assert "install-firmware" in captured_stderr

    def test_user_comments_in_devices_yml_survive_add(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The headline value of the round-trip writer."""
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')
        (tmp_path / "devices.yml").write_text(
            "# House sensors — keep this file checked in.\n"
            "defaults:\n"
            "  micropython: existing  # default for deploy commands\n"
            "devices:\n"
            "  - id: existing\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.preset\n"
        )

        import chumicro_deploy
        monkeypatch.setattr(
            chumicro_deploy, "probe_device", lambda _d: fake_probe_info(),
        )
        cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.fake", "--runtime", "micropython", "lolin-s2",
        ])
        body = (tmp_path / "devices.yml").read_text()
        assert "# House sensors" in body
        assert "# default for deploy commands" in body
        assert "lolin-s2" in body  # new entry made it in


# ---------------------------------------------------------------------------
# add-device — auto-fill ``defaults.<runtime>`` on first registration
# of a runtime (gap 6 of the workspace-template
# dev-and-regular-mode-gaps audit).
# ---------------------------------------------------------------------------


class TestAddDeviceAutoDefaults:
    def test_first_device_of_runtime_fills_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Adding the first MP device sets ``defaults.micropython``."""
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')
        import chumicro_deploy
        monkeypatch.setattr(
            chumicro_deploy, "probe_device", lambda _device: fake_probe_info(),
        )
        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.fake", "--runtime", "micropython", "lolin-s2",
        ])
        assert exit_code == 0
        body = (tmp_path / "devices.yml").read_text()
        assert "micropython: lolin-s2" in body

    def test_first_device_with_null_default_slot_fills_it(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The materialized template has ``micropython:`` (null) — fill on first add.

        Repro for gap #6's exact symptom: the user runs
        ``chumicro-workspace setup`` (which materializes a
        devices.yml.template carrying ``defaults.micropython: null``),
        then runs ``add-device``.  Pre-fix, the slot stayed null
        because the existence check (``runtime not in defaults``)
        skipped present-but-null keys.  Post-fix, the null is
        treated as "no default set" and the new device fills it.
        """
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')
        # Pre-create a devices.yml mirroring the template materializer's output.
        (tmp_path / "devices.yml").write_text(
            "defaults:\n"
            "  micropython:\n"
            "  circuitpython:\n",
        )
        import chumicro_deploy
        monkeypatch.setattr(
            chumicro_deploy, "probe_device", lambda _device: fake_probe_info(),
        )
        cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.fake", "--runtime", "micropython", "lolin-s2",
        ])
        body = (tmp_path / "devices.yml").read_text()
        assert "micropython: lolin-s2" in body

    def test_second_device_of_same_runtime_does_not_overwrite_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Adding a 2nd MP device leaves the existing default alone."""
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')
        import chumicro_deploy
        # First add — fills defaults.
        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _device: fake_probe_info(uid="UID-A"),
        )
        cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.A", "--runtime", "micropython", "first",
        ])
        # Second add — same runtime, different board.
        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _device: fake_probe_info(uid="UID-B"),
        )
        cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.B", "--runtime", "micropython", "second",
        ])
        body = (tmp_path / "devices.yml").read_text()
        # Still the first device — the auto-fill happened on add 1, not 2.
        assert "micropython: first" in body
        assert "micropython: second" not in body

    def test_different_runtime_fills_its_own_slot(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """MP and CP each get their own auto-fill on first registration."""
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')
        import chumicro_deploy
        # First add MP.
        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _device: fake_probe_info(runtime="micropython"),
        )
        cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.mp", "--runtime", "micropython", "lolin-s2",
        ])
        # Then add CP.
        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _device: fake_probe_info(
                runtime="circuitpython", uid="CP-UID", version="9.2.0",
            ),
        )
        cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.cp", "--runtime", "circuitpython", "pico-w",
        ])
        body = (tmp_path / "devices.yml").read_text()
        assert "micropython: lolin-s2" in body
        assert "circuitpython: pico-w" in body

    def test_existing_default_not_overwritten(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A user-set ``defaults.micropython`` survives a fresh add-device."""
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')
        # Pre-existing devices.yml with a default already named.
        (tmp_path / "devices.yml").write_text(
            "defaults:\n"
            "  micropython: preset-default\n"
            "devices:\n"
            "  - id: preset-default\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.old\n",
        )
        import chumicro_deploy
        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _device: fake_probe_info(uid="NEW-UID"),
        )
        cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.new", "--runtime", "micropython", "newcomer",
        ])
        body = (tmp_path / "devices.yml").read_text()
        # Default unchanged.
        assert "micropython: preset-default" in body
        assert "micropython: newcomer" not in body

    def test_force_re_probe_does_not_auto_fill(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Re-probing with --force shouldn't touch defaults — first-add territory only."""
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')
        # Pre-existing entry with defaults explicitly cleared.
        (tmp_path / "devices.yml").write_text(
            "defaults:\n"
            "  micropython:\n"  # null
            "devices:\n"
            "  - id: lolin-s2\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.old\n"
            "    hardware:\n"
            "      uid: ABCD1234\n",
        )
        import chumicro_deploy
        monkeypatch.setattr(
            chumicro_deploy, "probe_device", lambda _device: fake_probe_info(),
        )
        cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.new", "--runtime", "micropython",
            "--force", "lolin-s2",
        ])
        body = (tmp_path / "devices.yml").read_text()
        # Defaults stays null (user cleared it; --force re-probe doesn't restore).
        assert "micropython:\n" in body or "micropython: null" in body


# ---------------------------------------------------------------------------
# add-device — firmware-version floor
# ---------------------------------------------------------------------------


class TestAddDeviceFirmwareFloor:
    def _seed(self, tmp_path: Path) -> None:
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')

    def test_supported_firmware_emits_no_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._seed(tmp_path)
        import chumicro_deploy

        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _d: fake_probe_info(version="1.27.0"),
        )
        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "--runtime", "micropython", "pico",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "warning" not in captured.err.lower()

    def test_old_firmware_warns_but_succeeds(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Below-floor firmware: warn, don't block registration."""
        self._seed(tmp_path)
        import chumicro_deploy

        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _d: fake_probe_info(version="1.26.0"),
        )
        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "--runtime", "micropython", "pico",
        ])
        assert exit_code == 0  # warn, do not block
        captured = capsys.readouterr()
        assert "1.26.0" in captured.err
        assert "1.27.0" in captured.err
        assert "install-firmware" in captured.err

    def test_unknown_runtime_warns(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._seed(tmp_path)
        import chumicro_deploy

        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _d: fake_probe_info(runtime="cpython", version="3.13.0"),
        )
        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "--runtime", "micropython", "host",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "tested matrix" in captured.err

    def test_firmware_version_persisted_to_devices_yml(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The probed-always firmware_version field should land on disk."""
        self._seed(tmp_path)
        import chumicro_deploy

        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _d: fake_probe_info(version="1.27.0"),
        )
        cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "--runtime", "micropython", "pico",
        ])
        body = (tmp_path / "devices.yml").read_text()
        assert "firmware_version: 1.27.0" in body

    def test_force_reprobe_refreshes_firmware_version(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An upgrade out of band → re-probe with --force should overwrite."""
        self._seed(tmp_path)
        import chumicro_deploy

        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _d: fake_probe_info(version="1.26.0"),
        )
        cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "--runtime", "micropython", "pico",
        ])
        body_before = (tmp_path / "devices.yml").read_text()
        assert "firmware_version: 1.26.0" in body_before

        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _d: fake_probe_info(version="1.27.0"),
        )
        result = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "--runtime", "micropython",
            "--force", "pico",
        ])
        assert result == 0
        body_after = (tmp_path / "devices.yml").read_text()
        assert "firmware_version: 1.27.0" in body_after
        assert "firmware_version: 1.26.0" not in body_after


# ---------------------------------------------------------------------------
# add-device — runtime auto-inference
# ---------------------------------------------------------------------------


class TestAddDeviceRuntimeInference:
    """`--runtime` is optional; when omitted, runtime is probed."""

    def _seed(self, tmp_path: Path) -> None:
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')

    def test_omitted_runtime_is_inferred(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._seed(tmp_path)
        from chumicro_workspace import onboarding

        # Fake the inference helper to return a CP probe.
        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=fake_probe_info(
                    runtime="circuitpython", version="10.1.4",
                ),
                runtime="circuitpython",
            )

        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )
        # Also rebind the name imported into cli.py.
        monkeypatch.setattr(cli.devices, "probe_with_runtime_inference", fake_inference)

        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "feather",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "auto-detected runtime = circuitpython" in captured.out
        body = (tmp_path / "devices.yml").read_text()
        assert "runtime: circuitpython" in body
        assert "firmware_version: 10.1.4" in body

    def test_explicit_runtime_skips_inference(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Passing --runtime takes the existing path; inference is bypassed."""
        self._seed(tmp_path)
        called = {"inference": False, "probe": False}

        from chumicro_workspace import onboarding

        def fake_inference(*_args, **_kw):
            called["inference"] = True
            raise AssertionError("inference should not run when --runtime set")

        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(cli.devices, "probe_with_runtime_inference", fake_inference)

        import chumicro_deploy

        def fake_probe(_device):
            called["probe"] = True
            return fake_probe_info(version="1.27.0")

        monkeypatch.setattr(chumicro_deploy, "probe_device", fake_probe)

        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "--runtime", "micropython", "pico",
        ])
        assert exit_code == 0
        assert called["probe"] is True
        assert called["inference"] is False

    def test_inference_failure_falls_through_to_diagnosis(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No transport produced a marker → exit 1 with a helpful diagnosis."""
        self._seed(tmp_path)
        from chumicro_workspace import onboarding

        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=None,
                runtime=None,
                last_exception=OSError("could not open port /dev/cu.x"),
            )

        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(cli.devices, "probe_with_runtime_inference", fake_inference)

        # detect_board_state will run its own probe — stub it so we don't
        # actually try to open the port.
        import chumicro_deploy
        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _d: (_ for _ in ()).throw(
                OSError("could not open port /dev/cu.x"),
            ),
        )

        # Force the diagnosis branch onto SERIAL_UNREACHABLE — no UF2 drive.
        exit_code = cli.main(
            [
                "add-device", "--workspace-dir", str(tmp_path),
                "--address", "/dev/cu.x", "feather",
            ],
            env=cli.CliEnv(uf2_search_paths=[]),
        )
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "auto-detect failed" in captured.err
        # Diagnosis next-steps suggest discover/replug for SERIAL_UNREACHABLE.
        assert "discover" in captured.err

    def test_inference_completes_but_returns_no_marker(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Probe ran cleanly on every transport but no implementation marker.

        last_exception stays None so the message reads "no runtime
        returned a probe marker" instead of pointing at an exception.
        """
        self._seed(tmp_path)
        from chumicro_workspace import onboarding

        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=None,
                runtime=None,
                last_exception=None,
            )

        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(cli.devices, "probe_with_runtime_inference", fake_inference)

        import chumicro_deploy

        class _NoMarker:
            implementation = None
            board_id = ""
            uid = ""

        monkeypatch.setattr(
            chumicro_deploy, "probe_device", lambda _d: _NoMarker(),
        )

        exit_code = cli.main(
            [
                "add-device", "--workspace-dir", str(tmp_path),
                "--address", "/dev/cu.x", "feather",
            ],
            env=cli.CliEnv(uf2_search_paths=[]),
        )
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "no runtime returned a probe marker" in captured.err


class TestAddDeviceOmittedId:
    """``add-device`` accepts no positional id and derives a default
    from the probe.
    """

    def _seed(self, tmp_path: Path) -> None:
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')

    def test_omitted_id_uses_suggested(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No positional id → derive from machine + runtime + collision-resolve."""
        self._seed(tmp_path)
        from chumicro_workspace import onboarding

        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=fake_probe_info(
                    runtime="circuitpython",
                    machine="Raspberry Pi Pico W with rp2040",
                    version="10.1.4",
                ),
                runtime="circuitpython",
            )

        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(cli.devices, "probe_with_runtime_inference", fake_inference)

        # No positional id passed.
        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "using suggested id 'raspberry-pi-pico-w-cp'" in captured.out
        body = (tmp_path / "devices.yml").read_text()
        assert "id: raspberry-pi-pico-w-cp" in body

    def test_omitted_id_collides_appends_counter(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Two probes of identical board models produce ``-cp`` and ``-cp-2``."""
        self._seed(tmp_path)
        from chumicro_workspace import onboarding

        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=fake_probe_info(
                    runtime="circuitpython",
                    machine="Raspberry Pi Pico W with rp2040",
                    version="10.1.4",
                    uid="ABCD1234",
                ),
                runtime="circuitpython",
            )

        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(cli.devices, "probe_with_runtime_inference", fake_inference)

        # First registration.
        cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x",
        ])

        # Second registration with the same probe shape — a different
        # physical board (different uid) but the same model + runtime.
        # Bumping uid via a fresh fake_inference closure isn't necessary:
        # the suggested-id collision logic doesn't read uid, only the
        # existing id set.
        def fake_inference_second(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=fake_probe_info(
                    runtime="circuitpython",
                    machine="Raspberry Pi Pico W with rp2040",
                    version="10.1.4",
                    uid="EF567890",
                ),
                runtime="circuitpython",
            )

        monkeypatch.setattr(
            onboarding,
            "probe_with_runtime_inference",
            fake_inference_second,
        )
        monkeypatch.setattr(
            cli.devices, "probe_with_runtime_inference", fake_inference_second,
        )
        capsys.readouterr()  # drain first run's output.
        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.y",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "using suggested id 'raspberry-pi-pico-w-cp-2'" in captured.out
        body = (tmp_path / "devices.yml").read_text()
        assert "id: raspberry-pi-pico-w-cp" in body
        assert "id: raspberry-pi-pico-w-cp-2" in body

    def test_explicit_id_skips_suggestion(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Positional id wins; no "using suggested id" message printed."""
        self._seed(tmp_path)
        from chumicro_workspace import onboarding

        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=fake_probe_info(
                    runtime="circuitpython",
                    machine="Raspberry Pi Pico W with rp2040",
                    version="10.1.4",
                ),
                runtime="circuitpython",
            )

        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(cli.devices, "probe_with_runtime_inference", fake_inference)

        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "porch",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "using suggested id" not in captured.out
        body = (tmp_path / "devices.yml").read_text()
        assert "id: porch" in body


class TestAddDeviceOmittedAddress:
    """``add-device`` accepts no ``--address`` and falls into the
    serial-port picker (auto-pick when one port detected, prompt
    when multiple).  Non-interactive callers must pass ``--address``
    explicitly.
    """

    def _seed(self, tmp_path: Path) -> None:
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')

    def _stub_inference(
        self, monkeypatch: pytest.MonkeyPatch, version: str = "10.1.4",
    ) -> None:
        from chumicro_workspace import onboarding

        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=fake_probe_info(
                    runtime="circuitpython",
                    machine="Raspberry Pi Pico W with rp2040",
                    version=version,
                ),
                runtime="circuitpython",
            )

        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(
            cli.devices, "probe_with_runtime_inference", fake_inference,
        )

    def test_single_port_auto_picks(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """One port detected → used silently, no prompt."""
        self._seed(tmp_path)
        from serial.tools import list_ports

        monkeypatch.setattr(
            list_ports,
            "comports",
            lambda: [FakePort("/dev/cu.only", "Pi Pico W")],
        )
        self._stub_inference(monkeypatch)

        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "only one port found, using /dev/cu.only" in captured.out
        body = (tmp_path / "devices.yml").read_text()
        assert "address: /dev/cu.only" in body

    def test_no_ports_returns_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Empty port list → exit 1 with hint."""
        self._seed(tmp_path)
        from serial.tools import list_ports

        monkeypatch.setattr(list_ports, "comports", lambda: [])

        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
        ])
        assert exit_code == 1
        assert "no serial ports detected" in capsys.readouterr().err

    def test_non_interactive_without_address_returns_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--non-interactive`` requires ``--address`` — agent-runnable CLIs never prompt."""
        self._seed(tmp_path)

        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--non-interactive",
        ])
        assert exit_code == 2
        assert "--address is required" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# rename — wired to project dirs + devices.yml
# ---------------------------------------------------------------------------


class TestRename:
    def test_project_renames_directory(self, tmp_path: Path) -> None:
        root = seed_workspace(tmp_path)
        seed_project(root, "old_name")
        exit_code = cli.main([
            "rename", "--workspace-dir", str(root),
            "--project", "old_name", "new_name",
        ])
        assert exit_code == 0
        assert not (root / "projects" / "old_name").exists()
        assert (root / "projects" / "new_name" / "code.py").exists()

    def test_project_missing_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        exit_code = cli.main([
            "rename", "--workspace-dir", str(root),
            "--project", "ghost", "spook",
        ])
        assert exit_code == 1
        assert "not found" in capsys.readouterr().err

    def test_project_target_exists_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        seed_project(root, "alpha")
        seed_project(root, "beta")
        exit_code = cli.main([
            "rename", "--workspace-dir", str(root),
            "--project", "alpha", "beta",
        ])
        assert exit_code == 1
        assert "already exists" in capsys.readouterr().err

    def test_project_rejects_invalid_new_segment(
        self, tmp_path: Path,
    ) -> None:
        """``_validate_project_name`` runs on both sides of the rename."""
        root = seed_workspace(tmp_path)
        seed_project(root, "alpha")
        with pytest.raises(SystemExit) as caught:
            cli.main([
                "rename", "--workspace-dir", str(root),
                "--project", "alpha", "kitchen-sensor",
            ])
        assert "valid Python identifier" in str(caught.value)


class TestRenameNested:
    """`rename --project` accepts slash / dotted paths on both sides."""

    def test_moves_into_new_namespace(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        seed_project(root, "bedroom_sensor")

        exit_code = cli.main([
            "rename", "--workspace-dir", str(root),
            "--project", "bedroom_sensor", "upstairs/bedroom_sensor",
        ])
        assert exit_code == 0
        assert not (root / "projects" / "bedroom_sensor").exists()
        assert (
            root / "projects" / "upstairs" / "bedroom_sensor" / "code.py"
        ).is_file()
        # Auto-created namespace dir got an __init__.py marker.
        assert (root / "projects" / "upstairs" / "__init__.py").is_file()
        out = capsys.readouterr().out
        assert "creating namespace projects/upstairs/" in out

    def test_moves_between_namespaces(
        self, tmp_path: Path,
    ) -> None:
        root = seed_workspace(tmp_path)
        seed_project(root, "garage/door_open")

        exit_code = cli.main([
            "rename", "--workspace-dir", str(root),
            "--project", "garage/door_open", "upstairs/door_open",
        ])
        assert exit_code == 0
        assert not (
            root / "projects" / "garage" / "door_open"
        ).exists()
        assert (
            root / "projects" / "upstairs" / "door_open" / "code.py"
        ).is_file()

    def test_dotted_form_normalizes(self, tmp_path: Path) -> None:
        root = seed_workspace(tmp_path)
        seed_project(root, "garage/door_open")

        exit_code = cli.main([
            "rename", "--workspace-dir", str(root),
            "--project", "garage.door_open", "upstairs.door_open",
        ])
        assert exit_code == 0
        assert (
            root / "projects" / "upstairs" / "door_open" / "code.py"
        ).is_file()

    def test_bare_name_disambiguates_against_tree(
        self, tmp_path: Path,
    ) -> None:
        """Bare old-name resolves uniquely when only one path matches."""
        root = seed_workspace(tmp_path)
        seed_project(root, "garage/door_open")
        seed_project(root, "thermostat")

        exit_code = cli.main([
            "rename", "--workspace-dir", str(root),
            "--project", "door_open", "front_door_open",
        ])
        assert exit_code == 0
        assert (
            root / "projects" / "front_door_open" / "code.py"
        ).is_file()

    def test_bare_name_ambiguous_lists_candidates(
        self, tmp_path: Path,
    ) -> None:
        root = seed_workspace(tmp_path)
        seed_project(root, "upstairs/sensor")
        seed_project(root, "garage/sensor")
        with pytest.raises(SystemExit) as caught:
            cli.main([
                "rename", "--workspace-dir", str(root),
                "--project", "sensor", "renamed_sensor",
            ])
        assert "ambiguous" in str(caught.value)

    def test_device_rename_rewrites_id_and_default(self, tmp_path: Path) -> None:
        root = seed_workspace(tmp_path)
        # Seed devices.yml has 'lolin-s2' as default.
        exit_code = cli.main([
            "rename", "--workspace-dir", str(root),
            "--device", "lolin-s2", "back-porch",
        ])
        assert exit_code == 0
        body = (root / "devices.yml").read_text()
        assert "lolin-s2" not in body
        assert "back-porch" in body

    def test_device_missing_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        exit_code = cli.main([
            "rename", "--workspace-dir", str(root),
            "--device", "ghost", "spook",
        ])
        assert exit_code == 1
        assert "not found" in capsys.readouterr().err

    def test_device_target_exists_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')
        (tmp_path / "devices.yml").write_text(
            "devices:\n"
            "  - id: alpha\n"
            "    runtime: micropython\n"
            "    address: /a\n"
            "  - id: beta\n"
            "    runtime: circuitpython\n"
            "    address: /b\n"
        )
        exit_code = cli.main([
            "rename", "--workspace-dir", str(tmp_path),
            "--device", "alpha", "beta",
        ])
        assert exit_code == 1
        assert "already exists" in capsys.readouterr().err

    def test_neither_project_nor_device_specified_argparse_errors(
        self,
        tmp_path: Path,
    ) -> None:
        """Argparse's mutually-exclusive group raises SystemExit on missing input."""
        root = seed_workspace(tmp_path)
        with pytest.raises(SystemExit):
            cli.main(["rename", "--workspace-dir", str(root)])


class TestDeployHealthGate:
    """Pre-deploy fast health gate — block on ERROR, warn on WARN, opt-out flag."""

    def test_aborts_on_error_level_finding(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Malformed workspace.yml is an ERROR; deploy aborts with exit 2."""
        root = seed_workspace(tmp_path)
        seed_project(root)
        # Corrupt workspace.yml to trigger an ERROR-level finding.
        (root / "workspace.yml").write_text("not: valid: yaml: ::\n")

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "--device", "lolin-s2", "back-porch",
        ])
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "ERROR WORKSPACE.YML" in captured.err
        assert "aborting before sending bytes" in captured.err

    def test_skip_health_check_bypasses_error_gate(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--skip-health-check bypasses the gate even on ERROR findings.

        Synthesises an ERROR-level finding via monkeypatch (rather
        than actually corrupting workspace.yml — that would also
        break the surrounding ``_resolve_workspace`` read, which is
        a separate failure mode).  The point of this test is that
        the gate's *abort* is what gets bypassed, not the deeper
        config-file reads.
        """
        root = seed_workspace(tmp_path)
        seed_project(root)

        from chumicro_workspace import cli as workspace_cli
        from chumicro_workspace.health import HealthFinding, HealthLevel

        synthetic_error = HealthFinding(
            label="WORKSPACE.YML",
            level=HealthLevel.ERROR,
            message="synthesised for test",
            hint="ignore — test fixture",
        )
        monkeypatch.setattr(
            workspace_cli.deploy, "collect_health_findings",
            lambda _ws: [synthetic_error],
        )

        # Stub the deploy transport so the test doesn't need real hardware.
        transport = FakeTransport(execute_output="ok\n")
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "--device", "lolin-s2", "back-porch",
            "--skip-health-check", "--non-interactive",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        # Gate suppressed → no "aborting" line.
        assert "aborting before sending bytes" not in captured.err
        # And no per-finding ERROR lines either.
        assert "ERROR WORKSPACE.YML" not in captured.err

    def test_warn_findings_print_but_do_not_block(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A devices.yml warn (no entries) prints but doesn't block deploy."""
        root = seed_workspace(tmp_path)
        seed_project(root)
        # Wipe devices.yml's entries so check_devices_yaml emits a WARN —
        # deploy itself still picks up the device-id we pass explicitly.
        (root / "devices.yml").write_text(
            "defaults:\n  micropython: lolin-s2\n"
            "devices:\n"
            "  - id: lolin-s2\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.fake\n",
        )

        transport = FakeTransport(execute_output="proceeded\n")
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "--device", "lolin-s2", "back-porch",
            "--non-interactive",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        # No ERROR-level findings → deploy proceeds.
        assert "aborting before sending bytes" not in captured.err
        assert "proceeded" in captured.out


class TestCommandPreflight:
    """preflight chains lint then test, short-circuits on failure."""

    def test_skips_test_when_lint_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        calls: list[str] = []

        def fake_lint(args):  # noqa: ANN001
            calls.append("lint")
            return 1
        def fake_test(args):  # noqa: ANN001
            calls.append("test")
            return 0
        monkeypatch.setattr(cli.quality, "_cmd_lint",fake_lint)
        monkeypatch.setattr(cli.quality, "_cmd_test",fake_test)

        exit_code = cli.main(["preflight", "--workspace-dir", str(root)])
        assert exit_code == 1
        assert calls == ["lint"]  # short-circuit
        assert "lint failed" in capsys.readouterr().out

    def test_runs_both_when_lint_passes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        calls: list[str] = []
        monkeypatch.setattr(
            cli.quality, "_cmd_lint", lambda args: calls.append("lint") or 0,  # noqa: ARG005
        )
        monkeypatch.setattr(
            cli.quality, "_cmd_test", lambda args: calls.append("test") or 0,  # noqa: ARG005
        )

        exit_code = cli.main(["preflight", "--workspace-dir", str(root)])
        assert exit_code == 0
        assert calls == ["lint", "test"]
        assert "passed" in capsys.readouterr().out

    def test_returns_test_exit_when_lint_passes_test_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = seed_workspace(tmp_path)
        monkeypatch.setattr(cli.quality, "_cmd_lint",lambda args: 0)  # noqa: ARG005
        monkeypatch.setattr(cli.quality, "_cmd_test",lambda args: 5)  # noqa: ARG005
        exit_code = cli.main(["preflight", "--workspace-dir", str(root)])
        assert exit_code == 5

    def test_real_composition_propagates_env_to_lint_and_test(
        self,
        tmp_path: Path,
    ) -> None:
        # The three tests above stub _cmd_lint / _cmd_test, so the
        # synthetic Namespaces _cmd_preflight builds for them were never
        # exercised — a missing `_env` on those Namespaces shipped as a
        # deterministic `AttributeError` (preflight gate dead).  This runs
        # the real composition so the propagation stays covered: both
        # sub-commands must shell out through the injected runner.
        root = seed_workspace(tmp_path)
        runner = FakeSubprocessRunner()
        exit_code = cli.main(
            ["preflight", "--workspace-dir", str(root)],
            env=cli.CliEnv(subprocess_runner=runner),
        )
        assert exit_code == 0
        invoked = [call.args for call in runner.calls]
        assert [sys.executable, "-m", "ruff", "check", "."] in invoked
        assert [sys.executable, "-m", "pytest"] in invoked


class TestCommandDumpConfig:
    """dump-config prints the merged config (workspace + overlay + project) for a project."""

    def test_prints_merged_config_as_json(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        seed_project(root, "back-porch")

        exit_code = cli.main([
            "dump-config", "--workspace-dir", str(root), "back-porch",
        ])
        assert exit_code == 0
        import json
        printed = json.loads(capsys.readouterr().out)
        # Workspace.yml defaults + project config — flat dotted-key
        # output (compose-time flatten produces wifi.ssid, etc.).
        assert printed["wifi.ssid"] == "HomeNet"
        assert printed["wifi.password"] == "shh"  # from workspace.yml
        assert printed["wifi.hostname_prefix"] == "chu-"

    def test_repr_mode_uses_python_repr(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        seed_project(root)
        exit_code = cli.main([
            "dump-config", "--workspace-dir", str(root), "back-porch", "--repr",
        ])
        assert exit_code == 0
        # repr() of a dict starts with `{`, not `{\n  "key"`.
        out = capsys.readouterr().out
        assert out.startswith("{")
        assert "'wifi.ssid'" in out

    def test_missing_project_raises(self, tmp_path: Path) -> None:
        root = seed_workspace(tmp_path)
        with pytest.raises(SystemExit, match="not found"):
            cli.main([
                "dump-config", "--workspace-dir", str(root), "ghost-project",
            ])


class TestConfigValidate:
    """``config-validate`` runs the manifest validator against projects."""

    def _seed_with_wifi_lib(self, root: Path) -> None:
        """Add a libraries/wifi/ alongside the workspace with a manifest."""
        wifi_lib = root / "libraries" / "wifi"
        (wifi_lib / "src" / "chumicro_wifi").mkdir(parents=True)
        (wifi_lib / "src" / "chumicro_wifi" / "__init__.py").write_text("")
        (wifi_lib / "pyproject.toml").write_text(
            '[project]\nname = "chumicro-wifi"\n'
            "[tool.chumicro.config]\n"
            'required_keys = ["wifi.ssid", "wifi.password"]\n',
        )

    def test_passes_when_required_keys_present(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        seed_project(root)
        self._seed_with_wifi_lib(root)
        # secrets.toml from _seed_workspace already carries
        # wifi.password; the project's wifi.ssid covers the
        # remaining required key via the project_config.toml seeded
        # by _seed_project.
        (root / "projects" / "back-porch" / "project_config.toml").write_text(
            "[wifi]\nssid = 'HomeNet'\n",
        )
        exit_code = cli.main([
            "config-validate", "--workspace-dir", str(root), "back-porch",
        ])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "OK back-porch" in out

    def test_fails_when_required_key_missing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        seed_project(root)
        self._seed_with_wifi_lib(root)
        # secrets.toml from _seed_workspace has no wifi.ssid; the
        # project_config.toml override is empty too.
        (root / "projects" / "back-porch" / "project_config.toml").write_text(
            "[other]\nkey = 'value'\n",
        )
        exit_code = cli.main([
            "config-validate", "--workspace-dir", str(root), "back-porch",
        ])
        assert exit_code == 1
        out = capsys.readouterr().out
        assert "FAIL back-porch" in out
        assert "wifi.ssid" in out

    def test_validates_every_project_when_no_args(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        seed_project(root, name="alpha")
        seed_project(root, name="beta")
        self._seed_with_wifi_lib(root)
        (root / "projects" / "alpha" / "project_config.toml").write_text(
            "[wifi]\nssid = 'A'\n",
        )
        (root / "projects" / "beta" / "project_config.toml").write_text(
            "[wifi]\nssid = 'B'\n",
        )
        exit_code = cli.main([
            "config-validate", "--workspace-dir", str(root),
        ])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "OK alpha" in out
        assert "OK beta" in out

    def test_no_op_when_no_libraries_declare_manifest(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # No libraries/ tree at all — no manifests to validate against.
        # Validator short-circuits with a clear message and exit 0.
        root = seed_workspace(tmp_path)
        seed_project(root)
        exit_code = cli.main([
            "config-validate", "--workspace-dir", str(root), "back-porch",
        ])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "no library declares" in out

    def test_no_op_when_no_projects(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = seed_workspace(tmp_path)
        # No projects/ directory at all.
        exit_code = cli.main([
            "config-validate", "--workspace-dir", str(root),
        ])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "no projects" in out


class TestResetBoard:
    """`chumicro-workspace reset-board` standalone wipe subcommand."""

    def test_without_yes_refuses_and_exits_two(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Bare ``reset-board`` exits 2 and never touches the transport."""
        root = seed_workspace(tmp_path)
        transport = FakeTransport(execute_output="", mode="copy")
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "reset-board", "--workspace-dir", str(root),
            "--device", "lolin-s2",
        ])
        assert exit_code == 2
        assert ("wipe_filesystem", ()) not in transport.calls
        assert "without --yes" in capsys.readouterr().err

    def test_with_yes_invokes_wipe_filesystem(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--yes`` connects, wipes, and disconnects in order."""
        root = seed_workspace(tmp_path)
        transport = FakeTransport(execute_output="", mode="copy")
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "reset-board", "--workspace-dir", str(root),
            "--device", "lolin-s2", "--yes",
        ])
        assert exit_code == 0
        kinds = [call[0] for call in transport.calls]
        assert kinds == ["connect", "wipe_filesystem", "disconnect"]

    def test_ram_mode_is_a_printed_no_op(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """RAM / mount mode never wrote to flash → reset-board prints + exits 0."""
        root = seed_workspace(tmp_path)
        transport = FakeTransport(execute_output="", mode="ram")
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "reset-board", "--workspace-dir", str(root),
            "--device", "lolin-s2", "--yes",
        ])
        assert exit_code == 0
        # No-op: never reached connect/wipe.
        assert ("wipe_filesystem", ()) not in transport.calls
        assert "nothing in flash to wipe" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# deploy-example — front-door command
# ---------------------------------------------------------------------------


def _seed_example_library(
    workspace_root: Path,
    library_name: str,
    *,
    example_name: str = "circuitpython_blink.py",
    example_body: str = "print('blink')\n",
    runtimes_marker: str | None = "circuitpython",
) -> Path:
    """Stage ``<workspace>/libraries/<lib>/{src,examples}/`` so the
    deploy-example handler can resolve the example + walk its imports.

    Returns the library root path.
    """
    library_root = workspace_root / "libraries" / library_name
    src_pkg = library_root / "src" / f"chumicro_{library_name}"
    src_pkg.mkdir(parents=True)
    (src_pkg / "__init__.py").write_text(f"VERSION = '{library_name}-1.0'\n")
    (library_root / "pyproject.toml").write_text(
        f'[project]\n'
        f'name = "chumicro-{library_name}"\nversion = "0.1.0"\n'
        f'\n[tool.chumicro.config]\nrequired_keys = []\noptional_keys = []\n',
    )
    examples = library_root / "examples"
    examples.mkdir()
    full_body = example_body
    if runtimes_marker is not None:
        full_body = f"__chumicro_runtimes__ = ({runtimes_marker!r},)\n" + body_to_pythony(full_body)
    else:
        full_body = body_to_pythony(full_body)
    (examples / example_name).write_text(full_body)
    return library_root


def body_to_pythony(text: str) -> str:
    """Identity passthrough — kept as a hook in case a test wants to
    inject standard imports automatically (currently no-op)."""
    return text


def _seed_workspace_with_cp_device(tmp_path: Path) -> Path:
    """``seed_workspace`` with a CircuitPython device registered by default.

    Matches the runtime of the deploy-example examples seeded below.
    """
    return seed_workspace(tmp_path, runtime="circuitpython")


class TestDeployExampleListing:
    """``--list`` enumerates examples without touching a device."""

    def test_list_all_libraries(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _seed_workspace_with_cp_device(tmp_path)
        _seed_example_library(root, "timing")
        _seed_example_library(
            root, "runner", example_name="circuitpython_blink.py",
        )
        exit_code = cli.main(
            ["deploy-example", "--workspace-dir", str(root), "--list"],
        )
        assert exit_code == 0
        out = capsys.readouterr().out.splitlines()
        assert "timing/circuitpython_blink" in out
        assert "runner/circuitpython_blink" in out

    def test_list_scoped_to_one_library(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _seed_workspace_with_cp_device(tmp_path)
        _seed_example_library(root, "timing")
        _seed_example_library(root, "runner")
        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root), "--list", "timing",
        ])
        assert exit_code == 0
        out = capsys.readouterr().out.splitlines()
        assert "timing/circuitpython_blink" in out
        assert "runner/circuitpython_blink" not in out

    def test_list_with_unknown_library_returns_precheck_error(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _seed_workspace_with_cp_device(tmp_path)
        _seed_example_library(root, "timing")
        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root),
            "--list", "ghost",
        ])
        assert exit_code == cli_examples.DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED
        assert "no examples under" in capsys.readouterr().err


class TestDeployExamplePrechecks:
    """Precheck failures all return exit 2 with structured stderr."""

    def test_missing_library_returns_precheck_error(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _seed_workspace_with_cp_device(tmp_path)
        (root / "libraries").mkdir()  # empty libraries/ tree
        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root),
            "noexlib", "blink", "--non-interactive",
        ])
        assert exit_code == cli_examples.DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED
        assert "noexlib" in capsys.readouterr().err

    def test_missing_example_file_returns_precheck_error(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _seed_workspace_with_cp_device(tmp_path)
        _seed_example_library(root, "timing")
        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root),
            "timing", "ghost", "--non-interactive",
        ])
        assert exit_code == cli_examples.DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED
        assert "ghost.py not found" in capsys.readouterr().err

    def test_runtime_mismatch_returns_precheck_error(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An example marked CP-only refuses to deploy to an MP device."""
        # Workspace has only an MP device registered.
        root = tmp_path
        (root / "workspace.yml").write_text("")
        (root / "secrets.toml").write_text("")
        (root / "devices.yml").write_text(
            "defaults:\n  micropython: lolin-s2\n"
            "devices:\n  - id: lolin-s2\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.fake\n",
        )
        _seed_example_library(
            root, "timing",
            example_name="circuitpython_only.py",
            runtimes_marker="circuitpython",
        )
        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root),
            "timing", "circuitpython_only", "--non-interactive",
            "--device", "lolin-s2",
        ])
        assert exit_code == cli_examples.DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED
        assert "requires circuitpython" in capsys.readouterr().err


class TestDeployExampleNoDevice:
    """State (1) — no device registered for the example's runtime."""

    def test_non_interactive_with_no_device_exits_three(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Empty devices.yml + --non-interactive → exit 3 with hint."""
        root = tmp_path
        (root / "workspace.yml").write_text("")
        (root / "secrets.toml").write_text("")
        (root / "devices.yml").write_text("devices: []\n")
        _seed_example_library(root, "timing")

        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root),
            "timing", "circuitpython_blink", "--non-interactive",
        ])
        assert exit_code == cli_examples.DEPLOY_EXAMPLE_EXIT_NO_DEVICE_REGISTERED
        stderr = capsys.readouterr().err
        assert "no circuitpython device registered" in stderr
        assert "add-device" in stderr
        assert "discover" in stderr

    def test_no_auto_register_falls_through_to_exit_three(
        self,
        tmp_path: Path,
    ) -> None:
        """--no-auto-register skips the wizard fall-through even in TTY mode."""
        root = tmp_path
        (root / "workspace.yml").write_text("")
        (root / "secrets.toml").write_text("")
        (root / "devices.yml").write_text("devices: []\n")
        _seed_example_library(root, "timing")

        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root),
            "timing", "circuitpython_blink", "--no-auto-register",
        ])
        assert exit_code == cli_examples.DEPLOY_EXAMPLE_EXIT_NO_DEVICE_REGISTERED


class TestDeployExampleHappyPath:
    """Full deploy through a FakeTransport."""

    def test_ships_example_through_fake_transport(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = _seed_workspace_with_cp_device(tmp_path)
        _seed_example_library(
            root, "timing",
            example_body="from chumicro_timing import VERSION\nprint(VERSION)\n",
        )
        transport = FakeTransport(execute_output="")
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root),
            "timing", "circuitpython_blink", "--non-interactive",
        ])
        assert exit_code == 0

        deploy_calls = [
            call for call in transport.calls if call[0] == "deploy_files"
        ]
        assert len(deploy_calls) == 1
        files, entrypoint, _follow = deploy_calls[0][1]
        assert entrypoint == "/code.py"
        # The walked library module rides under /lib/.
        assert "/lib/chumicro_timing/__init__.py" in files
        # And so does the merged runtime config msgpack.
        assert "/runtime_config.msgpack" in files

    def test_py_suffix_on_example_name_is_optional(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Both ``"blink"`` and ``"blink.py"`` resolve to the same example."""
        root = _seed_workspace_with_cp_device(tmp_path)
        _seed_example_library(root, "timing")
        transport = FakeTransport(execute_output="")
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root),
            "timing", "circuitpython_blink.py", "--non-interactive",
        ])
        assert exit_code == 0

    def test_tail_seconds_flag_flows_to_transport(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--tail-seconds 30`` reaches the CP transport's deploy_files.

        Slow-wifi boards (Pi Pico W cyw43) need a longer post-soft-reboot
        capture window so the example's first prints land inside it.
        Sweep harness uses this flag for known-slow (network) examples.
        """
        root = _seed_workspace_with_cp_device(tmp_path)
        _seed_example_library(root, "timing")
        transport = FakeTransport(execute_output="")
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root),
            "timing", "circuitpython_blink", "--non-interactive",
            "--tail-seconds", "30",
        ])
        assert exit_code == 0
        assert transport.last_tail_seconds == 30.0

    def test_tail_seconds_default_is_none(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without ``--tail-seconds``, the transport sees ``None``.

        ``None`` lets the CP transport fall back to its built-in
        timeout (10 s) — the prior default before this flag existed.
        """
        root = _seed_workspace_with_cp_device(tmp_path)
        _seed_example_library(root, "timing")
        transport = FakeTransport(execute_output="")
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root),
            "timing", "circuitpython_blink", "--non-interactive",
        ])
        assert exit_code == 0
        assert transport.last_tail_seconds is None


class TestDeployExampleModes:
    """``_resolve_deploy_example_modes`` honors TTY default + flags."""

    def test_non_interactive_flag_forces_no_tail(self) -> None:
        """``--non-interactive`` always disables tail, even with --tail."""
        args = argparse.Namespace(non_interactive=True, tail=True)
        non_interactive, should_tail = cli_examples._resolve_deploy_example_modes(args)
        assert non_interactive is True
        assert should_tail is False

    def test_tty_default_picks_interactive_tail(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No --non-interactive + isatty=True → interactive + tail."""
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        args = argparse.Namespace(non_interactive=False, tail=True)
        non_interactive, should_tail = cli_examples._resolve_deploy_example_modes(args)
        assert non_interactive is False
        assert should_tail is True

    def test_no_tty_picks_non_interactive(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No TTY → non-interactive default; tail also off."""
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        args = argparse.Namespace(non_interactive=False, tail=True)
        non_interactive, should_tail = cli_examples._resolve_deploy_example_modes(args)
        assert non_interactive is True
        assert should_tail is False

    def test_no_tail_flag_overrides_tty_default(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Interactive but ``--no-tail`` → exit cleanly after deploy."""
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        args = argparse.Namespace(non_interactive=False, tail=False)
        non_interactive, should_tail = cli_examples._resolve_deploy_example_modes(args)
        assert non_interactive is False
        assert should_tail is False


class TestDeployExampleAdditionalBranches:
    """Cover the remaining state-machine branches in the deploy-example
    handler — bootstrap fall-through, multi-runtime disambiguation,
    deploy-failure classification, missing positional rejection."""

    def test_missing_library_positional_returns_precheck_error(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No positionals + not --list → exit 2 with a clear message."""
        root = _seed_workspace_with_cp_device(tmp_path)
        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root),
            "--non-interactive",
        ])
        assert exit_code == cli_examples.DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED
        assert "library positional required" in capsys.readouterr().err

    def test_missing_example_positional_returns_precheck_error(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Library passed but no example → exit 2."""
        root = _seed_workspace_with_cp_device(tmp_path)
        _seed_example_library(root, "timing")
        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root),
            "timing", "--non-interactive",
        ])
        assert exit_code == cli_examples.DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED
        assert "example positional required" in capsys.readouterr().err

    def test_list_with_no_libraries_dir_returns_precheck_error(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--list`` without a libraries/ dir → exit 2."""
        root = tmp_path
        (root / "workspace.yml").write_text("")
        (root / "secrets.toml").write_text("")
        (root / "devices.yml").write_text("devices: []\n")
        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root), "--list",
        ])
        assert exit_code == cli_examples.DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED
        assert "libraries" in capsys.readouterr().err.lower()

    def test_multi_runtime_example_without_runtime_flag_exits_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An example whose ``__chumicro_runtimes__`` lists more than
        one runtime requires --runtime to disambiguate."""
        root = _seed_workspace_with_cp_device(tmp_path)
        _seed_example_library(
            root, "timing",
            example_name="universal.py",
            runtimes_marker=None,  # we'll write the marker manually
            example_body=(
                "__chumicro_runtimes__ = ('circuitpython', 'micropython')\n"
                "print('universal')\n"
            ),
        )
        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root),
            "timing", "universal", "--non-interactive",
        ])
        assert exit_code == cli_examples.DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED
        assert "multiple runtimes" in capsys.readouterr().err

    def test_multi_runtime_example_with_runtime_flag_proceeds(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--runtime`` selecting one of the example's runtimes proceeds
        to deploy."""
        root = _seed_workspace_with_cp_device(tmp_path)
        _seed_example_library(
            root, "timing",
            example_name="universal.py",
            runtimes_marker=None,
            example_body=(
                "__chumicro_runtimes__ = ('circuitpython', 'micropython')\n"
                "print('universal')\n"
            ),
        )
        transport = FakeTransport(execute_output="")
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root),
            "timing", "universal",
            "--runtime", "circuitpython", "--non-interactive",
        ])
        assert exit_code == 0

    def test_bootstrap_fall_through_when_no_device_in_tty_mode(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No device + interactive (TTY-detected) + --auto-register
        (default) → bootstrap wizard runs → device resolves → deploy
        proceeds.  Mocks _cmd_bootstrap to register a CP device."""
        root = tmp_path
        (root / "workspace.yml").write_text("")
        (root / "secrets.toml").write_text("")
        (root / "devices.yml").write_text("devices: []\n")
        _seed_example_library(root, "timing")

        # TTY mode (avoid the non-interactive default).
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

        bootstrap_calls: list[argparse.Namespace] = []

        def fake_bootstrap(args: argparse.Namespace) -> int:
            """Pretend the wizard ran and registered a CP device."""
            bootstrap_calls.append(args)
            (root / "devices.yml").write_text(
                "defaults:\n  circuitpython: pico\n"
                "devices:\n  - id: pico\n"
                "    runtime: circuitpython\n"
                "    address: /dev/cu.fake\n",
            )
            return 0

        monkeypatch.setattr(cli.examples, "_cmd_bootstrap",fake_bootstrap)
        transport = FakeTransport(execute_output="")
        _install_fake_transport(monkeypatch, transport)
        # In TTY mode the handler also tries to drop into chumicro-repl
        # after a successful deploy — short-circuit it for the test.
        import chumicro_repl.cli as repl_cli_mod
        monkeypatch.setattr(repl_cli_mod, "main", lambda _argv: 0)

        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root),
            "timing", "circuitpython_blink",
        ])
        assert exit_code == 0
        assert len(bootstrap_calls) == 1
        # Wizard called with no demo (we're about to deploy the example).
        assert bootstrap_calls[0].with_demo is False

    def test_bootstrap_canceled_exits_five(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """User cancels the wizard → exit 5 (distinct from precheck-2)."""
        root = tmp_path
        (root / "workspace.yml").write_text("")
        (root / "secrets.toml").write_text("")
        (root / "devices.yml").write_text("devices: []\n")
        _seed_example_library(root, "timing")
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(cli.examples, "_cmd_bootstrap",lambda _args: 1)

        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root),
            "timing", "circuitpython_blink",
        ])
        assert exit_code == cli_examples.DEPLOY_EXAMPLE_EXIT_WIZARD_CANCELLED

    def test_no_python_runtime_classifies_to_exit_six(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A deployer exception classified as NO_PYTHON_RUNTIME exits 6
        (the install-firmware coaching path).  Distinct from generic
        deploy-failure exit 4."""
        from chumicro_deploy.circuitpython_transport import (
            CircuitpythonTransportError,
        )

        root = _seed_workspace_with_cp_device(tmp_path)
        _seed_example_library(root, "timing")

        # Replace _make_deploy_runner so deploy_diff() raises a
        # classifiable NO_PYTHON_RUNTIME error.
        class _NoPythonDeployer:
            def deploy_diff(self, _source: object, **_kwargs: object) -> None:
                raise CircuitpythonTransportError(
                    "no python runtime detected on /dev/cu.fake",
                )

        monkeypatch.setattr(
            cli.examples, "_make_deploy_runner",
            lambda _device, *, non_interactive: _NoPythonDeployer(),
        )

        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root),
            "timing", "circuitpython_blink", "--non-interactive",
        ])
        assert exit_code == cli_examples.DEPLOY_EXAMPLE_EXIT_NO_PYTHON_RUNTIME

    def test_generic_deploy_exception_exits_four(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Any other transport error → exit 4 (generic deploy failure)."""
        from chumicro_deploy.circuitpython_transport import (
            CircuitpythonTransportError,
        )

        root = _seed_workspace_with_cp_device(tmp_path)
        _seed_example_library(root, "timing")

        class _PortBusyDeployer:
            def deploy_diff(self, _source: object, **_kwargs: object) -> None:
                raise CircuitpythonTransportError(
                    "Failed to open serial port: Resource busy",
                )

        monkeypatch.setattr(
            cli.examples, "_make_deploy_runner",
            lambda _device, *, non_interactive: _PortBusyDeployer(),
        )

        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root),
            "timing", "circuitpython_blink", "--non-interactive",
        ])
        assert exit_code == cli_examples.DEPLOY_EXAMPLE_EXIT_DEPLOY_FAILED

    def test_traceback_in_execute_output_exits_four(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A successful deploy that returns a traceback in execute_output
        → exit 4 (the result.success heuristic flips on traceback)."""
        root = _seed_workspace_with_cp_device(tmp_path)
        _seed_example_library(root, "timing")
        transport = FakeTransport(
            execute_output=(
                "Traceback (most recent call last):\n"
                "  File \"/code.py\", line 1\n"
                "RuntimeError: boom\n"
            ),
        )
        _install_fake_transport(monkeypatch, transport)

        exit_code = cli.main([
            "deploy-example", "--workspace-dir", str(root),
            "timing", "circuitpython_blink", "--non-interactive",
        ])
        assert exit_code == cli_examples.DEPLOY_EXAMPLE_EXIT_DEPLOY_FAILED
        assert "RuntimeError: boom" in capsys.readouterr().err


class TestResolveDeployLayoutAsyncRun:
    """`async def run` in app.py is rejected, not silently shimmed.

    The boot shim calls ``run()`` synchronously; an async run would be
    a coroutine that's never awaited (board boots, does nothing).  The
    auto-detect must raise an actionable error rather than ship a dead
    board or imply async is supported.
    """

    def test_async_run_raises_actionable_layout_error(
        self, tmp_path: Path,
    ) -> None:
        from chumicro_workspace.cli.deploy import (
            _DeployLayoutError,
            _resolve_deploy_layout,
        )

        (tmp_path / "app.py").write_text("async def run():\n    pass\n")

        with pytest.raises(_DeployLayoutError) as excinfo:
            _resolve_deploy_layout(
                project_dir=tmp_path,
                target_entrypoint="code.py",
                user_passed_boot_shim=False,
                user_passed_import_graph=False,
            )

        message = str(excinfo.value)
        assert "async def run()" in message
        assert "never awaited" in message
        assert "chumicro_runner" in message

    def test_sync_run_still_resolves_to_shim(self, tmp_path: Path) -> None:
        from chumicro_workspace.cli.deploy import _resolve_deploy_layout

        (tmp_path / "app.py").write_text("def run():\n    pass\n")

        layout = _resolve_deploy_layout(
            project_dir=tmp_path,
            target_entrypoint="code.py",
            user_passed_boot_shim=False,
            user_passed_import_graph=False,
        )
        assert layout.boot_shim is True


class TestResolveProjectDeploySourceGuard:
    """``resolve_project_deploy_source`` owns project *and* example.

    Exactly one of ``project_dir`` / ``example`` must be given — the
    single source owner refuses an ambiguous or empty request rather
    than silently picking a path.
    """

    def test_neither_project_nor_example_raises(self) -> None:
        from chumicro_workspace.cli.deploy import (
            resolve_project_deploy_source,
        )

        with pytest.raises(ValueError, match="exactly one"):
            resolve_project_deploy_source(
                workspace=object(), device=object(),
            )

    def test_both_project_and_example_raises(self, tmp_path: Path) -> None:
        from chumicro_workspace.cli.deploy import (
            ExampleSpec,
            resolve_project_deploy_source,
        )

        with pytest.raises(ValueError, match="exactly one"):
            resolve_project_deploy_source(
                workspace=object(),
                device=object(),
                project_dir=tmp_path,
                example=ExampleSpec(
                    library_root=tmp_path / "timing",
                    example_name="circuitpython_blink",
                    libraries_root=tmp_path,
                ),
            )


class TestResolverRefusesBootReachableResets:
    """The checked resolver scans every staged .py for top-level resets (W8)."""

    def test_staged_module_with_top_level_reset_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        from chumicro_workspace.cli import deploy as deploy_cli

        class _StubSource:
            def files(self):
                return {
                    "/code.py": b"import pkg.mod\n",
                    "/lib/pkg/mod.py": b"import machine\nmachine.reset()\n",
                }

        monkeypatch.setattr(
            deploy_cli,
            "_resolve_project_deploy_source_unchecked",
            lambda *args, **kwargs: ("flat", _StubSource()),
        )
        with pytest.raises(
            deploy_cli._DeployLayoutError, match="top level, line 2",
        ):
            deploy_cli.resolve_project_deploy_source(
                workspace=object(), device=object(), project_dir=tmp_path,
            )

    def test_in_function_reset_in_staged_module_is_allowed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        from chumicro_workspace.cli import deploy as deploy_cli

        class _StubSource:
            def files(self):
                return {
                    "/code.py": b"import pkg.mod\n",
                    "/lib/pkg/mod.py": (
                        b"import machine\n"
                        b"def recover():\n"
                        b"    machine.reset()\n"
                    ),
                }

        monkeypatch.setattr(
            deploy_cli,
            "_resolve_project_deploy_source_unchecked",
            lambda *args, **kwargs: ("flat", _StubSource()),
        )
        layout, source = deploy_cli.resolve_project_deploy_source(
            workspace=object(), device=object(), project_dir=tmp_path,
        )
        assert layout == "flat"


def _seed_with_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, description: str | None = None,
) -> None:
    """Fresh workspace with one micropython device registered via add-device."""
    (tmp_path / "workspace.yml").write_text('# machinery only\n')
    (tmp_path / "secrets.toml").write_text('')
    import chumicro_deploy
    monkeypatch.setattr(
        chumicro_deploy, "probe_device", lambda _device: fake_probe_info(),
    )
    argv = [
        "add-device", "--workspace-dir", str(tmp_path),
        "--address", "/dev/cu.old", "--runtime", "micropython",
    ]
    if description is not None:
        argv += ["--description", description]
    argv.append("lolin-s2")
    assert cli.main(argv) == 0


class TestRemoveDevice:
    def test_deletes_entry_with_yes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _seed_with_device(tmp_path, monkeypatch)
        capsys.readouterr()
        result = cli.main([
            "remove-device", "--workspace-dir", str(tmp_path), "--yes", "lolin-s2",
        ])
        assert result == 0
        assert "deleted lolin-s2" in capsys.readouterr().out
        assert "lolin-s2" not in (tmp_path / "devices.yml").read_text()

    def test_refuses_without_yes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _seed_with_device(tmp_path, monkeypatch)
        capsys.readouterr()
        result = cli.main([
            "remove-device", "--workspace-dir", str(tmp_path), "lolin-s2",
        ])
        assert result == 2
        assert "--yes" in capsys.readouterr().err
        assert "lolin-s2" in (tmp_path / "devices.yml").read_text()

    def test_missing_id_returns_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _seed_with_device(tmp_path, monkeypatch)
        result = cli.main([
            "remove-device", "--workspace-dir", str(tmp_path), "--yes", "ghost",
        ])
        assert result == 1
        assert "not found" in capsys.readouterr().err

    def test_no_devices_file_returns_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        (tmp_path / "workspace.yml").write_text('# machinery only\n')
        (tmp_path / "secrets.toml").write_text('')
        result = cli.main([
            "remove-device", "--workspace-dir", str(tmp_path), "--yes", "any",
        ])
        assert result == 1
        assert "does not exist" in capsys.readouterr().err


class TestResetDevice:
    def test_rebuilds_dropping_user_fields_keeps_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _seed_with_device(tmp_path, monkeypatch, description="Hand-typed note")
        body_before = (tmp_path / "devices.yml").read_text()
        assert "Hand-typed note" in body_before
        capsys.readouterr()
        result = cli.main([
            "reset-device", "--workspace-dir", str(tmp_path),
            "--runtime", "micropython", "--yes", "lolin-s2",
        ])
        assert result == 0
        assert "rebuilt lolin-s2" in capsys.readouterr().out
        body = (tmp_path / "devices.yml").read_text()
        assert "lolin-s2" in body
        assert "Hand-typed note" not in body  # user-owned drift dropped
        assert "ABCD1234" in body  # hardware re-derived from probe
        # defaults binding survived the remove+add round (id re-seeds it).
        assert "micropython: lolin-s2" in body

    def test_refuses_without_yes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _seed_with_device(tmp_path, monkeypatch, description="keep me")
        capsys.readouterr()
        result = cli.main([
            "reset-device", "--workspace-dir", str(tmp_path),
            "--runtime", "micropython", "lolin-s2",
        ])
        assert result == 2
        assert "--yes" in capsys.readouterr().err
        assert "keep me" in (tmp_path / "devices.yml").read_text()

    def test_missing_id_returns_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _seed_with_device(tmp_path, monkeypatch)
        result = cli.main([
            "reset-device", "--workspace-dir", str(tmp_path),
            "--yes", "ghost",
        ])
        assert result == 1
        assert "use `add-device`" in capsys.readouterr().err

    def test_probe_failure_steers_to_remove_device(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _seed_with_device(tmp_path, monkeypatch)
        import chumicro_deploy

        def boom(_device: object) -> object:
            raise RuntimeError("no board")

        monkeypatch.setattr(chumicro_deploy, "probe_device", boom)
        capsys.readouterr()
        result = cli.main([
            "reset-device", "--workspace-dir", str(tmp_path),
            "--runtime", "micropython", "--yes", "lolin-s2",
        ])
        assert result == 1
        assert "remove-device" in capsys.readouterr().err

    def test_infers_runtime_when_omitted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _seed_with_device(tmp_path, monkeypatch)
        from chumicro_workspace import cli as workspace_cli
        from chumicro_workspace import onboarding

        def fake_inference(address: str, **_kw: object) -> object:
            return onboarding.RuntimeInferenceResult(
                info=fake_probe_info(runtime="micropython"),
                runtime="micropython",
            )

        monkeypatch.setattr(
            workspace_cli.devices, "probe_with_runtime_inference", fake_inference,
        )
        capsys.readouterr()
        result = cli.main([
            "reset-device", "--workspace-dir", str(tmp_path),
            "--yes", "lolin-s2",
        ])
        assert result == 0
        out = capsys.readouterr().out
        assert "auto-detected runtime = micropython" in out


class TestDeployExampleLibraryResolution:
    """deploy-example accepts the short name or the import-name form."""

    def _make_lib(self, root: Path, name: str) -> None:
        example = root / name / "examples" / "telemetry.py"
        example.parent.mkdir(parents=True, exist_ok=True)
        example.write_text("x = 1\n", encoding="utf-8")

    def test_resolves_exact_import_name(self, tmp_path: Path) -> None:
        from chumicro_workspace.cli.examples import _resolve_library_dir

        self._make_lib(tmp_path, "chumicro_mqtt")
        assert _resolve_library_dir(tmp_path, "chumicro_mqtt") == (
            tmp_path / "chumicro_mqtt"
        )

    def test_resolves_short_name_to_prefixed_dir(self, tmp_path: Path) -> None:
        # Workspace layout: libraries/chumicro_mqtt/, user types "mqtt".
        from chumicro_workspace.cli.examples import _resolve_library_dir

        self._make_lib(tmp_path, "chumicro_mqtt")
        assert _resolve_library_dir(tmp_path, "mqtt") == (
            tmp_path / "chumicro_mqtt"
        )

    def test_resolves_mono_repo_short_dir(self, tmp_path: Path) -> None:
        # Mono-repo layout: libraries/mqtt/, user types "mqtt".
        from chumicro_workspace.cli.examples import _resolve_library_dir

        self._make_lib(tmp_path, "mqtt")
        assert _resolve_library_dir(tmp_path, "mqtt") == tmp_path / "mqtt"

    def test_unknown_library_returns_none(self, tmp_path: Path) -> None:
        from chumicro_workspace.cli.examples import _resolve_library_dir

        assert _resolve_library_dir(tmp_path, "nope") is None

    def test_deploy_example_paths_accepts_short_name(self, tmp_path: Path) -> None:
        import argparse

        from chumicro_workspace.cli.examples import _resolve_deploy_example_paths

        self._make_lib(tmp_path, "chumicro_mqtt")
        args = argparse.Namespace(library="mqtt", example_name="telemetry")
        paths = _resolve_deploy_example_paths(tmp_path, args)
        assert paths.library_root == tmp_path / "chumicro_mqtt"
        assert paths.stem == "telemetry"
