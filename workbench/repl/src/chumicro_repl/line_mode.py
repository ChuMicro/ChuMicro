"""Line-mode REPL — prompt_toolkit-driven input + per-device history.

Phase 7 of the workspace-ecosystem workstream (Slice 1a of the
REPL playground roadmap, `plans/workstreams/repl-playground.md`).

The default `chumicro-repl` interactive loop is byte-passthrough:
keystrokes go straight to the device, output streams back.  That's
right for raw-REPL framing, paste-mode, and other byte-exact
flows, but it loses the host-side affordances every modern shell
ships — cursor edit, history search, persistent up-arrow recall.

Line mode interposes a `prompt_toolkit.PromptSession` between
the user and the device.  Per-line:

1. ``prompt_toolkit`` reads a complete line with cursor edit,
   history navigation, and ``Ctrl-R`` reverse search.
2. Lines starting with ``:`` route through the command parser
   (Slice 1b — only ``:help`` / ``:quit`` registered for 1a).
3. Other lines ship to the device; subsequent serial output
   prints back to the user.

History is persistent at
``~/.chumicro-repl/history/<sanitized-address>/history.txt`` so a
session on ``back-porch`` doesn't pollute one on ``greenhouse``.

This module is independent from :mod:`chumicro_repl.tui` —
:func:`run_line_mode` is the analogue of
:func:`chumicro_repl.tui.run_loop` for the line-mode path.  The
CLI's ``--mode`` flag picks one or the other.
"""

from __future__ import annotations

import re
import time as _time_module
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, cast

from ._serial import SerialPort, TimeSource
from .framing import Utf8StreamDecoder
from .highlight import DEFAULT_THEME, Theme
from .patterns import StreamingPatternDetector

if TYPE_CHECKING:  # pragma: no cover — type-only
    from prompt_toolkit import PromptSession

#: Per-line drain window — how long to wait after sending a line
#: for the device to print its response before re-prompting.  The
#: friendly REPL on a healthy board responds in tens of ms; a slow
#: import or long computation can take seconds.  We poll throughout
#: the window and exit early when ``in_waiting`` settles to zero.
_DRAIN_WINDOW_SECONDS: float = 1.5

#: Inner poll interval inside the drain window.  Short enough to
#: keep the prompt feeling instantaneous; long enough not to peg a
#: CPU.
_DRAIN_POLL_INTERVAL: float = 0.01

#: Quiet-period before we declare the device "done responding."
#: The device may emit output in bursts (e.g. a chunked print);
#: we keep draining as long as bytes keep arriving and only break
#: out after this many seconds of no new input.
_DRAIN_SETTLE_SECONDS: float = 0.05

#: Default location for per-device history files.  Each device gets
#: its own subdirectory keyed off a sanitized form of the serial
#: address — ``/dev/cu.usbmodem1101`` → ``dev_cu_usbmodem1101``.
DEFAULT_HISTORY_ROOT: Path = Path.home() / ".chumicro-repl" / "history"

#: Prefix that turns a line into a `:command`.  Plain shell convention.
COMMAND_PREFIX: str = ":"

#: Regex for sanitizing a serial address into a filesystem path
#: segment.  Keeps alphanumerics + underscore + dash; collapses
#: runs of anything else into a single underscore.  Idempotent on
#: already-clean inputs.
_SANITIZE_PATTERN = re.compile(r"[^A-Za-z0-9_\-]+")


def sanitize_address(address: str) -> str:
    """Map *address* to a safe filesystem path segment.

    ``/dev/cu.usbmodem1101`` → ``dev_cu_usbmodem1101``.
    ``COM3`` → ``COM3``.  Empty / non-string inputs degrade to
    ``"unknown_device"`` so the history root is always creatable.
    """
    if not address:
        return "unknown_device"
    cleaned = _SANITIZE_PATTERN.sub("_", address).strip("_")
    return cleaned or "unknown_device"


def history_path_for(
    address: str,
    *,
    root: Path | None = None,
) -> Path:
    """Return the persistent-history path for *address*.

    Creates the parent directory if needed (mode 0o700 — the file
    may carry session secrets so reusing the user's home defaults
    is safer than dropping it world-readable in a temp dir).
    """
    base = root if root is not None else DEFAULT_HISTORY_ROOT
    target = base / sanitize_address(address) / "history.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.parent.chmod(0o700)
    except OSError:  # pragma: no cover — best-effort on filesystems without chmod
        pass
    return target


# ---------------------------------------------------------------------------
# Command registry
# ---------------------------------------------------------------------------


#: Signature: ``(line, output) -> True | False``.  Return False to
#: ask the loop to exit.  Slice 1a registers two commands;
#: Slice 1b layers `:edit` / `:save` / `:load` / `:snippets` on
#: top of the same registry.
CommandHandler = Callable[[str, TextIO], bool]


def _cmd_quit(_line: str, output: TextIO) -> bool:
    """``:quit`` — exit the line-mode loop without rebooting the device."""
    output.write("line-mode: bye\n")
    output.flush()
    return False


def _cmd_help(_line: str, output: TextIO) -> bool:
    """``:help`` — list registered commands."""
    output.write("commands:\n")
    for name, handler in sorted(BUILTIN_COMMANDS.items()):
        doc = (handler.__doc__ or "").splitlines()[0].strip()
        output.write(f"  :{name:<10}{doc}\n")
    output.flush()
    return True


#: Built-in command set for Slice 1a.  Slice 1b extends.
BUILTIN_COMMANDS: dict[str, CommandHandler] = {
    "help": _cmd_help,
    "quit": _cmd_quit,
}


def _split_command(line: str) -> tuple[str, str]:
    """Split a ``:command rest...`` line into (name, rest)."""
    body = line[len(COMMAND_PREFIX):].strip()
    if not body:
        return "", ""
    parts = body.split(None, 1)
    name = parts[0]
    rest = parts[1] if len(parts) > 1 else ""
    return name, rest


# ---------------------------------------------------------------------------
# Drain helpers
# ---------------------------------------------------------------------------


def _drain_serial(
    port: SerialPort,
    *,
    output: TextIO,
    decoder: Utf8StreamDecoder,
    detector: StreamingPatternDetector,
    theme: Theme,
    time: TimeSource,
    window_seconds: float,
    settle_seconds: float,
) -> None:
    """Read every byte the device emits within *window_seconds*.

    Two-phase wait: keep reading as long as bytes arrive; if the
    serial buffer goes empty, wait *settle_seconds* before declaring
    the response complete.  Bounded by *window_seconds* total so a
    runaway-print loop on the device doesn't lock the prompt.
    """
    from .tui import _render  # noqa: PLC0415 — avoid circular import at module load

    deadline = time.monotonic() + window_seconds
    last_read_at = time.monotonic()
    while True:
        if time.monotonic() >= deadline:
            return
        try:
            available = port.in_waiting
        except OSError:  # pragma: no cover — port dropped mid-drain
            return
        if not available:
            if time.monotonic() - last_read_at >= settle_seconds:
                return
            time.sleep(_DRAIN_POLL_INTERVAL)
            continue
        try:
            chunk = port.read(available)
        except OSError:  # pragma: no cover — port dropped mid-drain
            return
        last_read_at = time.monotonic()
        decoded = decoder.decode(chunk)
        if decoded:
            matches = detector.feed(decoded)
            output.write(_render(decoded, matches, detector, theme))
            output.flush()


# ---------------------------------------------------------------------------
# Line-mode entry point
# ---------------------------------------------------------------------------


def run_line_mode(
    port: SerialPort,
    *,
    output: TextIO,
    address: str,
    history_root: Path | None = None,
    commands: Mapping[str, CommandHandler] | None = None,
    prompt: str = ">>> ",
    welcome_banner: str = "",
    theme: Theme | None = None,
    time: TimeSource | None = None,
    prompt_session: object | None = None,
    drain_window_seconds: float = _DRAIN_WINDOW_SECONDS,
    drain_settle_seconds: float = _DRAIN_SETTLE_SECONDS,
) -> int:
    """Run a line-mode REPL session.

    Reads complete lines via ``prompt_toolkit`` (host-side cursor
    edit, history navigation, reverse search), ships them to the
    device, and renders the response with the same pattern-detector
    + traceback highlighter the passthrough TUI uses.  Returns 0 on
    a clean exit (``:quit`` / EOF / Ctrl-C at the empty prompt).

    Args:
        port: Open :class:`SerialPort`.  Caller owns close.
        output: Where rendered serial output goes (stdout in normal
            use; tests inject a StringIO).
        address: Serial address — used to derive the per-device
            persistent history file.
        history_root: Override the history root.  Defaults to
            :data:`DEFAULT_HISTORY_ROOT`; tests pass a tmp_path.
        commands: Override / extend the built-in `:command` table.
            Defaults to :data:`BUILTIN_COMMANDS`.  Slice 1b will
            ship a richer set via this parameter.
        prompt: Text shown to the user before each input.
        welcome_banner: Local text written before the loop starts.
        theme: Color theme for serial-output highlighting.
        time: Injectable :class:`TimeSource` for the drain window.
        prompt_session: Override `prompt_toolkit.PromptSession` (tests
            pass a fake; CLI passes ``None`` and the real one is
            constructed against the per-device history file).
        drain_window_seconds: Hard upper bound on the per-line wait
            for device output.  Defaults to 1.5 s.
        drain_settle_seconds: Quiet-period before declaring the
            device done responding.  Defaults to 50 ms.

    Returns:
        ``0`` on a clean exit.  Other failures raise.
    """
    active_time: TimeSource = (
        time if time is not None else cast(TimeSource, _time_module)
    )
    active_theme = theme if theme is not None else DEFAULT_THEME
    command_table: Mapping[str, CommandHandler] = (
        commands if commands is not None else BUILTIN_COMMANDS
    )
    decoder = Utf8StreamDecoder()
    detector = StreamingPatternDetector()

    if welcome_banner:
        output.write(welcome_banner)
        output.flush()

    # Print whatever the device has already buffered before we
    # block on input — usually the friendly REPL banner / prompt
    # the device emitted in response to the connect.
    _drain_serial(
        port,
        output=output,
        decoder=decoder,
        detector=detector,
        theme=active_theme,
        time=active_time,
        window_seconds=0.4,
        settle_seconds=drain_settle_seconds,
    )

    session: PromptSession[str] = (
        cast("PromptSession[str]", prompt_session)
        if prompt_session is not None
        else _build_prompt_session(address=address, history_root=history_root)
    )

    while True:
        try:
            line = session.prompt(prompt)
        except (EOFError, KeyboardInterrupt):
            output.write("\nline-mode: bye\n")
            output.flush()
            return 0
        if not line:
            continue
        if line.startswith(COMMAND_PREFIX):
            name, _rest = _split_command(line)
            handler = command_table.get(name)
            if handler is None:
                output.write(
                    f"line-mode: unknown command :{name!r}.  "
                    f"Try :help.\n",
                )
                output.flush()
                continue
            keep_running = handler(line, output)
            if not keep_running:
                return 0
            continue
        try:
            port.write((line + "\r\n").encode("utf-8"))
        except OSError as error:  # pragma: no cover — port dropped mid-line
            output.write(f"line-mode: write failed: {error!r}\n")
            output.flush()
            return 1
        _drain_serial(
            port,
            output=output,
            decoder=decoder,
            detector=detector,
            theme=active_theme,
            time=active_time,
            window_seconds=drain_window_seconds,
            settle_seconds=drain_settle_seconds,
        )


def _build_prompt_session(
    *,
    address: str,
    history_root: Path | None,
) -> object:
    """Construct a real ``prompt_toolkit.PromptSession`` for *address*.

    Imported lazily so the module-level cost of `chumicro_repl` doesn't
    pay for prompt_toolkit unless line mode is actually entered.
    """
    from prompt_toolkit import PromptSession  # noqa: PLC0415
    from prompt_toolkit.history import FileHistory  # noqa: PLC0415

    history_file = history_path_for(address, root=history_root)
    return PromptSession(history=FileHistory(str(history_file)))


# ---------------------------------------------------------------------------
# Welcome banner helper
# ---------------------------------------------------------------------------


def format_line_mode_banner(*, address: str) -> str:
    """One-line banner shown when the line-mode loop starts.

    Tells the user the mode they're in + the address (so they
    notice if they've connected to the wrong board) + the exit
    keystroke.
    """
    history = history_path_for(address)
    return (
        f"chumicro-repl line mode — {address}\n"
        f"history: {history}\n"
        f"  :help     list commands\n"
        f"  :quit     exit (Ctrl-D / Ctrl-C also work)\n"
    )
