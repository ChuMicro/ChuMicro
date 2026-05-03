"""File sources — plug-in input types that feed the Deployer.

A :class:`FileSource` produces two projects: a mapping of on-device
paths to byte contents, and the name of the entrypoint file the
runtime should boot into.  Three built-ins cover the common cases:

- :class:`FileMapSource` — caller already has an in-memory dict.
- :class:`DirectorySource` — ship a directory tree from disk.
- :class:`ImportGraphSource` — walk imports from an entrypoint file
  and ship exactly the transitively-reachable modules.

Custom sources implement the :class:`FileSource` protocol.  The
protocol is :func:`~typing.runtime_checkable` so ``isinstance`` works
at the deployer boundary.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Protocol, runtime_checkable

from ._runtime_marker import file_targets_runtime
from .protocol import validate_entrypoint_in_files


@runtime_checkable
class FileSource(Protocol):
    """What the Deployer expects from any file source.

    Implementations return the deploy-time file map and declare which
    of those files is the entrypoint.  The Deployer does not mutate
    either result — sources own their own state.
    """

    def files(self) -> dict[str, bytes]:
        """Return on-device path → file bytes.

        Keys are on-device paths (typically starting with ``/``) that
        the Deployer writes onto the target.  Values are the raw file
        contents.
        """
        ...

    def entrypoint(self) -> str:
        """Return the on-device entrypoint path.

        Must be one of the keys returned by :meth:`files`.  The
        Deployer executes this file after staging.
        """
        ...


class FileMapSource:
    """A source backed by an in-memory dict.

    Strings in the input are encoded as UTF-8.  Binary values pass
    through unchanged.

    Args:
        files: Mapping of on-device paths to file contents.  Values
            may be ``str`` (encoded to UTF-8) or ``bytes``
            (passed through).
        entrypoint: Key in *files* that is the boot file.

    Raises:
        ValueError: If *entrypoint* is not a key of *files*.
    """

    def __init__(
        self,
        files: dict[str, str | bytes],
        *,
        entrypoint: str,
    ) -> None:
        validate_entrypoint_in_files(files, entrypoint)
        self._files: dict[str, bytes] = {
            path: (
                content.encode("utf-8") if isinstance(content, str) else content
            )
            for path, content in files.items()
        }
        self._entrypoint = entrypoint

    def files(self) -> dict[str, bytes]:
        return dict(self._files)

    def entrypoint(self) -> str:
        return self._entrypoint


class DirectorySource:
    """A source that ships every file under a host-side directory.

    Walks *root* recursively and reads every file as bytes.  The
    on-device path is the file path relative to *root*, joined with
    *resource_prefix* (default ``/``).

    Args:
        root: Host directory whose contents are deployed.
        entrypoint: On-device entrypoint path.  Must end up as a key
            in the produced file map — i.e. must be a file under
            *root* (relative to *resource_prefix*).
        resource_prefix: On-device prefix prepended to each file's
            path.  Defaults to ``/`` (files land at the top of the
            device filesystem).
        excluded_names: Filename / directory names to skip entirely
            (exact match, not glob).  Defaults to common artifacts
            (``__pycache__``, ``.DS_Store``, ``.git``, etc.).
        target_runtime: Decision 0044 — when set
            (``"circuitpython"`` / ``"micropython"`` / ``"cpython"``),
            ``.py`` files carrying a ``__chumicro_runtimes__`` marker
            are skipped if the marker doesn't include *target_runtime*.
            ``None`` (the default) ships every file, matching the prior
            unfiltered behavior.  Non-``.py`` files are unaffected.

    Raises:
        NotADirectoryError: If *root* does not exist or is not a
            directory.
        ValueError: If *entrypoint* is not produced by the walk.
    """

    DEFAULT_EXCLUDED: frozenset[str] = frozenset(
        {"__pycache__", ".DS_Store", ".git", ".pytest_cache", ".mypy_cache"}
    )

    def __init__(
        self,
        root: Path,
        *,
        entrypoint: str,
        resource_prefix: str = "/",
        excluded_names: frozenset[str] | None = None,
        target_runtime: str | None = None,
    ) -> None:
        if not root.is_dir():
            raise NotADirectoryError(f"DirectorySource root not a directory: {root}")
        self._root = root
        self._entrypoint = entrypoint
        self._resource_prefix = resource_prefix
        self._excluded = (
            excluded_names if excluded_names is not None else self.DEFAULT_EXCLUDED
        )
        self._target_runtime = target_runtime
        self._files: dict[str, bytes] | None = None

    def _walk(self) -> dict[str, bytes]:
        collected: dict[str, bytes] = {}
        for file_path in sorted(self._root.rglob("*")):
            if not file_path.is_file():
                continue
            if any(part in self._excluded for part in file_path.relative_to(self._root).parts):
                continue
            if file_path.suffix == ".py" and not file_targets_runtime(
                file_path, target_runtime=self._target_runtime,
            ):
                continue
            relative_path = file_path.relative_to(self._root).as_posix()
            device_path = self._join_prefix(self._resource_prefix, relative_path)
            collected[device_path] = file_path.read_bytes()
        if self._entrypoint not in collected:
            raise ValueError(
                f"entrypoint {self._entrypoint!r} not produced by directory walk "
                f"(keys: {sorted(collected.keys())!r})"
            )
        return collected

    @staticmethod
    def _join_prefix(prefix: str, relative_path: str) -> str:
        if prefix == "/" or prefix == "":
            return f"/{relative_path}"
        trimmed = prefix.rstrip("/")
        return f"{trimmed}/{relative_path}"

    def files(self) -> dict[str, bytes]:
        if self._files is None:
            self._files = self._walk()
        return dict(self._files)

    def entrypoint(self) -> str:
        return self._entrypoint


class ImportGraphSource:
    """A source that walks Python imports starting from an entrypoint.

    Parses *entrypoint* with the ``ast`` module, collects every
    ``import`` and ``from ... import`` target, resolves each one
    against *search_paths* (first match wins), and recursively walks
    the resolved modules.  Packages are walked through their
    ``__init__.py``.  Dynamic imports (``importlib.import_module``,
    ``__import__``) are not detected; pass those names explicitly via
    *extra_modules*.

    Modules that don't resolve against any search path are skipped
    silently — they are assumed to be device-runtime built-ins
    (``gc``, ``time``, ``board``, etc.) the host can't provide
    regardless.

    Args:
        entrypoint: Host path to the entrypoint file.  Deployed as
            ``{device_entrypoint}`` at the top of the device
            filesystem.
        search_paths: Directories searched in order when resolving
            imports.  Typical chumicro usage supplies ``libs/`` and
            ``packages/``.
        extra_modules: Dotted module names to force-include even when
            ``ast`` cannot see them (dynamic imports, plugin targets).
        device_entrypoint: On-device path for the entrypoint (default
            ``/code.py``).
        resource_prefix: On-device prefix for every non-entrypoint
            module file (default ``/lib``).
        target_runtime: Decision 0044 — when set
            (``"circuitpython"`` / ``"micropython"`` / ``"cpython"``),
            modules carrying a ``__chumicro_runtimes__`` marker for a
            different runtime are dropped, and their imports are not
            walked further.  ``None`` (the default) ships every
            reachable module, matching the prior unfiltered behavior;
            this is the right setting when the runtime selector
            reaches both adapters at import time and you want the
            unmatched one available so the selector can fail loudly
            on misclassification.  The entrypoint itself is never
            filtered.

    Raises:
        FileNotFoundError: If *entrypoint* does not exist.
        NotADirectoryError: If any of *search_paths* is not a
            directory.
    """

    def __init__(
        self,
        entrypoint: Path,
        *,
        search_paths: list[Path],
        extra_modules: list[str] | None = None,
        device_entrypoint: str = "/code.py",
        resource_prefix: str = "/lib",
        target_runtime: str | None = None,
    ) -> None:
        if not entrypoint.is_file():
            raise FileNotFoundError(f"ImportGraphSource entrypoint not found: {entrypoint}")
        for search_path in search_paths:
            if not search_path.is_dir():
                raise NotADirectoryError(
                    f"ImportGraphSource search path not a directory: {search_path}"
                )
        self._entrypoint_path = entrypoint
        self._search_paths = list(search_paths)
        self._extra_modules = list(extra_modules) if extra_modules else []
        self._device_entrypoint = device_entrypoint
        self._resource_prefix = resource_prefix
        self._target_runtime = target_runtime
        self._files = self._collect()

    def _collect(self) -> dict[str, bytes]:
        collected: dict[str, bytes] = {
            self._device_entrypoint: self._entrypoint_path.read_bytes(),
        }
        visited: set[str] = set()
        queue: list[str] = self._imports_from_file(self._entrypoint_path)
        queue.extend(self._extra_modules)

        while queue:
            module_name = queue.pop(0)
            if module_name in visited:
                continue
            visited.add(module_name)
            resolved_path = self._resolve_module(module_name)
            if resolved_path is None:
                continue
            if not file_targets_runtime(
                resolved_path, target_runtime=self._target_runtime,
            ):
                # Wrong-runtime module: drop it and don't walk its
                # imports — they are likely runtime-specific too.
                continue
            device_path = self._device_path_for(module_name, resolved_path)
            collected[device_path] = resolved_path.read_bytes()
            queue.extend(self._imports_from_file(resolved_path))
        return collected

    def _imports_from_file(self, path: Path) -> list[str]:
        try:
            tree = ast.parse(path.read_bytes())
        except SyntaxError:
            return []
        discovered: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                discovered.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                discovered.append(node.module)
                # ``from foo.bar import baz`` could be importing a
                # ``foo/bar/baz.py`` submodule or a name defined in
                # ``foo/bar/__init__.py``.  AST can't tell — probe both.
                # ``_resolve_module`` skips names that don't resolve to
                # a real file, so probing harmless function/class names
                # is a no-op.  Closes the gap where a runtime-gated
                # ``from chumicro_sockets._adapters import mp`` inside
                # a function body shipped only ``_adapters/__init__.py``,
                # not the named adapter file.
                for alias in node.names:
                    if alias.name != "*":
                        discovered.append(f"{node.module}.{alias.name}")
        return discovered

    def _resolve_module(self, module_name: str) -> Path | None:
        dotted_parts = module_name.split(".")
        for search_path in self._search_paths:
            module_file = search_path.joinpath(*dotted_parts).with_suffix(".py")
            if module_file.is_file():
                return module_file
            package_init = search_path.joinpath(*dotted_parts) / "__init__.py"
            if package_init.is_file():
                return package_init
        return None

    def _device_path_for(self, module_name: str, resolved_path: Path) -> str:
        dotted_parts = module_name.split(".")
        if resolved_path.name == "__init__.py":
            relative_device = "/".join([*dotted_parts, "__init__.py"])
        else:
            relative_device = "/".join([*dotted_parts[:-1], dotted_parts[-1] + ".py"])
        prefix = self._resource_prefix.rstrip("/")
        return f"{prefix}/{relative_device}" if prefix else f"/{relative_device}"

    def files(self) -> dict[str, bytes]:
        return dict(self._files)

    def entrypoint(self) -> str:
        return self._device_entrypoint
