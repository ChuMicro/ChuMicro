"""Tests for the scoped diff-deploy primitive (multi-project-staging replacement)."""

from __future__ import annotations

import pytest
from chumicro_deploy import (
    DEPLOY_SCOPE_FILES,
    DEPLOY_SCOPE_PREFIXES,
    Deployer,
    Device,
    FakeTransport,
    FileMapSource,
    is_in_deploy_scope,
)

# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------


class TestIsInDeployScope:
    @pytest.mark.parametrize(
        "path",
        sorted(DEPLOY_SCOPE_FILES) + [
            "/lib/foo.py",
            "/lib/projects/__init__.py",
            "/lib/projects/garage/sensors/door_open/app.py",
        ],
    )
    def test_in_scope_paths(self, path: str) -> None:
        assert is_in_deploy_scope(path)

    @pytest.mark.parametrize(
        "path",
        [
            "/settings.toml",        # CP user-config — out of scope
            "/boot.py",              # user-managed boot hook
            "/.fseventsd/...",       # macOS metadata on CIRCUITPY
            "/photo.jpg",            # user-uploaded asset
            "/data/log.txt",         # user-managed data dir
            "/secrets.toml",         # CP-style secrets
        ],
    )
    def test_out_of_scope_paths(self, path: str) -> None:
        assert not is_in_deploy_scope(path)

    def test_scope_prefixes_documented(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sanity — the prefix list is what the test cases above assume."""
        assert DEPLOY_SCOPE_PREFIXES == ("/lib/",)


# ---------------------------------------------------------------------------
# FakeTransport list / delete primitives
# ---------------------------------------------------------------------------


class TestFakeTransportPrimitives:
    def test_list_in_scope_filters_to_scope(self, monkeypatch: pytest.MonkeyPatch) -> None:
        transport = FakeTransport(device_files={
            "/code.py": b"# entrypoint",
            "/lib/foo.py": b"x = 1",
            "/photo.jpg": b"<jpeg>",          # out of scope
            "/settings.toml": b"WIFI_SSID=...",  # out of scope
        })
        listed = sorted(transport.list_files_in_scope())
        assert listed == ["/code.py", "/lib/foo.py"]
        assert ("list_files_in_scope", (False,)) in transport.calls
        # clean-slate widens scope to everything but the keep set.
        clean = sorted(transport.list_files_in_scope(clean_slate=True))
        assert clean == ["/code.py", "/lib/foo.py", "/photo.jpg", "/settings.toml"]
        assert ("list_files_in_scope", (True,)) in transport.calls

    def test_delete_drops_paths_from_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        transport = FakeTransport(device_files={
            "/code.py": b"a",
            "/lib/old.py": b"b",
            "/lib/keep.py": b"c",
        })
        transport.delete_files(["/lib/old.py", "/missing.py"])
        # Missing path tolerated silently; rest survive.
        assert "/code.py" in transport.device_files
        assert "/lib/keep.py" in transport.device_files
        assert "/lib/old.py" not in transport.device_files
        assert ("delete_files", (["/lib/old.py", "/missing.py"],)) in transport.calls

    def test_deploy_files_updates_simulated_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A deploy_files call writes to FakeTransport.device_files for next list."""
        transport = FakeTransport()
        transport.deploy_files(
            {"/code.py": b"# new", "/lib/foo.py": b"y = 2"},
            "/code.py",
        )
        assert transport.device_files["/code.py"] == b"# new"
        assert transport.device_files["/lib/foo.py"] == b"y = 2"


# ---------------------------------------------------------------------------
# Deployer.deploy_diff orchestration
# ---------------------------------------------------------------------------


def _build_device(
    transport: FakeTransport, *, deploy_mode: str = "flash",
) -> Device:
    return Device(
        transport="micropython",
        address="/dev/cu.fake",
        deploy_mode=deploy_mode,
        transport_factory=lambda _device: transport,
    )


class TestDeployerDeployDiff:
    def test_deletes_stale_in_scope_files(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """File on device + not in new payload → deleted; new payload written."""
        transport = FakeTransport(
            mode="copy",
            device_files={
                "/code.py": b"# previous deploy",
                "/lib/old_project.py": b"old code",
                "/lib/shared.py": b"shared v1",
            },
        )
        deployer = Deployer(_build_device(transport))
        new_payload = {
            "/code.py": b"# new deploy",
            "/lib/shared.py": b"shared v2",
            "/lib/new_project.py": b"new code",
        }
        deleted: list[str] = []
        result = deployer.deploy_diff(
            FileMapSource(new_payload, entrypoint="/code.py"),
            on_file_deleted=deleted.append,
        )
        assert result.success
        # Stale file deleted; shared file replaced; new file added.
        assert deleted == ["/lib/old_project.py"]
        assert transport.device_files["/code.py"] == b"# new deploy"
        assert transport.device_files["/lib/shared.py"] == b"shared v2"
        assert transport.device_files["/lib/new_project.py"] == b"new code"
        assert "/lib/old_project.py" not in transport.device_files

    def test_clean_slate_default_removes_non_keepset_files(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The default clean-slate diff removes everything but payload + keep set.

        A board ``settings.toml`` (competing wifi authority), stray
        photos, and old logs are reconciled away; only the new payload
        and the closed keep set (``boot_out.txt``) remain.
        """
        transport = FakeTransport(
            mode="copy",
            device_files={
                "/code.py": b"# previous",
                "/settings.toml": b"WIFI_SSID = 'home'",
                "/photo.jpg": b"<jpeg>",
                "/data/log.txt": b"old log",
                "/lib/foo.py": b"old foo",
                "/boot_out.txt": b"identity",  # keep set — must survive
            },
        )
        deployer = Deployer(_build_device(transport))
        deployer.deploy_diff(
            FileMapSource({"/code.py": b"# new"}, entrypoint="/code.py"),
        )
        assert "/settings.toml" not in transport.device_files
        assert "/photo.jpg" not in transport.device_files
        assert "/data/log.txt" not in transport.device_files
        assert "/lib/foo.py" not in transport.device_files
        # Keep-set file preserved; payload written.
        assert transport.device_files["/boot_out.txt"] == b"identity"
        assert transport.device_files["/code.py"] == b"# new"

    def test_no_wipe_opt_out_preserves_out_of_scope_files(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """clean=False (the --no-wipe opt-out) keeps user-managed files."""
        transport = FakeTransport(
            mode="copy",
            device_files={
                "/code.py": b"# previous",
                "/settings.toml": b"WIFI_SSID = 'home'",
                "/photo.jpg": b"<jpeg>",
                "/data/log.txt": b"old log",
                "/lib/foo.py": b"old foo",
            },
        )
        deployer = Deployer(_build_device(transport))
        deployer.deploy_diff(
            FileMapSource({"/code.py": b"# new"}, entrypoint="/code.py"),
            clean=False,
        )
        # Legacy additive scope: out-of-scope files preserved.
        assert transport.device_files["/settings.toml"] == b"WIFI_SSID = 'home'"
        assert transport.device_files["/photo.jpg"] == b"<jpeg>"
        assert transport.device_files["/data/log.txt"] == b"old log"
        # In-scope file still dropped because not in new payload.
        assert "/lib/foo.py" not in transport.device_files

    def test_no_stale_files_skips_delete_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty stale set → delete_files not called (no transport round-trip)."""
        transport = FakeTransport(
            mode="copy",
            device_files={"/code.py": b"# v1"},
        )
        deployer = Deployer(_build_device(transport))
        deployer.deploy_diff(
            FileMapSource(
                {
                    "/code.py": b"# v2",
                    "/lib/new.py": b"x = 1",
                },
                entrypoint="/code.py",
            ),
        )
        # delete_files NOT in the call log — there was nothing stale.
        delete_calls = [
            call for call in transport.calls if call[0] == "delete_files"
        ]
        assert delete_calls == []

    def test_first_deploy_to_empty_device(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No prior deploy → no stale files, normal write flow."""
        transport = FakeTransport(mode="copy", device_files={})
        deployer = Deployer(_build_device(transport))
        result = deployer.deploy_diff(
            FileMapSource(
                {"/code.py": b"# first deploy"},
                entrypoint="/code.py",
            ),
        )
        assert result.success
        assert transport.device_files == {"/code.py": b"# first deploy"}

    def test_ram_mode_collapses_to_plain_deploy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """RAM-mode FakeTransport.list_files_in_scope returns [] — no diff cleanup.

        Tests with the FakeTransport whose `device_files` populates from
        prior deploys but starts empty here — the equivalent of "RAM
        mode never wrote anything to flash."
        """
        transport = FakeTransport(mode="ram", device_files={})
        deployer = Deployer(_build_device(transport))
        result = deployer.deploy_diff(
            FileMapSource(
                {"/main.py": b"print('hi')"},
                entrypoint="/main.py",
            ),
        )
        assert result.success
        # No deletions attempted; deploy_files was called.
        delete_calls = [
            call for call in transport.calls if call[0] == "delete_files"
        ]
        deploy_calls = [
            call for call in transport.calls if call[0] == "deploy_files"
        ]
        assert delete_calls == []
        assert len(deploy_calls) == 1

    def test_traceback_marks_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Diff-deploy uses the same traceback detection as plain deploy."""
        transport = FakeTransport(
            mode="copy",
            device_files={"/code.py": b"# v1"},
            execute_output=(
                "Traceback (most recent call last):\n"
                "  File \"/code.py\", line 1\n"
                "RuntimeError: boom\n"
            ),
        )
        deployer = Deployer(_build_device(transport))
        result = deployer.deploy_diff(
            FileMapSource(
                {"/code.py": b"# crashy"},
                entrypoint="/code.py",
            ),
        )
        assert not result.success
        assert "RuntimeError: boom" in (result.traceback or "")

    def test_progress_callbacks_fire_in_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        transport = FakeTransport(
            mode="copy",
            device_files={"/lib/old.py": b"x"},
        )
        deployer = Deployer(_build_device(transport))
        progress: list[tuple[float, str]] = []
        deployer.deploy_diff(
            FileMapSource(
                {"/code.py": b"# new"},
                entrypoint="/code.py",
            ),
            on_progress=lambda fraction, message: progress.append(
                (fraction, message),
            ),
        )
        # Stages monotonic, last is "done".
        fractions = [item[0] for item in progress]
        assert fractions == sorted(fractions)
        assert progress[-1][1] == "done"
        # The "cleaning stale" stage fired since /lib/old.py was stale.
        cleaning_messages = [
            message for _, message in progress if "cleaning" in message
        ]
        assert cleaning_messages, progress

    def test_disconnect_called_even_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Transport.disconnect() must run via the finally guard."""
        transport = FakeTransport(
            mode="copy",
            device_files={},
            execute_output="Traceback (most recent call last):\nValueError: x",
        )
        deployer = Deployer(_build_device(transport))
        deployer.deploy_diff(
            FileMapSource(
                {"/code.py": b"# x"},
                entrypoint="/code.py",
            ),
        )
        assert ("disconnect", ()) in transport.calls


class TestDeployerWipeFlag:
    """`Deployer.deploy_diff(..., wipe=True)` — destructive clean-slate path."""

    def test_wipe_clears_everything_and_skips_diff(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Wipe nukes in-scope + out-of-scope alike, then plain deploy_files runs."""
        transport = FakeTransport(
            mode="copy",
            device_files={
                "/code.py": b"# previous",
                "/lib/old.py": b"old",
                "/settings.toml": b"WIFI_SSID = 'home'",
                "/photo.jpg": b"<jpeg>",
            },
        )
        deployer = Deployer(_build_device(transport))
        deleted: list[str] = []
        result = deployer.deploy_diff(
            FileMapSource(
                {"/code.py": b"# fresh", "/lib/new.py": b"x = 1"},
                entrypoint="/code.py",
            ),
            wipe=True,
            on_file_deleted=deleted.append,
        )
        assert result.success
        # Wipe ran; out-of-scope files are GONE (this is the whole point).
        assert "wipe_filesystem" in [call[0] for call in transport.calls]
        assert "/settings.toml" not in transport.device_files
        assert "/photo.jpg" not in transport.device_files
        # Diff-cleanup primitives were skipped — wipe makes them redundant.
        labels = [call[0] for call in transport.calls]
        assert "list_files_in_scope" not in labels
        assert "delete_files" not in labels
        assert deleted == []
        # New payload landed.
        assert transport.device_files == {
            "/code.py": b"# fresh",
            "/lib/new.py": b"x = 1",
        }

    def test_wipe_progress_reports_wiping_stage(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        transport = FakeTransport(
            mode="copy", device_files={"/code.py": b"# v1"},
        )
        deployer = Deployer(_build_device(transport))
        progress: list[tuple[float, str]] = []
        deployer.deploy_diff(
            FileMapSource({"/code.py": b"# v2"}, entrypoint="/code.py"),
            wipe=True,
            on_progress=lambda fraction, message: progress.append(
                (fraction, message),
            ),
        )
        wipe_messages = [
            message for _, message in progress if "wiping" in message
        ]
        assert wipe_messages, progress
        # Listing/cleaning stages should NOT show up — we wiped instead.
        cleaning_messages = [
            message for _, message in progress if "cleaning" in message
        ]
        listing_messages = [
            message for _, message in progress if "listing" in message
        ]
        assert cleaning_messages == []
        assert listing_messages == []

    def test_wipe_ram_mode_no_op_still_deploys(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RAM-mode FakeTransport.wipe_filesystem() leaves device_files alone."""
        transport = FakeTransport(mode="ram", device_files={})
        deployer = Deployer(_build_device(transport))
        result = deployer.deploy_diff(
            FileMapSource({"/main.py": b"# hi"}, entrypoint="/main.py"),
            wipe=True,
        )
        assert result.success
        # wipe_filesystem still got called — the no-op happens inside the
        # transport, callers don't have to gate on mode.
        assert "wipe_filesystem" in [call[0] for call in transport.calls]


class TestFakeTransportWipe:
    def test_wipe_clears_flash_mode_state(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        transport = FakeTransport(
            mode="copy",
            device_files={"/lib/foo.py": b"x", "/photo.jpg": b"y"},
        )
        transport.wipe_filesystem()
        assert transport.device_files == {}
        assert ("wipe_filesystem", ()) in transport.calls

    def test_wipe_ram_mode_is_no_op(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RAM/mount transports leave device_files alone — nothing in flash."""
        transport = FakeTransport(
            mode="ram",
            device_files={"/lib/foo.py": b"x"},
        )
        transport.wipe_filesystem()
        # Files still there because RAM mode never wrote them to flash.
        assert transport.device_files == {"/lib/foo.py": b"x"}
        assert ("wipe_filesystem", ()) in transport.calls


class TestMicropythonScopeListingParser:
    """Module-level parser for the on-device listing script."""

    def test_extracts_marked_lines_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from chumicro_deploy.micropython_transport import _parse_scope_listing

        output = (
            "boot ok\n"
            "__CHU_F:/code.py\n"
            "extraneous noise\n"
            "__CHU_F:/lib/foo.py\n"
            "__CHU_F:/lib/foo.py\n"  # dedup
        )
        assert _parse_scope_listing(output) == ["/code.py", "/lib/foo.py"]

    def test_empty_output_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from chumicro_deploy.micropython_transport import _parse_scope_listing

        assert _parse_scope_listing("") == []
        assert _parse_scope_listing("nothing matches\n") == []
