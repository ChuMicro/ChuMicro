"""Line-mode REPL: prompt_toolkit-driven input + per-device history.

`chumicro-repl`'s default loop on a TTY interposes a
`prompt_toolkit.PromptSession` between the user and the device,
adding the host-side affordances every modern shell ships: cursor
edit, history search, persistent up-arrow recall.  The
byte-passthrough sibling (:mod:`chumicro_repl.tui`) covers
raw-REPL framing, paste-mode, and other byte-exact flows; the CLI's
``--mode`` flag picks one or the other (``auto`` falls back to
passthrough when stdin is piped, since line mode requires
interactive input).

Per-line:

1. ``prompt_toolkit`` reads a complete line with cursor edit,
   history navigation, and ``Ctrl-R`` reverse search.
2. Lines starting with ``:`` route through the command parser.
3. Other lines ship to the device; subsequent serial output
   prints back to the user.

Key bindings mirror ``mpremote repl`` and the passthrough TUI:

- ``Ctrl-C`` forwards ``\\x03`` to the device, which interrupts a
  runaway loop and returns the friendly REPL to ``>>>``.  The local
  input buffer is cleared at the same time.
- ``Ctrl-D`` at an empty prompt forwards ``\\x04``, which
  soft-reboots the runtime.
- ``Ctrl-X`` exits line mode without touching the device.

History is persistent at
``~/.chumicro-repl/history/<sanitized-address>/history.txt`` so a
session on ``back-porch`` doesn't pollute one on ``greenhouse``.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
import time as _time_module
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, cast

from ._serial import CTRL_C, CTRL_D, SerialPort, TimeSource
from .completion import CompletionCache, build_default_completer
from .framing import Utf8StreamDecoder
from .highlight import DEFAULT_THEME, Theme, colorize_stream_chunk
from .patterns import StreamingPatternDetector

if TYPE_CHECKING:  # pragma: no cover -type-only
    from prompt_toolkit import PromptSession
    from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent

#: Per-line drain window: how long to wait after sending a line
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
#: address (``/dev/cu.usbmodem1101`` → ``dev_cu_usbmodem1101``).
DEFAULT_HISTORY_ROOT: Path = Path.home() / ".chumicro-repl" / "history"

#: Default location for ``:save`` / ``:load`` snippet files.  Flat
#: directory keyed by name: ``:save back-porch-bringup`` lands at
#: ``~/.chumicro-repl/snippets/back-porch-bringup.py``.
DEFAULT_SNIPPETS_ROOT: Path = Path.home() / ".chumicro-repl" / "snippets"

#: Default editor for ``:edit`` when ``$EDITOR`` is unset.  ``vi`` is
#: the lowest-common-denominator install on every POSIX host.
DEFAULT_EDITOR: str = "vi"

#: Prefix that turns a line into a `:command`.  Plain shell convention.
COMMAND_PREFIX: str = ":"

#: Regex for sanitizing a serial address into a filesystem path
#: segment.  Keeps alphanumerics + underscore + dash; collapses
#: runs of anything else into a single underscore.
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

    Creates the parent directory if needed (mode 0o700, because the
    file may carry session secrets so reusing the user's home defaults
    is safer than dropping it world-readable in a temp dir).
    """
    base = root if root is not None else DEFAULT_HISTORY_ROOT
    target = base / sanitize_address(address) / "history.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.parent.chmod(0o700)
    except OSError:  # pragma: no cover -best-effort on filesystems without chmod
        pass
    return target


# ---------------------------------------------------------------------------
# Command registry + execution context
# ---------------------------------------------------------------------------


@dataclass
class LineModeContext:
    """Per-session state passed to every :command handler.

    Carries everything a richer command needs that it can't derive
    from its argument string: the live serial port, the rendering
    output stream, the snippet directory, the editor binary, and a
    rolling list of input lines that ``:save`` writes out as a
    snippet.

    The line list is updated by :func:`run_line_mode` on every
    non-command line, so handlers reading ``input_history`` see
    everything the user has shipped to the device this session in
    order.
    """

    port: SerialPort
    output: TextIO
    snippets_root: Path = field(default_factory=lambda: DEFAULT_SNIPPETS_ROOT)
    editor: str = field(
        default_factory=lambda: os.environ.get("EDITOR") or DEFAULT_EDITOR,
    )
    #: Lines the user has typed and shipped this session, in order.
    #: ``:save`` writes the (deduplicated, last-10) tail to disk.
    input_history: list[str] = field(default_factory=list)
    #: Tab-completion cache wired to :func:`run_line_mode`'s
    #: completer.  ``:rescan`` calls ``.clear()`` so the next Tab
    #: re-queries the device.  ``None`` when the loop is running
    #: without device-side completion (e.g. a test injecting its
    #: own ``prompt_session``).
    completion_cache: CompletionCache | None = None

    def send_line(self, line: str) -> None:
        """Ship *line* to the device with a CRLF; record in the history list.

        Editor- and snippet-replayed lines land in ``input_history``
        alongside manually-typed ones, in send order.
        """
        self.port.write((line + "\r\n").encode("utf-8"))
        self.input_history.append(line)


#: Signature: ``(context, rest) -> True | False``.  *rest* is the
#: substring after the command name.  Return False to ask the loop
#: to exit.
CommandHandler = Callable[["LineModeContext", str], bool]


def _cmd_quit(_context: LineModeContext, _rest: str) -> bool:
    """``:quit``: exit the line-mode loop without rebooting the device."""
    _context.output.write("line-mode: bye\n")
    _context.output.flush()
    return False


def _cmd_help(context: LineModeContext, _rest: str) -> bool:
    """``:help``: list registered commands."""
    context.output.write("commands:\n")
    for name, handler in sorted(BUILTIN_COMMANDS.items()):
        doc = (handler.__doc__ or "").splitlines()[0].strip()
        context.output.write(f"  :{name:<10}{doc}\n")
    context.output.flush()
    return True


#: Maximum number of recent input lines ``:save`` writes to disk.
#: Keeps a "save my last burst" save short enough to be useful as a
#: replay buffer; users wanting larger captures use the editor
#: handoff (``:edit`` writes to a tempfile they can save manually).
_SNIPPET_TAIL_LINES: int = 10


def _snippet_path(context: LineModeContext, name: str) -> Path:
    """Resolve a snippet name to its on-disk path.

    Names go through :func:`sanitize_address`'s rules, which keeps
    the snippet root flat without surprises from path-separator
    bytes in user-supplied names.
    """
    return context.snippets_root / f"{sanitize_address(name)}.py"


def _cmd_save(context: LineModeContext, rest: str) -> bool:
    """``:save <name>``: write the last 10 input lines to a snippet."""
    name = rest.strip()
    if not name:
        context.output.write("line-mode: usage: :save <name>\n")
        context.output.flush()
        return True
    context.snippets_root.mkdir(parents=True, exist_ok=True)
    target = _snippet_path(context, name)
    tail = context.input_history[-_SNIPPET_TAIL_LINES:]
    if not tail:
        context.output.write(
            "line-mode: nothing to save; type a line first.\n",
        )
        context.output.flush()
        return True
    target.write_text("\n".join(tail) + "\n")
    context.output.write(
        f"line-mode: saved {len(tail)} line(s) to {target}\n",
    )
    context.output.flush()
    return True


def _cmd_load(context: LineModeContext, rest: str) -> bool:
    """``:load <name>``: replay a saved snippet line-by-line to the device."""
    name = rest.strip()
    if not name:
        context.output.write("line-mode: usage: :load <name>\n")
        context.output.flush()
        return True
    target = _snippet_path(context, name)
    if not target.is_file():
        context.output.write(
            f"line-mode: snippet not found: {target}\n",
        )
        context.output.flush()
        return True
    text = target.read_text()
    lines = [line for line in text.splitlines() if line.strip() != ""]
    for line in lines:
        context.send_line(line)
    context.output.write(
        f"line-mode: replayed {len(lines)} line(s) from {target}\n",
    )
    context.output.flush()
    return True


def _cmd_snippets(context: LineModeContext, _rest: str) -> bool:
    """``:snippets``: list saved snippets."""
    if not context.snippets_root.is_dir():
        context.output.write("line-mode: no snippets saved yet\n")
        context.output.flush()
        return True
    snippets = sorted(
        path.stem
        for path in context.snippets_root.iterdir()
        if path.is_file() and path.suffix == ".py"
    )
    if not snippets:
        context.output.write("line-mode: no snippets saved yet\n")
    else:
        context.output.write(f"snippets ({context.snippets_root}):\n")
        for snippet in snippets:
            context.output.write(f"  {snippet}\n")
    context.output.flush()
    return True


def _open_editor(*, editor: str, file_path: Path) -> int:
    """Run ``$EDITOR <file_path>`` and return its exit code.

    Args:
        editor: Editor command line.  Honors shell-shaped values
            via ``shlex.split`` so projects like ``"code -w"`` work.
        file_path: File the editor opens.

    Indirection point: tests stub this so they don't shell out.
    """
    argv = shlex.split(editor) + [str(file_path)]
    completed = subprocess.run(argv, check=False)  # noqa: S603 - shlex-parsed user editor
    return completed.returncode


def _cmd_edit(context: LineModeContext, _rest: str) -> bool:
    """``:edit``: open ``$EDITOR``; ship the saved buffer to the device.

    Match IPython's ``%edit`` semantics: the editor opens with the
    last input prefilled (so the user can polish a multi-line block
    without retyping it).  On save+exit, every non-empty line ships
    to the device line-by-line.  Empty editor exit (no save / saved
    empty) is a no-op.
    """
    seed = "\n".join(context.input_history[-_SNIPPET_TAIL_LINES:])
    with tempfile.NamedTemporaryFile(
        mode="w+", suffix=".py", delete=False,
    ) as handle:
        handle.write(seed)
        if seed and not seed.endswith("\n"):
            handle.write("\n")
        tmp_path = Path(handle.name)
    try:
        try:
            editor_exit = _open_editor(editor=context.editor, file_path=tmp_path)
        except FileNotFoundError:
            context.output.write(
                f"line-mode: editor not found: {context.editor!r}; "
                f"set $EDITOR to an editor that's installed\n",
            )
            context.output.flush()
            return True
        if editor_exit != 0:
            context.output.write(
                f"line-mode: editor exited {editor_exit}; nothing shipped\n",
            )
            context.output.flush()
            return True
        text = tmp_path.read_text()
        lines = [line for line in text.splitlines() if line.strip() != ""]
        if not lines:
            context.output.write(
                "line-mode: editor buffer empty; nothing shipped\n",
            )
            context.output.flush()
            return True
        for line in lines:
            context.send_line(line)
        context.output.write(
            f"line-mode: shipped {len(lines)} line(s) from editor\n",
        )
        context.output.flush()
    finally:
        try:
            tmp_path.unlink()
        except OSError:  # pragma: no cover -tmpfile unlinks best-effort
            pass
    return True


def _cmd_rescan(context: LineModeContext, _rest: str) -> bool:
    """``:rescan``: drop the cached ``dir()`` so the next Tab re-queries.

    Use after ``import``-ing a new module or defining new names.  The
    completer otherwise serves the snapshot it took on first Tab.
    No-op (with a status line) when the loop is running without
    device-side completion.
    """
    if context.completion_cache is None:
        context.output.write(
            "line-mode: completion cache not in use (no port-backed completer)\n",
        )
        context.output.flush()
        return True
    context.completion_cache.clear()
    context.output.write(
        "line-mode: completion cache cleared; next Tab will re-query the device\n",
    )
    context.output.flush()
    return True


#: Built-in command set.
BUILTIN_COMMANDS: dict[str, CommandHandler] = {
    "edit": _cmd_edit,
    "help": _cmd_help,
    "load": _cmd_load,
    "quit": _cmd_quit,
    "rescan": _cmd_rescan,
    "save": _cmd_save,
    "snippets": _cmd_snippets,
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
# Key bindings: mirror passthrough TUI / mpremote conventions
# ---------------------------------------------------------------------------


class _ExitLineMode(Exception):  # noqa: N818 - internal control-flow sentinel, not a user-facing error
    """Ctrl-X raises this from a key binding so the main loop exits
    without rebooting the device."""


def _forward_ctrl_c(port: SerialPort) -> None:
    """Send ``\\x03`` to the device.

    Standard friendly-REPL convention: the runtime raises
    :class:`KeyboardInterrupt` and unwinds the current statement, so
    a runaway ``while True: print(...)`` snippet stops printing and
    returns control to ``>>>``.  Harmless when nothing's running.
    """
    port.write(CTRL_C)


def _forward_ctrl_d(port: SerialPort) -> None:
    """Send ``\\x04`` to the device.

    Triggers a soft reboot of the runtime.  MicroPython prints
    ``MPY: soft reboot``; CircuitPython rewinds silently.  Only bound
    when the local input buffer is empty (matches every shell on
    earth: Ctrl-D on a non-empty line is a no-op).
    """
    port.write(CTRL_D)


def build_line_mode_key_bindings(port: SerialPort) -> KeyBindings:
    """Build the prompt_toolkit key-binding table for line mode.

    Wires Ctrl-C and Ctrl-D to forward to *port* via
    :func:`_forward_ctrl_c` and :func:`_forward_ctrl_d`, and Ctrl-X
    to raise :class:`_ExitLineMode` and break out of the prompt loop
    without touching the device.  Ctrl-D fires only when the input
    buffer is empty, matching the shell convention that Ctrl-D on a
    non-empty line is a no-op.

    prompt_toolkit is imported inside the function so callers that
    never enter line mode do not pay its import cost.
    """
    from prompt_toolkit.application import get_app  # noqa: PLC0415
    from prompt_toolkit.filters import Condition  # noqa: PLC0415
    from prompt_toolkit.key_binding import KeyBindings  # noqa: PLC0415

    bindings = KeyBindings()

    @Condition
    def _buffer_empty() -> bool:
        return not get_app().current_buffer.text

    @bindings.add("c-c")
    def _on_ctrl_c(event: KeyPressEvent) -> None:
        _forward_ctrl_c(port)
        event.app.current_buffer.reset()
        event.app.exit(result="")

    @bindings.add("c-d", filter=_buffer_empty)
    def _on_ctrl_d(event: KeyPressEvent) -> None:
        _forward_ctrl_d(port)
        event.app.exit(result="")

    @bindings.add("c-x")
    def _on_ctrl_x(event: KeyPressEvent) -> None:
        event.app.exit(exception=_ExitLineMode())

    return bindings


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
    deadline = time.monotonic() + window_seconds
    last_read_at = time.monotonic()
    while True:
        if time.monotonic() >= deadline:
            return
        try:
            available = port.in_waiting
        except OSError:  # pragma: no cover -port dropped mid-drain
            return
        if not available:
            if time.monotonic() - last_read_at >= settle_seconds:
                return
            time.sleep(_DRAIN_POLL_INTERVAL)
            continue
        try:
            chunk = port.read(available)
        except OSError:  # pragma: no cover -port dropped mid-drain
            return
        last_read_at = time.monotonic()
        decoded = decoder.decode(chunk)
        if decoded:
            matches = detector.feed(decoded)
            output.write(colorize_stream_chunk(
                decoded, matches, detector, theme=theme,
            ))
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
    snippets_root: Path | None = None,
    editor: str | None = None,
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
        address: Serial address, used to derive the per-device
            persistent history file.
        history_root: Override the history root.  Defaults to
            :data:`DEFAULT_HISTORY_ROOT`; tests pass a tmp_path.
        commands: Override / extend the built-in `:command` table.
            Defaults to :data:`BUILTIN_COMMANDS`.
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
    # When tests inject their own prompt_session we leave the cache
    # unwired: the test owns its completer.  Otherwise we build the
    # device-completer cache here so :rescan can invalidate it.
    completion_cache: CompletionCache | None = (
        None if prompt_session is not None else CompletionCache()
    )
    context = LineModeContext(
        port=port,
        output=output,
        snippets_root=(
            snippets_root if snippets_root is not None else DEFAULT_SNIPPETS_ROOT
        ),
        editor=(
            editor
            if editor is not None
            else (os.environ.get("EDITOR") or DEFAULT_EDITOR)
        ),
        completion_cache=completion_cache,
    )

    if welcome_banner:
        output.write(welcome_banner)
        output.flush()

    # Print whatever the device has already buffered before we
    # block on input, usually the friendly REPL banner or prompt
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
        else _build_prompt_session(
            address=address,
            history_root=history_root,
            port=port,
            time=active_time,
            cache=completion_cache,
        )
    )

    while True:
        try:
            line = session.prompt(prompt)
        except _ExitLineMode:
            output.write("\nline-mode: bye\n")
            output.flush()
            return 0
        except (EOFError, KeyboardInterrupt):
            # EOFError fires when the underlying stdin closes (test stub
            # exhausting its script, no controlling tty).  KeyboardInterrupt
            # only reaches here if a SIGINT slips past our key binding;
            # the c-c handler normally converts it to an empty-line return.
            output.write("\nline-mode: bye\n")
            output.flush()
            return 0
        if line.startswith(COMMAND_PREFIX) and line:
            name, rest = _split_command(line)
            handler = command_table.get(name)
            if handler is None:
                output.write(
                    f"line-mode: unknown command :{name!r}.  "
                    f"Try :help.\n",
                )
                output.flush()
                continue
            try:
                keep_running = handler(context, rest)
            except OSError as error:
                # A port drop mid-command (``:load`` / ``:edit`` replay)
                # is fatal to the session the same way a dropped plain
                # line is: the port is gone.  Report and exit non-zero.
                output.write(f"line-mode: write failed: {error!r}\n")
                output.flush()
                return 1
            except Exception as error:
                # A buggy command handler must not tear down the whole
                # session.  Coach with a one-liner and return to the
                # prompt so in-progress history survives.
                output.write(
                    f"line-mode: :{name} failed: "
                    f"{type(error).__name__}: {error}\n",
                )
                output.flush()
                continue
            if not keep_running:
                return 0
        elif line:
            try:
                context.send_line(line)
            except OSError as error:  # pragma: no cover -port dropped mid-line
                output.write(f"line-mode: write failed: {error!r}\n")
                output.flush()
                return 1
        # Empty line (Enter on blank, or Ctrl-C / Ctrl-D forwarded a byte
        # via the key binding) falls through to drain so the device's
        # response (KeyboardInterrupt traceback, soft-reboot banner)
        # surfaces before the next prompt.
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
    port: SerialPort,
    time: TimeSource,
    cache: CompletionCache | None,
) -> object:
    """Construct a real ``prompt_toolkit.PromptSession`` for *address*.

    Imported lazily so the module-level cost of `chumicro_repl` doesn't
    pay for prompt_toolkit unless line mode is actually entered.

    The completer is wired to the live *port*.  Tab queries
    ``dir()`` on the device and caches the result in *cache*; the
    line-mode ``:rescan`` builtin invalidates the cache when the
    user wants to refresh after a new ``import``.
    """
    from prompt_toolkit import PromptSession  # noqa: PLC0415
    from prompt_toolkit.history import FileHistory  # noqa: PLC0415

    history_file = history_path_for(address, root=history_root)
    completer = build_default_completer(port=port, time=time, cache=cache)
    return PromptSession(
        history=FileHistory(str(history_file)),
        completer=completer,  # type: ignore[arg-type]
        key_bindings=build_line_mode_key_bindings(port),
    )


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
        f"chumicro-repl line mode: {address}\n"
        f"history: {history}\n"
        f"  :help     list commands\n"
        f"  :quit     exit\n"
        f"  Ctrl-X    exit\n"
        f"  Ctrl-C    interrupt running program on device\n"
        f"  Ctrl-D    soft-reboot device (at empty prompt)\n"
    )
