"""Interactive ``library browse``: the TTY front-end over the engine.

Library acquisition is one engine, two front-ends: the scriptable
``library add`` and this browser.  Both end by calling the same
closure-fetch.  The browser only adds selection UX (multi-select,
stable/experimental toggle, read a description, drill into a README or
an example and back).

The state machine (:class:`BrowserModel`) is pure and importable
without ``prompt_toolkit``.  Every fetch is an injected callable, so
it unit-tests with fakes (the pattern ``chumicro_repl`` uses to keep
its sources testable).  :func:`run_library_browser` is the thin
``prompt_toolkit`` shell: a full-screen app that needs a real
terminal, so it is excluded from coverage the way device adapters
are.  Its only logic is key bindings delegating to the model.
"""

from __future__ import annotations

from collections.abc import Callable

from chumicro_workspace.library_channel import (
    ChannelSnapshot,
    LibraryCatalogEntry,
    LibraryFetchError,
)

#: The two channels the Tab key toggles between.
_CHANNELS = ("stable", "experimental")

ResolveSnapshot = Callable[[str], ChannelSnapshot]
FetchText = Callable[[str, str, str], str]  # (channel, tag, path) -> text


class BrowserModel:
    """Pure browse state: list, detail, selection, channel toggle.

    Injected seams:

    * *resolve_snapshot*: ``channel -> ChannelSnapshot`` (the catalog).
    * *fetch_text*: ``(channel, tag, path) -> str`` for a README or
      one example file.

    A failed fetch sets :attr:`status` rather than raising, so the
    terminal app never dies under the user.
    """

    def __init__(
        self,
        *,
        channel: str,
        resolve_snapshot: ResolveSnapshot,
        fetch_text: FetchText,
    ) -> None:
        self._resolve = resolve_snapshot
        self._fetch_text = fetch_text
        self.channel = channel
        self.selected: set[str] = set()
        self.cursor = 0
        self.view = "list"  # "list" | "detail" | "example"
        self.status = ""
        self.detail_text = ""
        self.example_cursor = 0
        self._snapshot: ChannelSnapshot | None = None
        self.entries: list[LibraryCatalogEntry] = []
        self._load()

    # -- catalog ---------------------------------------------------------

    def _load(self) -> None:
        try:
            self._snapshot = self._resolve(self.channel)
        except LibraryFetchError as error:
            self.status = f"{self.channel}: {error} ({error.kind.value})"
            self.entries = []
            return
        self.entries = sorted(
            self._snapshot.libraries.values(), key=lambda entry: entry.name,
        )
        self.cursor = min(self.cursor, max(len(self.entries) - 1, 0))
        self.status = (
            f"{self.channel} @ {self._snapshot.tag}: "
            f"{len(self.entries)} libraries"
        )

    def switch_channel(self) -> None:
        """Toggle stable/experimental and re-resolve.  Selection persists."""
        self.channel = _CHANNELS[(_CHANNELS.index(self.channel) + 1) % 2]
        self.view = "list"
        self._load()

    # -- list navigation -------------------------------------------------

    @property
    def current(self) -> LibraryCatalogEntry | None:
        if not self.entries:
            return None
        return self.entries[self.cursor]

    def move(self, delta: int) -> None:
        if self.view == "example":
            return
        if self.view == "detail":
            entry = self.current
            count = len(entry.examples) if entry else 0
            if count:
                self.example_cursor = (self.example_cursor + delta) % count
            return
        if self.entries:
            self.cursor = (self.cursor + delta) % len(self.entries)

    def toggle_select(self) -> None:
        entry = self.current
        if self.view != "list" or entry is None:
            return
        if entry.name in self.selected:
            self.selected.discard(entry.name)
        else:
            self.selected.add(entry.name)

    # -- drill-in --------------------------------------------------------

    def enter(self) -> None:
        """From list, drill to detail (load README).  From detail, view highlighted example."""
        entry = self.current
        if entry is None or self._snapshot is None:
            return
        if self.view == "list":
            self.view = "detail"
            self.example_cursor = 0
            self.detail_text = self._text(entry.readme_path, "README")
        elif self.view == "detail" and entry.examples:
            path = entry.examples[self.example_cursor]
            self.view = "example"
            self.detail_text = self._text(path, path)

    def back(self) -> bool:
        """Step one view up.  Returns False when already at list.

        Example view collapses back to detail.  Detail collapses back to list.
        """
        if self.view == "example":
            self.view = "detail"
            entry = self.current
            if entry is not None:
                self.detail_text = self._text(entry.readme_path, "README")
            return True
        if self.view == "detail":
            self.view = "list"
            return True
        return False

    def _text(self, path: str, label: str) -> str:
        assert self._snapshot is not None
        try:
            return self._fetch_text(
                self.channel, self._snapshot.tag, path,
            )
        except LibraryFetchError as error:
            self.status = f"{label}: {error} ({error.kind.value})"
            return f"({label} unavailable: {error.kind.value})"

    # -- result ----------------------------------------------------------

    def selected_roots(self) -> list[str]:
        """Selected import names, deterministic order (BFS-stable add)."""
        return sorted(self.selected)

    def commit_target(self) -> list[str] | None:
        """Selected import names, or ``None`` when nothing is selected.

        Enter is gated on having an explicit Space-selection so that
        pressing Enter on a row you were just exploring shouldn't
        accidentally install it.  The binding layer interprets ``None``
        as "Enter means open the info view instead," so the cursor row
        still has a one-key path to its README and examples.
        """
        if self.view != "list" or not self.selected:
            return None
        return sorted(self.selected)


def run_library_browser(model: BrowserModel) -> list[str] | None:  # pragma: no cover
    """Full-screen prompt_toolkit shell.  Returns the chosen roots or None.

    Pure I/O wiring: needs a real terminal, so it carries no test
    coverage (the device-adapter convention).  Every binding delegates
    straight to :class:`BrowserModel`.  The logic lives there and is
    tested there.

    Layout shape: status line, help line, horizontal rule, and a
    content pane that swaps by view.  List view is a plain
    ``FormattedTextControl``.  Detail and example views are a scrollable
    ``TextArea`` so a long README or example file can be navigated.
    """
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import (
        DynamicContainer,
        HSplit,
        Window,
    )
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.widgets import TextArea

    # -- text area for scrollable README / example content -------------
    #
    # focusable=True so prompt_toolkit's built-in scroll bindings
    # (PgUp/PgDn/Home/End + arrow keys) work natively.  Our app-level
    # bindings declared with ``eager=True`` win over the TextArea's
    # arrow-key bindings inside detail view, so Up/Down cycle examples
    # there; PgUp/PgDn always scroll the buffer.
    content = TextArea(
        text="",
        read_only=True,
        scrollbar=True,
        focusable=True,
        wrap_lines=True,
    )

    # -- top status + help bars (always visible) -----------------------

    def render_status() -> str:
        if model.view == "list":
            return f" ChuMicro libraries: {model.status}"
        entry = model.current
        if entry is None:
            return ""
        if model.view == "detail":
            if entry.examples:
                selected_name = entry.examples[model.example_cursor]
                return (
                    f" {entry.name}: README   "
                    f"(example {model.example_cursor + 1}/"
                    f"{len(entry.examples)}: {selected_name})"
                )
            return f" {entry.name}: README   (no examples)"
        # example view: show which example file is on screen
        if entry.examples:
            selected_name = entry.examples[model.example_cursor]
            return f" {entry.name}: {selected_name}"
        return f" {entry.name}"

    def render_help() -> str:
        if model.view == "list":
            return (
                " [Space] select  [Enter] add selected (or info if none)  "
                "[i] info  [Tab] channel  [Up/Down] move  [q] quit"
            )
        if model.view == "detail":
            entry = model.current
            if entry and entry.examples:
                return (
                    " [Backspace] back  [Up/Down] cycle example  "
                    "[Enter] view example  [PgUp/PgDn] scroll README"
                )
            return " [Backspace] back  [PgUp/PgDn] scroll README"
        return " [Backspace] back  [PgUp/PgDn] scroll"

    status_window = Window(
        FormattedTextControl(render_status), height=Dimension.exact(1),
    )
    help_window = Window(
        FormattedTextControl(render_help), height=Dimension.exact(1),
    )
    rule_window = Window(height=Dimension.exact(1), char="─")

    # -- list view content ---------------------------------------------

    def render_list() -> str:
        lines = []
        for index, entry in enumerate(model.entries):
            mark = "x" if entry.name in model.selected else " "
            pointer = ">" if index == model.cursor else " "
            lines.append(
                f"{pointer} [{mark}] {entry.name}  {entry.version}  "
                f"{entry.description}",
            )
        return "\n".join(lines)

    list_window = Window(FormattedTextControl(render_list))

    def get_content_container():
        if model.view == "list":
            return list_window
        return content

    # Push the model's detail_text into the scrollable buffer and
    # claim focus for the TextArea so its built-in PgUp / PgDn / Home
    # / End / arrow scroll bindings start firing.  Called whenever a
    # key handler changes the view into detail or example.  Cursor
    # reset to 0 so the new content shows from the top, not wherever
    # the previous view's cursor happened to land.  Focus is best-
    # effort because the TextArea sits inside a ``DynamicContainer``
    # and isn't in the static layout tree at Layout-init time, so the
    # first transition after init may race the placement.  The next
    # transition catches up.
    def refresh_text_area(event) -> None:
        if model.view == "list":
            return
        content.text = model.detail_text
        content.buffer.cursor_position = 0
        try:
            event.app.layout.focus(content)
        except ValueError:  # pragma: no cover - TextArea not yet placed
            pass

    root = HSplit([
        status_window,
        help_window,
        rule_window,
        DynamicContainer(get_content_container),
    ])

    bindings = KeyBindings()

    @bindings.add("up", eager=True)
    def _(event) -> None:
        # eager=True so this wins over the TextArea's own Up binding
        # when detail view is active (the TextArea has focus there).
        # In example view we let PgUp/PgDn handle scroll; cycling
        # examples is meaningless once you're inside one.
        if model.view != "example":
            model.move(-1)

    @bindings.add("down", eager=True)
    def _(event) -> None:
        if model.view != "example":
            model.move(1)

    @bindings.add("space")
    def _(event) -> None:
        model.toggle_select()

    @bindings.add("tab")
    def _(event) -> None:
        if model.view == "list":
            model.switch_channel()

    @bindings.add("enter")
    def _(event) -> None:
        # On the list, Enter commits the explicit Space-selected set.
        # The user has to mark `[x]` first, so Enter on a row you're
        # just exploring should never accidentally install it.  With
        # no selection, Enter falls through to the same drill `i` does
        # so the cursor row still has a one-key path to its README and
        # example list.  Inside detail view, Enter opens the example
        # under the example cursor.
        if model.view == "list":
            target = model.commit_target()
            if target is not None:
                event.app.exit(result=target)
                return
            model.enter()
            refresh_text_area(event)
        elif model.view == "detail":
            model.enter()
            refresh_text_area(event)

    @bindings.add("i")
    def _(event) -> None:
        # Drill from list to detail.  Keeps a one-key path from the
        # cursor row to the README plus example list.  Enter is reserved
        # as the commit key on the list view.
        if model.view == "list":
            model.enter()
            refresh_text_area(event)

    @bindings.add("b", eager=True)
    @bindings.add("escape", eager=True)
    @bindings.add("backspace", eager=True)
    def _(event) -> None:
        # eager=True wins over the TextArea's own Esc / Backspace
        # bindings.  TextArea consumes Esc as a focus / cancel signal
        # under prompt_toolkit's default key set, so without the eager
        # flag the user couldn't back out of detail / example views
        # with Esc even though the binding existed.
        if model.back():
            refresh_text_area(event)

    @bindings.add("a")
    def _(event) -> None:
        # Explicit "add only what I Space-selected": exits with the
        # selection set even when empty.  Kept alongside Enter for
        # users who want the selections-only contract spelled out.
        event.app.exit(result=model.selected_roots())

    @bindings.add("q")
    @bindings.add("c-c")
    def _(event) -> None:
        event.app.exit(result=None)

    application: Application = Application(
        layout=Layout(root),
        key_bindings=bindings,
        full_screen=True,
    )
    return application.run()
