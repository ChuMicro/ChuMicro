"""Deploy-time mode resolution and the inputs it reads.

:func:`resolve_deploy_mode` is pure policy — given the configured
mode and the resolution unit's inputs, it returns the effective mode
plus an optional human-readable message when a requested RAM mode
was overridden to flash.  One rule, byte-identical for every caller:
the unit/functional distinction is expressed by how each caller
scopes ``staged_files`` and ``resolution_unit``, never by a branch
in the policy.

Public API:

* :func:`resolve_deploy_mode` — pure policy: given the configured mode
  and the resolution unit's inputs, return the effective mode plus an
  optional human-readable message when a requested RAM mode was
  overridden to flash.
* :class:`DeviceCaps` — static board capabilities the policy reads.
* :func:`find_libraries_requiring_flash` — walks a list of host paths
  to find every unique containing ``pyproject.toml``, reads
  ``[tool.chumicro].requires_flash`` from each, returns the names
  of the libraries flagged ``true``.  Host-paths-in /
  library-names-out so callers can build the list from any source
  shape; the result is a sorted list of pip-name-shaped strings ready
  to interpolate into a message.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .protocol import DeployMode


@dataclass(frozen=True)
class DeviceCaps:
    """Static capabilities of a deploy target relevant to mode resolution.

    There are exactly two deploy modes and flash is always available
    (every board can write its own filesystem — it is the
    production-shaped path), so the only real degree of freedom is
    whether the board can run RAM mode at all.  A struct rather than a
    bare bool so a second capability can be added later without
    re-threading every resolver call site; today it carries one field
    with no producer setting it ``False`` (no known board needs it).
    """

    supports_ram_mode: bool = True


def resolve_deploy_mode(
    configured_mode: str,
    *,
    staged_files: list[str],
    device_caps: DeviceCaps,
    requires_flash_libs: list[str],
    resolution_unit: str | None,
    force: str | None,
) -> tuple[str, str | None]:
    """Resolve the effective deploy mode for one resolution unit.

    Pure policy — no I/O, no emission.  The caller computes the inputs
    (the dependency-closure walk for *requires_flash_libs*, the staged
    file set for *staged_files*), surfaces the returned message, and
    applies the mode.  A *resolution unit* is one deploy for the
    :class:`~chumicro_deploy.Deployer` or one library's test suite for
    the on-device sweep.

    Two inputs have opposite scoping rules, and that — not a branch —
    is the whole subtlety:

    * *requires_flash_libs* is **always the full transitive dependency
      closure**.  ``requires_flash`` means "OOMs on import in RAM on a
      small board"; the import happens regardless of test shape, so it
      cannot be scoped down.
    * *staged_files* is **caller-scoped**: the full closure for
      functional / app-deploy callers (a functional test genuinely
      uses a dependency's data file), the library-under-test's own
      ``src`` only for the unit sweep (a pure unit test cannot reach a
      dependency's data-file code path, so a dropped dependency asset
      is harmless and must not poison every dependent suite).

    *resolution_unit* is the library a "you should declare
    ``requires_flash``" recommendation would name, or ``None`` for an
    app deploy with no single owning library (then no recommendation
    is emitted).

    Returns ``(mode, message_or_None)``.  The message is non-``None``
    only when a requested RAM mode was overridden to flash; the caller
    emits it and continues — never a silent skip.

    Resolution order:

    1. *force* set → that mode, no message (the explicit "I know what
       I'm doing" escape hatch).
    2. RAM requested but *device_caps* says the board cannot RAM →
       flash.
    3. RAM requested and the dependency closure carries a
       ``requires_flash`` library → flash.  When *resolution_unit* is
       set and is not itself flagged, the message also recommends that
       library declare ``requires_flash`` so future runs skip the
       discovery (the resolver never edits ``pyproject.toml``).
    4. RAM requested and *staged_files* contains a non-``.py`` data
       file → flash.  RAM-mode deploy is not a persistent filesystem
       write (CircuitPython is a raw-REPL ``exec()`` with no device
       filesystem; MicroPython is a host mount), so a non-``.py``
       asset is not reliably on the device — switch rather than risk a
       silent drop.
    5. Otherwise → *configured_mode* unchanged (a RAM preference stays
       RAM).
    """
    if force is not None:
        return force, None

    if configured_mode != DeployMode.RAM:
        return configured_mode, None

    if not device_caps.supports_ram_mode:
        return DeployMode.FLASH, (
            "chumicro-deploy: switching to flash mode — this device does "
            "not support RAM mode."
        )

    if requires_flash_libs:
        message = (
            f"chumicro-deploy: switching to flash mode — "
            f"{', '.join(requires_flash_libs)} declare `[tool.chumicro] "
            f"requires_flash = true` (heavy parsers / state machines / "
            f"recv buffers often OOM in RAM mode on smaller boards). "
            f"Pass force_deploy_mode='ram' to bypass."
        )
        if resolution_unit is not None and resolution_unit not in requires_flash_libs:
            message += (
                f" {resolution_unit} pulls a flash-only library in via its "
                f"dependency closure — declare `[tool.chumicro] "
                f"requires_flash = true` in its pyproject.toml so future "
                f"runs skip this discovery."
            )
        return DeployMode.FLASH, message

    data_files = sorted(name for name in staged_files if not name.endswith(".py"))
    if data_files:
        return DeployMode.FLASH, (
            f"chumicro-deploy: switching to flash mode — staged set "
            f"includes non-.py data file(s) ({', '.join(data_files)}) "
            f"that RAM-mode deploy cannot reliably carry to the device. "
            f"Pass force_deploy_mode='ram' to bypass."
        )

    return configured_mode, None


def find_libraries_requiring_flash(host_paths: list[Path]) -> list[str]:
    """Return library names with ``[tool.chumicro].requires_flash = true``.

    Walks each path in *host_paths* up the directory tree until a
    ``pyproject.toml`` is found, reads its
    ``[tool.chumicro].requires_flash`` flag, and collects the
    ``[project].name`` values of every flagged library.  Skips paths
    with no containing pyproject and pyprojects that fail to parse —
    pre-flight is best-effort, not authoritative.

    Args:
        host_paths: Filesystem paths the deploy graph drew files
            from (typically :meth:`ImportGraphSource.host_paths`).

    Returns:
        Sorted list of unique pip-name-shaped library names
        (``["chumicro-mqtt", "chumicro-requests"]``).  Empty list
        when no flagged library is in the graph.
    """
    flagged: set[str] = set()
    seen_pyprojects: set[Path] = set()
    for path in host_paths:
        pyproject = _find_pyproject(path)
        if pyproject is None or pyproject in seen_pyprojects:
            continue
        seen_pyprojects.add(pyproject)
        data = _load_pyproject(pyproject)
        if data is None:
            continue
        if not data.get("tool", {}).get("chumicro", {}).get("requires_flash", False):
            continue
        name = data.get("project", {}).get("name")
        if name:
            flagged.add(name)
    return sorted(flagged)


def _find_pyproject(start: Path) -> Path | None:
    """Walk up from *start* until a ``pyproject.toml`` is found.

    Returns the first ``pyproject.toml`` whose parent is an ancestor
    of *start*, or ``None`` when the walk reaches the filesystem root
    without finding one.
    """
    for ancestor in [start, *start.parents]:
        candidate = ancestor / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def _load_pyproject(pyproject: Path) -> dict | None:
    """Parse *pyproject* once and return its full document, or ``None``.

    Pre-flight is best-effort: parse errors and unreadable files yield
    ``None`` so callers fall through to "RAM mode is fine."
    """
    try:
        with open(pyproject, "rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None
