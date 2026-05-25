"""Host-side driver for the http_server_roundtrip demo.

Picks a registered device, builds a transport, stages ``app.py`` plus
its library dependencies, runs ``app.py`` on the board concurrently
via :class:`DeviceBootstrapRunner`, and fires HTTP requests against
the routes the board advertises — ``GET /hello``, ``GET /uptime``,
``POST /echo`` — printing each response as it lands.

Run: ``.venv/bin/python demos/http_server_roundtrip/driver.py``
By default targets the first CircuitPython device in ``devices.yml``;
pass ``--device <id>`` or ``--runtime micropython`` to override.

Imports cross the mono-repo intentionally (workbench / fixtures /
internals) — demos are mono-repo native artifacts and the rule
constraining ``examples/`` to library-only imports doesn't apply.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from chumicro_deploy import DeviceEntry, load_device_registry
from msgpack import packb
from chumicro_pytest_device.concurrent_runner import DeviceBootstrapRunner
from chumicro_pytest_device.fixtures.host_driver import bind_to
from chumicro_pytest_device.markers import MarkerTimeoutError
from chumicro_pytest_device.test_runner import (
    build_device_bootstrap,
    build_transport_for_entry,
    resolve_library_source_dirs,
)
from chumicro_workspace import compose_runtime_config

_DEMO_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _DEMO_DIR.parents[1]
_APP_FILE = _DEMO_DIR / "app.py"


def _select_device(
    runtime: str | None, device_id: str | None,
) -> DeviceEntry:
    """Pick a registered device matching the runtime + id filters.

    Raises :class:`SystemExit` when no device matches the filters, or
    when *device_id* and *runtime* are both supplied but resolve to a
    device whose actual runtime doesn't match — silently honouring
    one and ignoring the other would let a typo go undetected.
    """
    entries, _ = load_device_registry(workspace_root=_REPO_ROOT)
    if device_id is not None:
        for entry in entries:
            if entry.identifier == device_id:
                if runtime is not None and entry.runtime != runtime:
                    raise SystemExit(
                        f"driver: --device {device_id!r} is a "
                        f"{entry.runtime!r} board, but --runtime says "
                        f"{runtime!r}.  Drop --runtime or pass a "
                        f"matching device id.",
                    )
                return entry
        raise SystemExit(
            f"driver: no device with id {device_id!r} in devices.yml "
            f"(known: {[entry.identifier for entry in entries]!r})",
        )
    effective_runtime = runtime or "circuitpython"
    for entry in entries:
        if entry.runtime == effective_runtime:
            return entry
    raise SystemExit(
        f"driver: no {effective_runtime!r} device in devices.yml — "
        f"register one with `chumicro-workspace add-device`.",
    )


def _build_runtime_config_payload() -> dict[str, bytes] | None:
    """Read secrets.toml and return ``{path: msgpack_bytes}`` for stage.

    Returns :data:`None` when ``secrets.toml`` is missing — the board's
    ``wifi_up`` will then error out clearly rather than the driver
    silently shipping an empty config.
    """
    secrets_toml = _REPO_ROOT / "secrets.toml"
    if not secrets_toml.is_file():
        return None
    merged = compose_runtime_config(
        secrets_toml=secrets_toml, project_config=None,
    )
    encoded = packb(merged, use_single_float=True)
    return {"/runtime_config.msgpack": encoded}


def _stage_demo(transport, device_entry: DeviceEntry) -> None:
    """Stage ``app.py`` plus every chumicro_* library it imports."""
    libraries_root = _REPO_ROOT / "libraries"
    harness_source = _REPO_ROOT / "support" / "test_harness" / "src"

    # ``resolve_library_source_dirs`` walks the test file's imports +
    # any pyproject dependencies of the supplied library_dir.  Passing
    # the demos dir as library_dir gives an empty pyproject walk; the
    # test_files arg is what carries the real dependency edge from
    # ``app.py``.
    source_dirs = resolve_library_source_dirs(
        _DEMO_DIR,
        libraries_root=libraries_root,
        test_files=[_APP_FILE],
    )

    extra_files = _build_runtime_config_payload()
    if extra_files is None:
        print(
            "driver: secrets.toml not found at repo root — the board's "
            "wifi_up call will fail.  Create secrets.toml with "
            "wifi.ssid + wifi.password before running this demo.",
            file=sys.stderr,
        )

    transport.stage(
        source_dirs,
        [_APP_FILE],
        harness_source,
        extra_files=extra_files,
        include_test_support=False,
    )


def _format_body(body: bytes) -> str:
    """Pretty-print the response body — JSON when valid, repr otherwise."""
    try:
        parsed = json.loads(body)
    except ValueError:
        return repr(body)
    return json.dumps(parsed, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Drive the http_server_roundtrip demo against a registered board.",
    )
    parser.add_argument(
        "--device", default=None,
        help="device id from devices.yml (default: first matching --runtime)",
    )
    parser.add_argument(
        "--runtime", default=None,
        choices=("circuitpython", "micropython"),
        help=(
            "runtime filter — when --device isn't given, picks the "
            "first matching device (default: circuitpython); when "
            "--device IS given, validates the chosen device's runtime "
            "matches"
        ),
    )
    parser.add_argument(
        "--ready-timeout-s", type=float, default=60.0,
        help="seconds to wait for SERVER_READY from the board",
    )
    parser.add_argument(
        "--completion-timeout-s", type=float, default=90.0,
        help="seconds to wait for the bootstrap to finish after the round trip",
    )
    args = parser.parse_args(argv)

    device_entry = _select_device(args.runtime, args.device)
    print(
        f"driver: targeting {device_entry.identifier} "
        f"({device_entry.runtime} @ {device_entry.address})",
    )

    transport = build_transport_for_entry(device_entry)
    transport.connect()
    try:
        _stage_demo(transport, device_entry)
        bootstrap = build_device_bootstrap(
            device_entry, transport, _APP_FILE, function_filter=None,
        )

        runner = DeviceBootstrapRunner(transport, bootstrap)
        runner.start()
        try:
            hit = bind_to(runner)

            print(f"driver: waiting for SERVER_READY (up to {args.ready_timeout_s}s)...")
            try:
                hello_response = hit("/hello", timeout_s=args.ready_timeout_s)
            except MarkerTimeoutError as marker_error:
                print(
                    f"driver: SERVER_READY didn't arrive within "
                    f"{args.ready_timeout_s}s — the board may still be "
                    f"booting, wifi credentials in secrets.toml may be "
                    f"wrong, or the board can't reach the AP.  "
                    f"Detail: {marker_error}",
                    file=sys.stderr,
                )
                return 2
            print(
                f"driver: GET /hello → {hello_response.status} "
                f"{hello_response.reason}\n{_format_body(hello_response.body)}",
            )

            uptime_response = hit("/uptime", timeout_s=10.0)
            print(
                f"driver: GET /uptime → {uptime_response.status} "
                f"{uptime_response.reason}\n{_format_body(uptime_response.body)}",
            )

            echo_payload = b'{"from": "demo driver"}'
            echo_response = hit(
                "/echo", timeout_s=10.0, method="POST", body=echo_payload,
            )
            print(
                f"driver: POST /echo → {echo_response.status} "
                f"{echo_response.reason}\n{_format_body(echo_response.body)}",
            )

            print("driver: waiting for board to print DEMO_COMPLETE...")
            try:
                captured = runner.wait_for_completion(
                    timeout_s=args.completion_timeout_s,
                )
            except TimeoutError as completion_error:
                print(
                    f"driver: board didn't print DEMO_COMPLETE within "
                    f"{args.completion_timeout_s}s — {completion_error}",
                    file=sys.stderr,
                )
                return 3
            if "DEMO_COMPLETE" in captured:
                print("driver: demo completed cleanly.")
                return 0
            print(
                "driver: bootstrap returned without DEMO_COMPLETE — "
                "check the captured stdout below.",
                file=sys.stderr,
            )
            print(captured, file=sys.stderr)
            return 1
        finally:
            # Bounded shutdown so a wedged board after an aborted run
            # doesn't keep the driver alive until the board's own
            # deadline expires.  daemon=True takes the bg thread down
            # on interpreter exit if it's still alive after the bound.
            runner.shutdown(timeout_s=5.0)
    finally:
        try:
            transport.disconnect()
        except Exception as disconnect_error:
            print(
                f"driver: warning — transport.disconnect raised "
                f"{type(disconnect_error).__name__}: {disconnect_error}",
                file=sys.stderr,
            )


if __name__ == "__main__":
    raise SystemExit(main())
