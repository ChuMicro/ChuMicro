"""File sources: plug-in input types that feed the Deployer.

A :class:`FileSource` produces two things: a mapping of on-device
paths to byte contents, and the name of the entrypoint file the
runtime should boot into.  Three built-ins cover the common cases:

- :class:`FileMapSource` when the caller already has an in-memory dict.
- :class:`DirectorySource` to ship a directory tree from disk.
- :class:`ImportGraphSource` to walk imports from an entrypoint file
  and ship exactly the transitively-reachable modules.

Custom sources implement the :class:`FileSource` protocol.  The
protocol is :func:`~typing.runtime_checkable` so ``isinstance`` works
at the deployer boundary.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Protocol, runtime_checkable

from .import_allowlist import is_device_builtin
from .protocol import validate_entrypoint_in_files
from .runtime_marker import file_targets_runtime, is_test_support_module
from .skip_factories import (
    discover_factory_modules,
    read_skip_factories_marker,
    resolve_skip_targets,
)


class UnresolvedImportError(Exception):
    """Raised when an import walk reaches a module that ships nowhere.

    :class:`ImportGraphSource` refuses the deploy at construction time when an
    ``import`` in the bundle resolves to no file under any search path and the
    module name is not a known device-runtime built-in (see
    :data:`chumicro_deploy.import_allowlist.DEVICE_BUILTIN_MODULES`).  Such an
    import would ship silently and raise :exc:`ImportError` from the device
    runtime at first boot; refusing here turns a boot-time crash into a
    deploy-time error that names the importing file and the missing module.

    The message leads with ``"Deploy refused: unresolved import"`` so
    :func:`chumicro_deploy.recovery.classify_deploy_failure` routes it to
    :attr:`~chumicro_deploy.recovery_kind.DeployFailureKind.UNRESOLVED_IMPORT`
    without coupling the classifier to this subclass.

    Attributes:
        unresolved: Every ``(importing_file, module_name)`` pair the walk
            collected before refusing.  Collect-all-then-fail, so a single
            deploy attempt surfaces every missing module at once.
    """

    def __init__(self, unresolved: list[tuple[Path, str]]) -> None:
        self.unresolved = list(unresolved)
        lines = [
            f"  {importing_file} imports {module_name!r}, which resolves to no "
            "deployed file and is not a known device built-in"
            for importing_file, module_name in self.unresolved
        ]
        body = "\n".join(lines)
        super().__init__(
            "Deploy refused: unresolved import"
            f"{'s' if len(self.unresolved) != 1 else ''}.\n"
            f"{body}\n"
            "Register the module under a deploy search path, fix the typo, "
            "or, if it is a genuine runtime built-in, list it in the "
            "CHUMICRO_DEPLOY_EXTRA_BUILTINS environment variable "
            "(comma-separated top-level names).  An ImportError-guarded "
            "import (try/except ImportError) is treated as optional and "
            "never refused."
        )


@runtime_checkable
class FileSource(Protocol):
    """What the Deployer expects from any file source.

    Implementations return the deploy-time file map and declare which
    of those files is the entrypoint.  The Deployer does not mutate
    either result.  Sources own their own state.
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
            in the produced file map, i.e. must be a file under
            *root* (relative to *resource_prefix*).
        resource_prefix: On-device prefix prepended to each file's
            path.  Defaults to ``/`` (files land at the top of the
            device filesystem).
        excluded_names: Filename / directory names to skip entirely
            (exact match, not glob).  Defaults to common artifacts
            (``__pycache__``, ``.DS_Store``, ``.git``, etc.).
        target_runtime: When set (``"circuitpython"`` / ``"micropython"``
            / ``"cpython"``), ``.py`` files carrying a
            ``__chumicro_runtimes__`` marker are skipped if the marker
            doesn't include *target_runtime*.  ``None`` (the default)
            ships every file.  Non-``.py`` files are unaffected.

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
            if file_path.suffix == ".py" and (
                not file_targets_runtime(
                    file_path, target_runtime=self._target_runtime,
                )
                or is_test_support_module(file_path)
            ):
                # Wrong-runtime, or a test-support module (testing.py
                # fakes), which must not ship.
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


def _exists_case_strict(path: Path) -> bool:
    """Return True iff *path* exists with its exact filename casing.

    Necessary on case-insensitive host filesystems (default macOS
    APFS, NTFS) where :meth:`Path.is_file` returns True for case-
    mismatched lookups: a ``Heartbeat.py`` probe matches an on-disk
    ``heartbeat.py``.  Without this strictness :class:`ImportGraphSource`
    can't tell ``from chumicro_timing import Heartbeat`` (a *class*
    import, where Heartbeat lives inside ``heartbeat.py``) apart from
    ``from chumicro_timing import heartbeat`` (a *submodule* import,
    which pulls in the file).  The class case isn't a module the walker
    should follow; treating it as one stages a ``Heartbeat.py`` path
    that breaks on the device's case-sensitive filesystem (LittleFS).
    """
    try:
        return path.name in (entry.name for entry in path.parent.iterdir())
    except OSError:
        return False


class ImportGraphSource:
    """A source that walks Python imports starting from an entrypoint.

    Parses *entrypoint* with the ``ast`` module, collects every
    ``import`` and ``from ... import`` target, resolves each one
    against *search_paths* (first match wins), and recursively walks
    the resolved modules.  Packages are walked through their
    ``__init__.py``.  Dynamic imports (``importlib.import_module``,
    ``__import__``) are not detected; pass those names explicitly via
    *extra_modules*.

    A module name that doesn't resolve against any search path is
    either a device-runtime built-in (``gc``, ``time``, ``board``)
    the host can't provide, or a library the walk should have found
    but didn't (missing from the search paths, or a typo).  The two
    look identical at the AST level, since both are bare module names.
    :class:`ImportGraphSource` distinguishes them by an explicit
    allowlist: a name on
    :data:`chumicro_deploy.import_allowlist.DEVICE_BUILTIN_MODULES`
    is skipped as a built-in; any other unresolved *required* import
    is collected, and the constructor raises
    :class:`UnresolvedImportError` naming every importing file and
    missing module rather than shipping an import that would
    :exc:`ImportError` at first boot.  Two cases are exempt: an
    import guarded by ``try: ... except ImportError`` (a deliberate
    optional fallback), and the speculative ``module.name`` probe the
    walk uses to resolve ``from module import name`` against a real
    submodule.  When ``name`` is a function or class in
    ``module/__init__.py`` instead, the probe doesn't resolve and is
    silently dropped.

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
        target_runtime: When set (``"circuitpython"`` / ``"micropython"``
            / ``"cpython"``), modules carrying a ``__chumicro_runtimes__``
            marker for a different runtime are dropped, and their
            imports are not walked further.  ``None`` (the default)
            ships every reachable module, the right setting when the
            runtime selector reaches both adapters at import time and
            you want the unmatched one available so the selector can
            fail loudly on misclassification.  The entrypoint itself
            is never filtered.

    Honors a module-level ``__chumicro_skip_factories__`` opt-out on
    *entrypoint*; see :mod:`chumicro_deploy.skip_factories` for the
    marker shape and matching rules.  Diagnostics (direct-import
    overrides, dead-skip notices) surface through
    :attr:`skip_factories_warnings`.

    Raises:
        FileNotFoundError: If *entrypoint* does not exist.
        NotADirectoryError: If any of *search_paths* is not a
            directory.
        ValueError: If ``__chumicro_skip_factories__`` lists entries
            that match zero discovered factory modules.
        UnresolvedImportError: If a required import resolves to no
            file under any search path and is not a known device
            built-in.  Carries every offending ``(file, module)`` pair.
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
        self._host_paths: list[Path] = []
        self._skip_warnings: list[str] = []
        self._skip_per_entry: dict[str, frozenset[str]] = {}
        self._unresolved: list[tuple[Path, str]] = []
        self._skip_modules = self._compute_skip_modules()
        self._files = self._collect()
        if self._unresolved:
            raise UnresolvedImportError(self._unresolved)

    def _compute_skip_modules(self) -> frozenset[str]:
        """Resolve ``__chumicro_skip_factories__`` to fully-qualified module names.

        Returns the set of module names the queue loop should drop.
        Empty frozenset when the entrypoint declares no marker.  Raises
        :class:`ValueError` on typo'd entries.  Direct-import overrides
        (skip targets the entrypoint imports explicitly) are recorded
        as warnings and removed from the returned set so they ship.
        Stores the per-entry match mapping on ``self._skip_per_entry``
        for later dead-skip diagnostics.
        """
        skip_entries = read_skip_factories_marker(self._entrypoint_path)
        if not skip_entries:
            return frozenset()
        discovered = discover_factory_modules(self._search_paths)
        per_entry, unmatched = resolve_skip_targets(skip_entries, discovered)
        if unmatched:
            raise ValueError(
                "__chumicro_skip_factories__ entries did not match any "
                f"discovered factory module: {list(unmatched)!r}.  "
                "Discovered families: "
                f"{sorted(set(discovered.values()))!r}.",
            )
        matched: set[str] = set()
        for matches in per_entry.values():
            matched.update(matches)
        entrypoint_imports = {
            module_name
            for module_name, _is_required, _path in self._imports_from_file(
                self._entrypoint_path,
            )
        }
        overrides = matched & entrypoint_imports
        for override in sorted(overrides):
            self._skip_warnings.append(
                f"__chumicro_skip_factories__ names {override!r} but the "
                "entrypoint imports it directly; shipping it anyway.",
            )
        self._skip_per_entry = per_entry
        return frozenset(matched - overrides)

    def skip_factories_warnings(self) -> tuple[str, ...]:
        """Return diagnostic messages emitted by the skip mechanism.

        Direct-import overrides and dead-skip notices land here.
        Empty tuple when the deploy used no skip mechanism or nothing
        was worth saying.
        """
        return tuple(self._skip_warnings)

    def _collect(self) -> dict[str, bytes]:
        collected: dict[str, bytes] = {
            self._device_entrypoint: self._entrypoint_path.read_bytes(),
        }
        self._host_paths.append(self._entrypoint_path)
        visited: set[str] = set()
        # Each queue entry is (module_name, is_required, importing_file).
        # is_required marks a real ``import``/``from`` module that must
        # resolve to a file or a known built-in; speculative
        # ``module.name`` alias probes ride along as not-required so they
        # never trip the unresolved-import refusal.
        queue: list[tuple[str, bool, Path]] = self._imports_from_file(
            self._entrypoint_path,
        )
        queue.extend(
            (name, True, self._entrypoint_path) for name in self._extra_modules
        )

        # Names already recorded as required-and-unresolved, so two imports
        # of the same broken module don't double-report it.
        reported_unresolved: set[str] = set()

        while queue:
            module_name, is_required, importing_file = queue.pop(0)
            resolved_path = (
                None
                if module_name in self._skip_modules
                else self._resolve_module(module_name)
            )
            if (
                resolved_path is None
                and is_required
                and module_name not in self._skip_modules
                and module_name not in reported_unresolved
                and not is_device_builtin(module_name)
            ):
                # A real import that ships nowhere and isn't a runtime
                # built-in.  Record it; the constructor refuses the deploy
                # after the whole walk so one attempt surfaces every missing
                # module, not just the first.  Checked before the visited
                # guard so a required import is never masked by a prior
                # not-required ``from x import name`` probe of the same name.
                reported_unresolved.add(module_name)
                self._unresolved.append((importing_file, module_name))
            if module_name in visited:
                continue
            visited.add(module_name)
            if module_name in self._skip_modules:
                # User opted this factory out at the entrypoint via
                # __chumicro_skip_factories__.  Drop without resolving
                # so its closure (typically chumicro_sockets) is not
                # pulled in.
                continue
            if resolved_path is None:
                continue
            if not file_targets_runtime(
                resolved_path, target_runtime=self._target_runtime,
            ) or is_test_support_module(resolved_path):
                # Wrong-runtime module, or a test-support module
                # (testing.py fakes): drop it and don't walk its
                # imports, which are likely runtime-specific too.
                continue
            device_path = self._device_path_for(module_name, resolved_path)
            collected[device_path] = resolved_path.read_bytes()
            self._host_paths.append(resolved_path)
            # Stage any sibling data files the module declares via
            # __chumicro_data_files__ (e.g. a CA bundle .der).  The import
            # walk can't see a runtime ``open`` of such a file, so without
            # this it ships nowhere and the device crashes when the module
            # reads it.
            device_dir = device_path.rsplit("/", 1)[0] if "/" in device_path else ""
            for data_name in self._data_files_from(resolved_path):
                data_source = resolved_path.parent / data_name
                if not data_source.is_file():
                    continue
                data_device_path = (
                    f"{device_dir}/{data_name}" if device_dir else data_name
                )
                collected[data_device_path] = data_source.read_bytes()
                self._host_paths.append(data_source)
            queue.extend(self._imports_from_file(resolved_path))
        self._check_dead_skips(visited)
        return collected

    @staticmethod
    def _data_files_from(path: Path) -> list[str]:
        """Return the string entries of a module-level
        ``__chumicro_data_files__`` assignment, or ``[]`` when absent.

        Extracted by AST (not import) so it works on a host that can't
        import the device module; names sibling data files the module
        opens at runtime that the import graph can't otherwise discover.
        """
        try:
            tree = ast.parse(path.read_bytes())
        except (SyntaxError, ValueError):
            return []
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "__chumicro_data_files__"
                    and isinstance(node.value, (ast.Tuple, ast.List))
                ):
                    return [
                        element.value
                        for element in node.value.elts
                        if isinstance(element, ast.Constant)
                        and isinstance(element.value, str)
                    ]
        return []

    def _check_dead_skips(self, visited: set[str]) -> None:
        """Emit an informational warning per user-written entry whose
        matched modules' parent libraries were never imported.

        For an exact-form entry like ``"chumicro_sockets.sockets_factory"``,
        dead means the user lists it but never imports ``chumicro_sockets``.
        For a family-form entry like ``"sockets_factory"``, dead means none
        of the libraries owning a matched module were reached.  An entry
        whose matched module the deploy does reach is *not* dead.

        Visit-set membership of the skip targets themselves is excluded
        from the "reached anything" check: the targets are added to the
        visited set before the skip filter runs, so they always look
        reached.
        """
        for entry, matched in self._skip_per_entry.items():
            parent_packages = {target.rsplit(".", 1)[0] for target in matched}
            reached_anything = any(
                seen not in matched and (
                    seen in parent_packages
                    or any(seen.startswith(f"{parent}.") for parent in parent_packages)
                )
                for seen in visited
            )
            if not reached_anything:
                self._skip_warnings.append(
                    f"__chumicro_skip_factories__ entry {entry!r} matches "
                    f"{sorted(matched)!r} but none of those libraries are "
                    "imported; skip entry has no effect.",
                )

    def _imports_from_file(self, path: Path) -> list[tuple[str, bool, Path]]:
        """Return ``(module_name, is_required, path)`` for *path*'s imports.

        *is_required* is ``True`` for a real ``import x`` / ``from x import``
        module the device must be able to import, and ``False`` for the
        speculative ``x.name`` probe that resolves ``from x import name``
        against a possible submodule.  An import nested in a
        ``try: ... except ImportError`` (or bare ``except``) block is omitted
        entirely, because it is a deliberate optional fallback and a device that
        can't import it isn't broken.  Returns an empty list on a syntax
        error (the file still ships as bytes; its imports just contribute no
        walk targets).
        """
        try:
            tree = ast.parse(path.read_bytes())
        except SyntaxError:
            return []
        guarded = self._import_error_guarded_names(tree)
        discovered: list[tuple[str, bool, Path]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                discovered.extend(
                    (alias.name, alias.name not in guarded, path)
                    for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                module_guarded = node.module in guarded
                discovered.append((node.module, not module_guarded, path))
                # ``from foo.bar import baz`` could be importing a
                # ``foo/bar/baz.py`` submodule or a name defined in
                # ``foo/bar/__init__.py``.  AST can't tell which form
                # an import resolves to, so probe ``foo.bar.baz`` as a
                # candidate submodule.  The probe is never *required*:
                # when ``baz`` is a function or class in
                # ``foo/bar/__init__.py`` it resolves to no file, and
                # dropping it silently is correct (the package itself
                # already shipped).  Without this probe, a runtime-gated
                # ``from chumicro_sockets._adapters import mp`` inside a
                # function body ships only ``_adapters/__init__.py``,
                # not the named adapter file.
                for alias in node.names:
                    if alias.name != "*":
                        discovered.append(
                            (f"{node.module}.{alias.name}", False, path),
                        )
        return discovered

    @staticmethod
    def _import_error_guarded_names(tree: ast.Module) -> set[str]:
        """Return module names imported inside an ``ImportError``-guarded block.

        ``ast.walk`` flattens the tree, so a ``try: import foo`` /
        ``except ImportError:`` guard is invisible to the flat import scan:
        the guarded ``import foo`` looks identical to a top-level one.  This
        re-reads the structure: every ``ast.Try`` whose handlers catch
        ``ImportError`` (or are bare, or catch ``Exception``) contributes the
        top-level module name of each import in its ``try`` body.  A guarded
        import is a deliberate optional fallback, so the walker must not
        refuse a deploy over a device that can't import it.
        """
        guarded: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            if not any(
                ImportGraphSource._handler_catches_import_error(handler)
                for handler in node.handlers
            ):
                continue
            for statement in node.body:
                for inner in ast.walk(statement):
                    if isinstance(inner, ast.Import):
                        guarded.update(alias.name for alias in inner.names)
                    elif (
                        isinstance(inner, ast.ImportFrom)
                        and inner.module
                        and inner.level == 0
                    ):
                        guarded.add(inner.module)
        return guarded

    @staticmethod
    def _handler_catches_import_error(handler: ast.ExceptHandler) -> bool:
        """Return whether *handler* catches ``ImportError``.

        A bare ``except:`` (``handler.type is None``) catches everything, so
        it counts.  Otherwise the caught type must name ``ImportError`` or its
        broader parents ``Exception`` / ``BaseException``, directly or inside
        an ``except (ImportError, OSError):`` tuple.
        """
        caught = handler.type
        if caught is None:
            return True
        catching_names = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}
        if isinstance(caught, ast.Name):
            return caught.id in catching_names
        if isinstance(caught, ast.Tuple):
            return any(
                isinstance(element, ast.Name) and element.id in catching_names
                for element in caught.elts
            )
        return False

    def _resolve_module(self, module_name: str) -> Path | None:
        dotted_parts = module_name.split(".")
        for search_path in self._search_paths:
            module_file = search_path.joinpath(*dotted_parts).with_suffix(".py")
            if module_file.is_file() and _exists_case_strict(module_file):
                return module_file
            package_init = search_path.joinpath(*dotted_parts) / "__init__.py"
            if package_init.is_file() and _exists_case_strict(package_init):
                return package_init
        return None

    def _device_path_for(self, module_name: str, resolved_path: Path) -> str:
        dotted_parts = module_name.split(".")
        if resolved_path.name == "__init__.py":
            relative_device = "/".join([*dotted_parts, "__init__.py"])
        else:
            # Use the on-disk filename, not ``dotted_parts[-1]``.  The
            # import statement's case may differ from the file's actual
            # case on the host (e.g. ``from chumicro_timing import
            # Heartbeat`` resolves to ``heartbeat.py`` on case-
            # insensitive APFS), and the device's filesystem (LittleFS
            # on MP, FAT32 on CP CIRCUITPY) needs the real name to
            # import correctly.  The companion check in
            # :func:`_exists_case_strict` rejects case-mismatched
            # lookups upstream so this branch only fires for true
            # submodule imports, but keep the on-disk name here as
            # defense in depth.
            relative_device = "/".join([*dotted_parts[:-1], resolved_path.name])
        prefix = self._resource_prefix.rstrip("/")
        return f"{prefix}/{relative_device}" if prefix else f"/{relative_device}"

    def files(self) -> dict[str, bytes]:
        return dict(self._files)

    def entrypoint(self) -> str:
        return self._device_entrypoint

    def host_paths(self) -> list[Path]:
        """Return the host filesystem paths every contributed module
        was read from, including the entrypoint.

        Returns a copy so callers can mutate without affecting the
        source's internal record.
        """
        return list(self._host_paths)

    def unresolved_imports(self) -> list[tuple[Path, str]]:
        """Return every ``(importing_file, module_name)`` the walk couldn't ship.

        A pair is collected for each required import that resolves to no file
        under any search path and isn't a known device built-in.  A
        successfully-constructed :class:`ImportGraphSource` always returns an
        empty list: a non-empty set aborts construction with
        :class:`UnresolvedImportError` (whose ``unresolved`` attribute carries
        the same pairs).  The accessor exists so a caller that builds the
        source under its own ``try`` can read the collected pairs off either
        side.
        """
        return list(self._unresolved)
