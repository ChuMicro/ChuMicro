"""Test fakes and seeders for ``chumicro-workspace``.

Provides host-side helpers for tests that drive ``cli.main([...])``
end-to-end against a temp directory:

- :func:`seed_workspace` — write the minimal ``workspace.yml`` +
  ``secrets.toml`` + ``devices.yml`` trio at *tmp_path*.
- :func:`seed_project` — add ``projects/<name>/`` with a config TOML
  and ``code.py`` / ``main.py`` entrypoints.
- :class:`FakePort` — pyserial ``ListPortInfo`` shim with ``device``
  and ``description`` fields, for ``list_ports.comports`` patches.
- :class:`FakeSubprocessRunner` — callable that records every
  ``subprocess.run`` invocation and returns canned
  :class:`subprocess.CompletedProcess` results.
- :func:`fake_probe_info` — object matching the shape
  :func:`chumicro_deploy.probe_device` returns, with firmware-floor-
  passing defaults so tests that don't care about the floor don't
  trip the warning path.

Mirrors the structure of :mod:`chumicro_deploy.testing` so contributors
moving between the two packages see the same shapes.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from chumicro_deploy import DeviceImplementation

__all__ = [
    "FakePort",
    "FakeProbeInfo",
    "FakeSubprocessCall",
    "FakeSubprocessRunner",
    "fake_probe_info",
    "seed_project",
    "seed_workspace",
]


def seed_workspace(
    tmp_path: Path,
    *,
    runtime: str = "micropython",
    device_id: str | None = None,
) -> Path:
    """Create a minimal workspace at *tmp_path* and return the root.

    Writes ``workspace.yml`` (machinery placeholder), ``secrets.toml``
    (wifi block with placeholder credentials), and ``devices.yml`` with
    a single device targeting ``/dev/cu.fake``.

    Args:
        tmp_path: Directory to populate (typically pytest's ``tmp_path``).
        runtime: ``"micropython"`` or ``"circuitpython"``.  Drives the
            default ``device_id`` and the ``defaults:`` block in
            ``devices.yml``.
        device_id: Override the registered device id.  Defaults to
            ``"lolin-s2"`` for micropython, ``"pico-w-cp"`` for
            circuitpython.
    """
    if device_id is None:
        device_id = "pico-w-cp" if runtime == "circuitpython" else "lolin-s2"
    (tmp_path / "workspace.yml").write_text("# machinery only\n")
    (tmp_path / "secrets.toml").write_text(
        "[wifi]\nhostname_prefix = 'chu-'\npassword = 'shh'\n",
    )
    (tmp_path / "devices.yml").write_text(
        f"defaults:\n"
        f"  {runtime}: {device_id}\n"
        f"devices:\n"
        f"  - id: {device_id}\n"
        f"    runtime: {runtime}\n"
        f"    address: /dev/cu.fake\n",
    )
    return tmp_path


def seed_project(workspace_root: Path, name: str = "back-porch") -> Path:
    """Add ``projects/<name>/`` under *workspace_root* and return its dir.

    Carries both ``code.py`` (CircuitPython convention) and ``main.py``
    (MicroPython convention) so the deploy command's runtime-derived
    entrypoint resolves cleanly regardless of the test fixture's chosen
    transport.

    *name* may be slash-form (``"upstairs/bedroom_sensor"``) — the
    intermediate parent directories are created automatically.
    """
    project_dir = workspace_root / "projects" / name
    project_dir.mkdir(parents=True)
    (project_dir / "project_config.toml").write_text(
        "[wifi]\nssid = 'HomeNet'\n",
    )
    (project_dir / "code.py").write_text("print('hello from project')\n")
    (project_dir / "main.py").write_text("print('hello from project')\n")
    return project_dir


@dataclass(frozen=True)
class FakePort:
    """Stand-in for ``serial.tools.list_ports_common.ListPortInfo``.

    Two attributes are load-bearing for the workspace CLI's
    ``list_ports.comports`` callers: ``device`` (the ``/dev/cu.*`` path)
    and ``description`` (the user-facing label).  Everything else the
    real ``ListPortInfo`` carries is unused.
    """

    device: str
    description: str = ""


@dataclass
class FakeSubprocessCall:
    """One recorded invocation of :class:`FakeSubprocessRunner`."""

    args: list[str]
    kwargs: dict[str, Any]

    @property
    def cwd(self) -> Path | str | None:
        """The ``cwd=`` kwarg the call was made with, or ``None``."""
        return self.kwargs.get("cwd")


class FakeSubprocessRunner:
    """Recording stand-in for :func:`subprocess.run`.

    Install via ``monkeypatch.setattr``::

        runner = FakeSubprocessRunner()
        monkeypatch.setattr(cli.subprocess, "run", runner)
        ...
        assert runner.calls[0].args == [sys.executable, "-m", "pytest"]
        assert runner.calls[0].cwd == workspace_root

    Every call appends a :class:`FakeSubprocessCall` to :attr:`calls`
    and returns a :class:`subprocess.CompletedProcess`.  Configure the
    return shape via constructor kwargs:

    - *returncode*: single returncode for every call (default ``0``).
    - *returncodes*: list of returncodes consumed in order — the first
      call returns ``returncodes[0]``, the second returns
      ``returncodes[1]``, etc.  Falls back to *returncode* once the
      list runs out.  Use this to script "ruff fails, then
      chumicro-checks succeeds" paths.
    - *stdout* / *stderr*: canned strings copied into every
      ``CompletedProcess``.
    """

    def __init__(
        self,
        *,
        returncode: int = 0,
        returncodes: list[int] | None = None,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.calls: list[FakeSubprocessCall] = []
        self._returncode = returncode
        self._returncodes = list(returncodes) if returncodes else []
        self._stdout = stdout
        self._stderr = stderr

    def __call__(
        self, args: list[str], **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(FakeSubprocessCall(args=list(args), kwargs=dict(kwargs)))
        code = self._returncodes.pop(0) if self._returncodes else self._returncode
        return subprocess.CompletedProcess(args, code, self._stdout, self._stderr)


@dataclass(frozen=True)
class FakeProbeInfo:
    """Mimics the shape :func:`chumicro_deploy.probe_device` returns."""

    implementation: DeviceImplementation | None
    board_id: str
    uid: str


def fake_probe_info(
    *,
    runtime: str = "micropython",
    machine: str = "Lolin S2",
    uid: str = "ABCD1234",
    board_id: str = "lolin_s2",
    version: str = "1.27.0",
    with_implementation: bool = True,
) -> FakeProbeInfo:
    """Build a probe-info object for tests of probe-driven commands.

    Default *version* is at the supported floor for ``micropython`` so
    tests that don't care about firmware support don't trip the
    firmware-floor warning path.  Tests that exercise the floor pass a
    lower or runtime-specific *version*.

    Pass ``with_implementation=False`` to simulate a board where the
    probe couldn't read an implementation marker — the returned object
    has ``implementation=None`` and empty ``board_id`` / ``uid``,
    matching what production code returns in that branch.
    """
    from chumicro_deploy import DeviceImplementation  # noqa: PLC0415

    if not with_implementation:
        return FakeProbeInfo(implementation=None, board_id="", uid="")
    return FakeProbeInfo(
        implementation=DeviceImplementation(
            name=runtime, version=version, machine=machine, uid=uid,
        ),
        board_id=board_id,
        uid=uid,
    )
