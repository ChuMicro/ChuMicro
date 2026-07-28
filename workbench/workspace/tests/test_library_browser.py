"""Tests for the pure BrowserModel state machine (no prompt_toolkit)."""

from __future__ import annotations

from chumicro_workspace.cli.library_browser import BrowserModel
from chumicro_workspace.library_channel import (
    ChannelSnapshot,
    LibraryCatalogEntry,
    LibraryFetchError,
    LibraryFetchFailureKind,
)


def _entry(name, *, examples=()):
    return LibraryCatalogEntry(
        name=name,
        version="1.0.0",
        description=f"{name} does things",
        readme_path=f"{name.removeprefix('chumicro_')}/README.md",
        examples=examples,
    )


def _snapshot(channel, names, **kw):
    return ChannelSnapshot(
        channel=channel,
        tag="stable-tag" if channel == "stable" else "exp-tag",
        libraries={name: _entry(name, **kw) for name in names},
    )


def _model(*, names=("chumicro_mqtt", "chumicro_timing"), examples=(),
           texts=None, fail_text=False):
    snapshots = {
        "stable": _snapshot("stable", names, examples=examples),
        "experimental": _snapshot(
            "experimental", ("chumicro_wifi",), examples=examples,
        ),
    }

    def resolve(channel):
        return snapshots[channel]

    def fetch_text(channel, tag, path):
        if fail_text:
            raise LibraryFetchError(
                LibraryFetchFailureKind.NETWORK, "offline",
            )
        return (texts or {}).get(path, f"<{path}@{tag}>")

    return BrowserModel(
        channel="stable", resolve_snapshot=resolve, fetch_text=fetch_text,
    )


class TestList:
    def test_initial_load_sorts_and_statuses(self):
        model = _model()
        assert [entry.name for entry in model.entries] == [
            "chumicro_mqtt", "chumicro_timing",
        ]
        assert "stable @ stable-tag: 2 libraries" in model.status

    def test_move_wraps(self):
        model = _model()
        model.move(-1)
        assert model.cursor == 1
        model.move(1)
        assert model.cursor == 0

    def test_toggle_select_and_roots_sorted(self):
        model = _model()
        model.toggle_select()              # select mqtt
        model.move(1)
        model.toggle_select()              # select timing
        model.move(-1)
        model.toggle_select()              # deselect mqtt
        assert model.selected_roots() == ["chumicro_timing"]

    def test_resolve_failure_sets_status_empty_list(self):
        def resolve(channel):
            raise LibraryFetchError(
                LibraryFetchFailureKind.INDEX_MALFORMED, "bad json",
            )

        model = BrowserModel(
            channel="stable",
            resolve_snapshot=resolve,
            fetch_text=lambda *args: "",
        )
        assert model.entries == []
        assert "index-malformed" in model.status
        assert model.current is None
        model.toggle_select()  # no-op, no crash
        assert model.selected_roots() == []


class TestChannelToggle:
    def test_switch_reresolves_keeps_selection(self):
        model = _model()
        model.toggle_select()  # select chumicro_mqtt (stable)
        model.switch_channel()
        assert model.channel == "experimental"
        assert [entry.name for entry in model.entries] == ["chumicro_wifi"]
        assert model.selected_roots() == ["chumicro_mqtt"]  # persists
        model.switch_channel()
        assert model.channel == "stable"


class TestDrillIn:
    def test_enter_loads_readme_then_back(self):
        model = _model(texts={"mqtt/README.md": "# MQTT\nuse it"})
        model.enter()
        assert model.view == "detail"
        assert "use it" in model.detail_text
        assert model.back() is True
        assert model.view == "list"
        assert model.back() is False  # already at list

    def test_example_navigation_and_view(self):
        model = _model(
            names=("chumicro_mqtt",),
            examples=("mqtt/examples/pub.py", "mqtt/examples/sub.py"),
            texts={"mqtt/examples/sub.py": "print('sub')"},
        )
        model.enter()                 # list -> detail (README)
        assert model.view == "detail"
        model.move(1)                 # example cursor -> sub.py
        assert model.example_cursor == 1
        model.enter()                 # detail -> example view
        assert model.view == "example"
        assert "print('sub')" in model.detail_text
        model.back()                  # example -> detail (reloads README)
        assert model.view == "detail"

    def test_detail_enter_without_examples_is_noop(self):
        model = _model(names=("chumicro_mqtt",))
        model.enter()
        model.enter()  # no examples — stays in detail
        assert model.view == "detail"

    def test_fetch_error_sets_status_and_placeholder(self):
        model = _model(fail_text=True)
        model.enter()
        assert model.view == "detail"
        assert "unavailable" in model.detail_text
        assert "network" in model.status

    def test_move_in_example_view_is_noop(self):
        model = _model(
            names=("chumicro_mqtt",), examples=("mqtt/examples/a.py",),
        )
        model.enter()
        model.enter()
        assert model.view == "example"
        model.move(1)  # no-op in example view
        assert model.view == "example"


class TestEmptyCatalog:
    def test_enter_and_move_safe_when_empty(self):
        model = _model(names=())
        model.move(1)
        model.enter()
        assert model.view == "list"
        assert model.current is None


class TestCommitTarget:
    """Backs the strict Enter-only-on-selection keybinding contract."""

    def test_no_selection_returns_none(self):
        model = _model()
        # No Space presses → Enter must not commit.  The binding layer
        # treats None as "fall through to the info drill instead."
        assert model.commit_target() is None

    def test_single_selection_returned(self):
        model = _model()
        model.move(1)
        model.toggle_select()              # select timing
        model.move(-1)                     # cursor back on mqtt
        # Cursor position doesn't matter — only Space-selections commit.
        assert model.commit_target() == ["chumicro_timing"]

    def test_multi_select_returns_sorted_set(self):
        model = _model()
        model.toggle_select()
        model.move(1)
        model.toggle_select()
        assert model.commit_target() == ["chumicro_mqtt", "chumicro_timing"]

    def test_empty_catalog_returns_none(self):
        model = _model(names=())
        assert model.commit_target() is None

    def test_detail_view_returns_none(self):
        model = _model()
        model.toggle_select()              # selection in list
        model.enter()                      # list → detail
        assert model.view == "detail"
        # Even with a selection set, Enter inside detail must not commit
        # — Enter there drills into the example.
        assert model.commit_target() is None
