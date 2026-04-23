"""Hardware-gated tests for Deployer.deploy + transport.deploy_files.

These are the Slice 1d acceptance tests — they exercise the real
``MicropythonTransport.deploy_files`` and
``CircuitpythonTransport.deploy_files`` paths against plugged-in
boards.  Host-side fakes cover the logic; these confirm the
integration with mpremote, pyserial, and the CIRCUITPY drive.

Skipped cleanly when ``devices.yml`` has no matching device.
"""

from __future__ import annotations

from pathlib import Path

from chumicro_deploy import Deployer, Device, FileMapSource

# scripts/ is on sys.path via root conftest.py.
from device_config import DeviceEntry  # type: ignore[import-not-found]


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
