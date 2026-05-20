"""Interactive ``library browse`` — the TTY front-end over the engine.

Library acquisition is one engine, two front-ends: the scriptable
``library add`` and this browser.  Both end by calling the same
closure-fetch; the browser only adds selection UX (multi-select,
stable/experimental toggle, read a description, drill into a README or
an example and back).

The state machine (:class:`BrowserModel`) is pure and importable
without ``prompt_toolkit`` — every fetch is an injected callable, so
it unit-tests with fakes (the pattern ``chumicro_repl`` uses to keep
its sources testable).  :func:`run_library_browser` is the thin
``prompt_toolkit`` shell: a full-screen app that needs a real
terminal, so it is excluded from coverage the way device adapters
are — its only logic is key bindings delegating to the model.
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
    """Pure browse state: list ⇄ detail, selection, channel toggle.

    Injected seams:

    * *resolve_snapshot* — ``channel -> ChannelSnapshot`` (the catalog).
    * *fetch_text* — ``(channel, tag, path) -> str`` for a README or
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
            f"{self.channel} @ {self._snapshot.tag} — "
            f"{len(self.entries)} libraries"
        )

    def switch_channel(self) -> None:
        """Toggle stable⇄experimental and re-resolve; selection persists."""
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
        """list → detail (load README); detail → view highlighted example."""
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
        """example → detail → list.  Returns False when already at list."""
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
            return f"({label} unavailable — {error.kind.value})"

    # -- result ----------------------------------------------------------

    def selected_roots(self) -> list[str]:
        """Selected import names, deterministic order (BFS-stable add)."""
        return sorted(self.selected)

    def commit_target(self) -> list[str] | None:
        """Roots the user is asking to install right now.

        Two modes the same Enter keystroke covers — multi-select then
        commit (Space to build up a set, then act) and single-shot
        (no Space at all, just Enter on the row you want).  When the
        user has built explicit selections, those win; otherwise the
        cursor row is the single-shot target.  Returns ``None`` when
        the user is in a non-list view or the catalog is empty —
        there's nothing for a commit keystroke to act on.
        """
        if self.view != "list":
            return None
        if self.selected:
            return sorted(self.selected)
        if self.current is not None:
            return [self.current.name]
        return None


def run_library_browser(model: BrowserModel) -> list[str] | None:  # pragma: no cover
    """Full-screen prompt_toolkit shell; returns the chosen roots or None.

    Pure I/O wiring — needs a real terminal, so it carries no test
    coverage (the device-adapter convention).  Every binding delegates
    straight to :class:`BrowserModel`; the logic lives there and is
    tested there.
    """
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    def render() -> str:
        if model.view == "list":
            lines = [
                f"  ChuMicro libraries — {model.status}",
                "  [Enter] add  [Space] select  [i] info  "
                "[Tab] channel  [q] quit",
                "",
            ]
            for index, entry in enumerate(model.entries):
                mark = "x" if entry.name in model.selected else " "
                pointer = ">" if index == model.cursor else " "
                lines.append(
                    f"{pointer} [{mark}] {entry.name}  {entry.version}  "
                    f"{entry.description}",
                )
            return "\n".join(lines)
        entry = model.current
        if model.view == "detail" and entry and entry.examples:
            header = (
                f"  {entry.name} — [Up/Down] pick example  "
                f"[Enter] view  [Backspace] back"
            )
            example_lines = "\n".join(
                f"{'>' if index == model.example_cursor else ' '} {name}"
                for index, name in enumerate(entry.examples)
            )
            return (
                f"{header}\n\n{model.detail_text}\n\n"
                f"  Examples:\n{example_lines}"
            )
        header = (
            f"  {entry.name if entry else ''} — [Backspace] back"
        )
        return f"{header}\n\n{model.detail_text}"

    bindings = KeyBindings()

    @bindings.add("up")
    def _(event) -> None:
        model.move(-1)

    @bindings.add("down")
    def _(event) -> None:
        model.move(1)

    @bindings.add("space")
    def _(event) -> None:
        model.toggle_select()

    @bindings.add("tab")
    def _(event) -> None:
        model.switch_channel()

    @bindings.add("enter")
    def _(event) -> None:
        # On the list, Enter is the action key: commits the cursor row
        # (single-shot) or the explicit Space-selected set if the user
        # built one up.  Inside detail view it drills into the example
        # under the example cursor — same drill behavior the model has
        # always exposed.
        if model.view == "list":
            target = model.commit_target()
            if target is not None:
                event.app.exit(result=target)
        else:
            model.enter()

    @bindings.add("i")
    def _(event) -> None:
        # Drill from list → detail.  Mirrors the old Enter behavior so
        # users keep a one-key path to a library's README + example
        # list once Enter took over as the commit key.
        if model.view == "list":
            model.enter()

    @bindings.add("b")
    @bindings.add("escape")
    @bindings.add("backspace")
    def _(event) -> None:
        model.back()

    @bindings.add("a")
    def _(event) -> None:
        # Explicit "add only what I Space-selected" — exits with the
        # selection set even when empty.  Kept alongside Enter for
        # users who want the selections-only contract spelled out.
        event.app.exit(result=model.selected_roots())

    @bindings.add("q")
    @bindings.add("c-c")
    def _(event) -> None:
        event.app.exit(result=None)

    application: Application = Application(
        layout=Layout(Window(FormattedTextControl(render))),
        key_bindings=bindings,
        full_screen=True,
    )
    return application.run()
