"""Tests for the shared on-device script sources (`_device_scripts`)."""

from __future__ import annotations

from chumicro_deploy._device_scripts import (
    CLEAR_ENTRYPOINTS_SCRIPT,
    LIST_ALL_SCRIPT,
    LIST_SCOPE_SCRIPT,
    SCOPE_LISTING_MARKER,
    WIPE_FILESYSTEM_SCRIPT,
    clean_slate_script,
    delete_files_script,
    remove_entries_script,
)
from chumicro_deploy.flash_drive import DEVICE_KEEP_SET
from chumicro_deploy.protocol import DEPLOY_SCOPE_FILES


class TestScriptsAreValidPython:
    """Every script (and builder output) must at least compile as Python.

    The bodies run on MicroPython, but CPython's compiler catches the
    same syntax-level breakage (a bad escape, an unbalanced paren from
    fragment composition) before it reaches a board.
    """

    def test_constants_compile(self) -> None:
        for name, script in [
            ("LIST_SCOPE_SCRIPT", LIST_SCOPE_SCRIPT),
            ("LIST_ALL_SCRIPT", LIST_ALL_SCRIPT),
            ("CLEAR_ENTRYPOINTS_SCRIPT", CLEAR_ENTRYPOINTS_SCRIPT),
            ("WIPE_FILESYSTEM_SCRIPT", WIPE_FILESYSTEM_SCRIPT),
        ]:
            compile(script, name, "exec")

    def test_builder_outputs_compile(self) -> None:
        compile(clean_slate_script(DEVICE_KEEP_SET), "clean_slate", "exec")
        compile(remove_entries_script(["lib", "main.py"]), "remove", "exec")
        compile(delete_files_script(["/lib/a.py"]), "delete", "exec")


class TestListScripts:
    """The listing scripts and their host-side parser share one marker."""

    def test_scope_script_paths_mirror_deploy_scope_files(self) -> None:
        """The embedded literal tuple must not drift from the shared constant.

        The script keeps a literal (deterministic device-visible listing
        order); this pins it to ``protocol.DEPLOY_SCOPE_FILES``.
        """
        embedded = {
            "/code.py", "/main.py", "/active.py", "/runtime_config.msgpack",
        }
        assert embedded == set(DEPLOY_SCOPE_FILES)
        for path in embedded:
            assert path in LIST_SCOPE_SCRIPT

    def test_both_list_scripts_emit_behind_the_marker(self) -> None:
        assert LIST_SCOPE_SCRIPT.count(repr(SCOPE_LISTING_MARKER)) == 2
        assert repr(SCOPE_LISTING_MARKER) in LIST_ALL_SCRIPT

    def test_scope_script_walks_lib_all_script_walks_root(self) -> None:
        assert LIST_SCOPE_SCRIPT.endswith("_walk('/lib')\n")
        assert LIST_ALL_SCRIPT.endswith("_walk('/')\n")


class TestScriptBuilders:
    """Parameterized scripts embed their arguments as Python literals."""

    def test_clean_slate_script_embeds_sorted_keep_set(self) -> None:
        script = clean_slate_script({"boot.py", "_chu_kv.msgpack"})
        assert "_keep = ['_chu_kv.msgpack', 'boot.py']" in script
        assert "os.listdir('/')" in script

    def test_remove_entries_script_embeds_a_tuple_of_names(self) -> None:
        script = remove_entries_script(["lib", "test_core.py"])
        assert "for _n in ('lib', 'test_core.py',):" in script

    def test_delete_files_script_round_trips_paths_via_repr(self) -> None:
        paths = ["/lib/pkg/mod.py", "/it's.py"]
        script = delete_files_script(paths)
        assert f"_paths = {paths!r}" in script
        assert "_reap('/')" in script

    def test_rmtree_fragment_is_shared_by_both_removal_builders(self) -> None:
        """clean_slate and remove_entries must stay on one _rm definition."""
        clean_slate_lines = clean_slate_script([]).splitlines()
        remove_lines = remove_entries_script([]).splitlines()
        rm_def = clean_slate_lines[: clean_slate_lines.index("_keep = []")]
        assert remove_lines[: len(rm_def)] == rm_def
