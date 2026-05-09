"""Hardware-gated tests for Deployer.deploy + transport.deploy_files.

Exercises the real ``MicropythonTransport.deploy_files`` and
``CircuitpythonTransport.deploy_files`` paths against plugged-in
boards.  Host-side fakes cover the logic; these confirm the
integration with mpremote, pyserial, and the CIRCUITPY drive.

Skipped cleanly when ``devices.yml`` has no matching device.
"""

from __future__ import annotations

from pathlib import Path

from chumicro_deploy import (
    Deployer,
    Device,
    DeviceEntry,
    DirectorySource,
    FileMapSource,
)


def _build_device(entry: DeviceEntry, deploy_mode: str) -> Device:
    """Translate a chumicro DeviceEntry into a public ``Device``."""
    return Device(
        transport=entry.runtime,
        address=entry.address,
        baudrate=entry.serial_baudrate,
        deploy_mode=deploy_mode,
        circuitpy_drive_path=(
            Path(entry.circuitpy_drive_path) if entry.circuitpy_drive_path else None
        ),
    )


def test_micropython_ram_deploy_runs_entrypoint(
    micropython_device: DeviceEntry,
) -> None:
    """MP mount-mode deploy — file writes, mount, exec, output round-trip."""
    device = _build_device(micropython_device, deploy_mode="ram")
    deployer = Deployer(device)
    staged: list[str] = []
    source = FileMapSource(
        {"/main.py": "print('chu-deploy-mp-ram')"}, entrypoint="/main.py"
    )
    result = deployer.deploy(source, on_file_staged=staged.append)
    assert result.success, result.execute_output
    assert "chu-deploy-mp-ram" in result.execute_output
    assert staged == ["/main.py"]
    assert result.traceback is None


def test_micropython_deploy_with_lib_module(
    micropython_device: DeviceEntry,
) -> None:
    """Multi-file deploy — a /lib helper module imported by the entrypoint."""
    device = _build_device(micropython_device, deploy_mode="ram")
    deployer = Deployer(device)
    source = FileMapSource(
        {
            "/main.py": (
                "from greeter import greet\n"
                "print(greet('chu'))\n"
            ),
            "/lib/greeter.py": (
                "def greet(name):\n    return 'hi-' + name\n"
            ),
        },
        entrypoint="/main.py",
    )
    result = deployer.deploy(source)
    assert result.success, result.execute_output
    assert "hi-chu" in result.execute_output


def test_micropython_copy_deploy_runs_entrypoint(
    micropython_device: DeviceEntry,
) -> None:
    """MP copy-mode deploy — files land in the device's real filesystem.

    Exercises the ``mpremote fs cp -r`` path (as opposed to mount-mode
    tested above), so the deploy covers the persistent-write code path
    including the post-copy raw-REPL re-open.
    """
    device = _build_device(micropython_device, deploy_mode="flash")
    deployer = Deployer(device)
    source = FileMapSource(
        {"/main.py": "print('chu-deploy-mp-copy')"}, entrypoint="/main.py"
    )
    result = deployer.deploy(source)
    assert result.success, result.execute_output
    assert "chu-deploy-mp-copy" in result.execute_output
    assert result.traceback is None


def test_circuitpython_ram_deploy_runs_entrypoint(
    circuitpython_device: DeviceEntry,
) -> None:
    """CP RAM-mode deploy — inline exec via chunked raw REPL, no drive.

    RAM mode runs the files through
    :func:`build_circuitpython_deploy_scripts` which registers every
    non-entrypoint file as a ``sys.modules`` entry via the
    class-as-module pattern, then ``exec()``s the entrypoint as
    ``__main__``.  No CIRCUITPY drive or soft-reboot is involved.
    """
    device = _build_device(circuitpython_device, deploy_mode="ram")
    deployer = Deployer(device)
    staged: list[str] = []
    source = FileMapSource(
        {"/code.py": "print('chu-deploy-cp-ram')"}, entrypoint="/code.py"
    )
    result = deployer.deploy(source, on_file_staged=staged.append)
    assert result.success, result.execute_output
    assert "chu-deploy-cp-ram" in result.execute_output
    assert staged == ["/code.py"]
    assert result.traceback is None


def test_circuitpython_ram_deploy_with_lib_module(
    circuitpython_device: DeviceEntry,
) -> None:
    """CP RAM deploy registers a /lib module as importable inline.

    Covers the chunked bootstrap prelude (helper + stub + population
    scripts) that both the test-harness and deploy builders share,
    and the deferred-import retry path that resolves relative imports
    between sibling modules.
    """
    device = _build_device(circuitpython_device, deploy_mode="ram")
    deployer = Deployer(device)
    source = FileMapSource(
        {
            "/code.py": (
                "from greeter import greet\n"
                "print(greet('cp-ram'))\n"
            ),
            "/lib/greeter.py": (
                "def greet(name):\n    return 'hi-' + name\n"
            ),
        },
        entrypoint="/code.py",
    )
    result = deployer.deploy(source)
    assert result.success, result.execute_output
    assert "hi-cp-ram" in result.execute_output


def test_deploy_with_directory_source(
    circuitpython_device: DeviceEntry,
    tmp_path: Path,
) -> None:
    """End-to-end deploy sourced from a directory on disk.

    Unlike the :class:`FileMapSource`-based tests above, this exercises
    :class:`DirectorySource`'s lazy-walk path — the walk happens once,
    inside ``Deployer.deploy``'s ``source.files()`` call.
    """
    project = tmp_path / "proj"
    project.mkdir()
    (project / "code.py").write_text("from helper import shout\nprint(shout('ok'))\n")
    lib_dir = project / "lib"
    lib_dir.mkdir()
    (lib_dir / "helper.py").write_text("def shout(word):\n    return word.upper() + '!'\n")

    device = _build_device(circuitpython_device, deploy_mode="ram")
    deployer = Deployer(device)
    source = DirectorySource(project, entrypoint="/code.py")
    result = deployer.deploy(source)
    assert result.success, result.execute_output
    assert "OK!" in result.execute_output


def test_circuitpython_flash_deploy_runs_entrypoint(
    circuitpython_flash_device: DeviceEntry,
) -> None:
    """CP flash-mode deploy — write to CIRCUITPY drive + exec via raw REPL."""
    device = _build_device(circuitpython_flash_device, deploy_mode="flash")
    deployer = Deployer(device)
    source = FileMapSource(
        {"/code.py": "print('chu-deploy-cp-flash')"}, entrypoint="/code.py"
    )
    result = deployer.deploy(source)
    assert result.success, result.execute_output
    assert "chu-deploy-cp-flash" in result.execute_output


def test_circuitpython_flash_deploy_with_lib_module(
    circuitpython_flash_device: DeviceEntry,
) -> None:
    """CP flash deploy ships a /lib module alongside the entrypoint."""
    device = _build_device(circuitpython_flash_device, deploy_mode="flash")
    deployer = Deployer(device)
    source = FileMapSource(
        {
            "/code.py": (
                "from greeter import greet\n"
                "print(greet('cp'))\n"
            ),
            "/lib/greeter.py": (
                "def greet(name):\n    return 'hi-' + name\n"
            ),
        },
        entrypoint="/code.py",
    )
    result = deployer.deploy(source)
    assert result.success, result.execute_output
    assert "hi-cp" in result.execute_output
