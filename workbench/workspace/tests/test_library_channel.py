"""Tests for chumicro_workspace.library_channel — snapshot backend.

No sockets: every test injects an ``http_get`` that serves bytes from
an in-memory dict, and snapshots are tarfiles built in memory.
"""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest
from chumicro_workspace.library import (
    LibraryFetchError,
    LibraryFetchFailureKind,
)
from chumicro_workspace.library_channel import (
    FILES_BASE_ENV,
    TARBALLS_BASE_ENV,
    _real_http_get,
    channel_repo,
    extract_library,
    fetch_snapshot_tarball,
    index_url,
    raw_file_url,
    resolve_snapshot,
    tarball_url,
)


def _index_bytes(tag: str, libraries: dict[str, dict]) -> bytes:
    return json.dumps({"tag": tag, "libraries": libraries}).encode()


def _snapshot_tarball(
    tag: str,
    shorts: tuple[str, ...],
    *,
    wrapper: str | None = None,
    traversal: bool = False,
    corrupt: bool = False,
) -> bytes:
    """Build a GitHub-shaped source tarball (one ``<repo>-<tag>/`` root)."""
    if corrupt:
        return b"not a gzip stream"
    wrapper = wrapper or f"ChuMicro-Libraries-{tag}"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        def add(name: str, body: bytes = b"x") -> None:
            info = tarfile.TarInfo(name)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))

        add(
            f"{wrapper}/index.json",
            _index_bytes(
                tag, {short: {"version": "1.0.0"} for short in shorts},
            ),
        )
        for short in shorts:
            add(f"{wrapper}/{short}/src/chumicro_{short}/__init__.py")
            add(f"{wrapper}/{short}/pyproject.toml")
        if traversal:
            add(f"{wrapper}/timing/../../escape.py")
    return buffer.getvalue()


def _serving(mapping: dict[str, bytes]):
    """An ``http_get`` that returns bytes for known URLs, 404s otherwise."""

    def http_get(url: str) -> bytes:
        try:
            return mapping[url]
        except KeyError:
            raise LibraryFetchError(
                LibraryFetchFailureKind.PACKAGE_NOT_FOUND,
                f"404 {url}",
            ) from None

    return http_get


class TestChannelRepo:
    def test_stable(self):
        assert channel_repo("stable") == "ChuMicro/ChuMicro-Libraries"

    def test_experimental(self):
        assert (
            channel_repo("experimental")
            == "ChuMicro/ChuMicro-Libraries-Experimental"
        )

    def test_unknown_channel_raises_unknown_channel_kind(self):
        with pytest.raises(LibraryFetchError) as caught:
            channel_repo("nightly")
        assert caught.value.kind is LibraryFetchFailureKind.UNKNOWN_CHANNEL


class TestUrlBuilders:
    def test_index_url(self):
        assert index_url("ChuMicro/ChuMicro-Libraries", "main") == (
            "https://raw.githubusercontent.com/"
            "ChuMicro/ChuMicro-Libraries/main/index.json"
        )

    def test_tarball_url(self):
        assert tarball_url("ChuMicro/ChuMicro-Libraries", "20260519") == (
            "https://codeload.github.com/"
            "ChuMicro/ChuMicro-Libraries/tar.gz/refs/tags/20260519"
        )

    def test_files_base_override_keeps_path_shape(self, monkeypatch):
        monkeypatch.setenv(FILES_BASE_ENV, "http://localhost:8000/")
        assert raw_file_url("ChuMicro/ChuMicro-Libraries", "main", "a/b") == (
            "http://localhost:8000/ChuMicro/ChuMicro-Libraries/main/a/b"
        )

    def test_tarballs_base_override_keeps_path_shape(self, monkeypatch):
        monkeypatch.setenv(TARBALLS_BASE_ENV, "file:///srv/mirror")
        assert tarball_url("ChuMicro/ChuMicro-Libraries", "20260519") == (
            "file:///srv/mirror/"
            "ChuMicro/ChuMicro-Libraries/tar.gz/refs/tags/20260519"
        )


class TestResolveSnapshot:
    def test_latest_reads_default_branch_index(self):
        repo = "ChuMicro/ChuMicro-Libraries"
        http_get = _serving({
            index_url(repo, "main"): _index_bytes(
                "20260519", {"chumicro_mqtt": {"version": "1.2.0"}},
            ),
        })
        snapshot = resolve_snapshot("stable", http_get=http_get)
        assert snapshot.tag == "20260519"
        assert snapshot.libraries["chumicro_mqtt"].version == "1.2.0"

    def test_pinned_tag_reads_index_at_tag(self):
        repo = "ChuMicro/ChuMicro-Libraries"
        http_get = _serving({
            index_url(repo, "20260101"): _index_bytes(
                "20260101", {"chumicro_timing": {"version": "0.9.0"}},
            ),
        })
        snapshot = resolve_snapshot(
            "stable", tag="20260101", http_get=http_get,
        )
        assert snapshot.tag == "20260101"

    def test_pinned_tag_mismatch_is_malformed(self):
        repo = "ChuMicro/ChuMicro-Libraries"
        http_get = _serving({
            index_url(repo, "20260101"): _index_bytes("20260102", {}),
        })
        with pytest.raises(LibraryFetchError) as caught:
            resolve_snapshot("stable", tag="20260101", http_get=http_get)
        assert caught.value.kind is LibraryFetchFailureKind.INDEX_MALFORMED

    def test_invalid_json_is_malformed(self):
        repo = "ChuMicro/ChuMicro-Libraries"
        http_get = _serving({index_url(repo, "main"): b"{not json"})
        with pytest.raises(LibraryFetchError) as caught:
            resolve_snapshot("stable", http_get=http_get)
        assert caught.value.kind is LibraryFetchFailureKind.INDEX_MALFORMED

    def test_missing_libraries_key_is_malformed(self):
        repo = "ChuMicro/ChuMicro-Libraries"
        http_get = _serving({
            index_url(repo, "main"): json.dumps({"tag": "x"}).encode(),
        })
        with pytest.raises(LibraryFetchError) as caught:
            resolve_snapshot("stable", http_get=http_get)
        assert caught.value.kind is LibraryFetchFailureKind.INDEX_MALFORMED

    def test_non_object_top_level_is_malformed(self):
        repo = "ChuMicro/ChuMicro-Libraries"
        http_get = _serving({index_url(repo, "main"): b"[]"})
        with pytest.raises(LibraryFetchError) as caught:
            resolve_snapshot("stable", http_get=http_get)
        assert caught.value.kind is LibraryFetchFailureKind.INDEX_MALFORMED

    def test_entry_without_version_is_malformed(self):
        repo = "ChuMicro/ChuMicro-Libraries"
        http_get = _serving({
            index_url(repo, "main"): _index_bytes(
                "t", {"chumicro_mqtt": {"description": "no version"}},
            ),
        })
        with pytest.raises(LibraryFetchError) as caught:
            resolve_snapshot("stable", http_get=http_get)
        assert caught.value.kind is LibraryFetchFailureKind.INDEX_MALFORMED

    def test_description_and_readme_default(self):
        repo = "ChuMicro/ChuMicro-Libraries"
        http_get = _serving({
            index_url(repo, "main"): _index_bytes(
                "t", {"chumicro_mqtt": {"version": "1.0.0"}},
            ),
        })
        entry = resolve_snapshot("stable", http_get=http_get).libraries[
            "chumicro_mqtt"
        ]
        assert entry.description == ""
        assert entry.readme_path == "README.md"


class TestExtractLibrary:
    def test_happy_strips_wrapper_into_short_dir(self, tmp_path: Path):
        tarball = _snapshot_tarball("20260519", ("mqtt", "timing"))
        root = extract_library(tarball, "chumicro_mqtt", tmp_path)
        assert root == tmp_path / "mqtt"
        assert (tmp_path / "mqtt" / "pyproject.toml").is_file()
        assert (
            tmp_path / "mqtt" / "src" / "chumicro_mqtt" / "__init__.py"
        ).is_file()
        # Only the requested library — not its snapshot siblings.
        assert not (tmp_path / "timing").exists()

    def test_missing_library_is_package_not_found(self, tmp_path: Path):
        tarball = _snapshot_tarball("20260519", ("timing",))
        with pytest.raises(LibraryFetchError) as caught:
            extract_library(tarball, "chumicro_mqtt", tmp_path)
        assert caught.value.kind is LibraryFetchFailureKind.PACKAGE_NOT_FOUND

    def test_traversal_member_rejected(self, tmp_path: Path):
        tarball = _snapshot_tarball(
            "20260519", ("timing",), traversal=True,
        )
        with pytest.raises(LibraryFetchError) as caught:
            extract_library(tarball, "chumicro_timing", tmp_path)
        assert caught.value.kind is LibraryFetchFailureKind.BAD_ARCHIVE

    def test_corrupt_tarball_is_bad_archive(self, tmp_path: Path):
        with pytest.raises(LibraryFetchError) as caught:
            extract_library(
                _snapshot_tarball("t", (), corrupt=True),
                "chumicro_mqtt",
                tmp_path,
            )
        assert caught.value.kind is LibraryFetchFailureKind.BAD_ARCHIVE


class TestSafeMemberPath:
    """Extraction containment is path-boundary, not string-prefix."""

    def test_rejects_sibling_directory_escape(self, tmp_path: Path):
        from chumicro_workspace import library_channel  # noqa: PLC0415

        into = tmp_path / "foo"
        into.mkdir()
        # `foo-evil` shares the `foo` string prefix but is a sibling of
        # `foo`, not a child; a str.startswith guard would admit it.
        with pytest.raises(LibraryFetchError) as caught:
            library_channel._safe_member_path(into, "../foo-evil/payload")
        assert caught.value.kind is LibraryFetchFailureKind.BAD_ARCHIVE

    def test_accepts_nested_member(self, tmp_path: Path):
        from chumicro_workspace import library_channel  # noqa: PLC0415

        into = tmp_path / "foo"
        resolved = library_channel._safe_member_path(into, "src/mod.py")
        assert resolved == (into / "src" / "mod.py").resolve()


class TestFetchSnapshotTarball:
    def test_fetches_tarball_url_once(self):
        repo = "ChuMicro/ChuMicro-Libraries"
        tarball = _snapshot_tarball("20260519", ("mqtt",))
        calls: list[str] = []

        def http_get(url: str) -> bytes:
            calls.append(url)
            return tarball

        snapshot = resolve_snapshot(
            "stable",
            tag="20260519",
            http_get=_serving({
                index_url(repo, "20260519"): _index_bytes("20260519", {}),
            }),
        )
        body = fetch_snapshot_tarball(
            "stable", snapshot, http_get=http_get,
        )
        assert body == tarball
        assert calls == [tarball_url(repo, "20260519")]


class TestFetchTextFile:
    def test_fetches_and_decodes_leniently(self):
        from chumicro_workspace.library_channel import fetch_text_file

        url = raw_file_url(
            "ChuMicro/ChuMicro-Libraries", "20260101", "mqtt/README.md",
        )
        # Invalid UTF-8 byte decodes to U+FFFD instead of aborting.
        http_get = _serving({url: b"# mqtt\n\xff"})
        text = fetch_text_file(
            "stable", "20260101", "mqtt/README.md", http_get=http_get,
        )
        assert text == "# mqtt\n�"


class TestRealHttpGet:
    def test_file_scheme_serves_an_on_disk_mirror(self, tmp_path: Path):
        body = _index_bytes("20260101", {})
        (tmp_path / "index.json").write_bytes(body)
        assert _real_http_get((tmp_path / "index.json").as_uri()) == body

    def test_missing_file_raises_network_kind(self, tmp_path: Path):
        with pytest.raises(LibraryFetchError) as caught:
            _real_http_get((tmp_path / "absent.json").as_uri())
        assert caught.value.kind is LibraryFetchFailureKind.NETWORK

    def test_unsupported_scheme_raises_network_kind(self):
        with pytest.raises(LibraryFetchError) as caught:
            _real_http_get("ftp://mirror.example/index.json")
        assert caught.value.kind is LibraryFetchFailureKind.NETWORK

    def test_http_404_is_package_not_found(self, monkeypatch):
        import urllib.error

        from chumicro_workspace import library_channel

        def boom(url, timeout):
            raise urllib.error.HTTPError(
                url, 404, "missing", {}, io.BytesIO(b""),
            )

        monkeypatch.setattr(
            library_channel.urllib.request, "urlopen", boom,
        )
        with pytest.raises(LibraryFetchError) as caught:
            library_channel._real_http_get("https://example.invalid/x")
        assert caught.value.kind is LibraryFetchFailureKind.PACKAGE_NOT_FOUND

    def test_http_500_is_network(self, monkeypatch):
        import urllib.error

        from chumicro_workspace import library_channel

        def boom(url, timeout):
            raise urllib.error.HTTPError(
                url, 500, "boom", {}, io.BytesIO(b""),
            )

        monkeypatch.setattr(
            library_channel.urllib.request, "urlopen", boom,
        )
        with pytest.raises(LibraryFetchError) as caught:
            library_channel._real_http_get("https://example.invalid/x")
        assert caught.value.kind is LibraryFetchFailureKind.NETWORK

    def test_success_returns_body(self, monkeypatch):
        from chumicro_workspace import library_channel

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *exception):
                return False

            def read(self):
                return b"payload"

        monkeypatch.setattr(
            library_channel.urllib.request,
            "urlopen",
            lambda url, timeout: _Response(),
        )
        assert (
            library_channel._real_http_get("https://example.invalid/x")
            == b"payload"
        )

    def test_urlerror_is_network(self, monkeypatch):
        import urllib.error

        from chumicro_workspace import library_channel

        def boom(url, timeout):
            raise urllib.error.URLError("no route")

        monkeypatch.setattr(
            library_channel.urllib.request, "urlopen", boom,
        )
        with pytest.raises(LibraryFetchError) as caught:
            library_channel._real_http_get("https://example.invalid/x")
        assert caught.value.kind is LibraryFetchFailureKind.NETWORK
