"""On-device workspace runtime — boots the active project.

Shipped as a payload by ``chumicro-workspace``; lands on
the device as ``/lib/workspace_runtime/__init__.py``.  The
companion ``/code.py`` (or ``/main.py``) is a fixed two-line
shim::

    import workspace_runtime
    workspace_runtime.boot()

:func:`boot` reads ``/active.py`` (a one-line module written by
the host-side deploy that names the active project), imports the
matching ``projects.<name>.app`` module, and calls its
``run()`` function.

The contract: the shim is stable, the project's ``app.py`` is the
user-facing edit surface, and ``active.py`` is the deploy-time
selector that lets a single device hold multiple project payloads
but boot only one.

Cross-runtime: this module runs on CircuitPython, MicroPython,
and CPython.  No f-strings on hot paths is overkill (CP / MP
both support them); the body uses string concatenation in error
messages so failures during bootstrap don't trip on a syntax
error path that the user can't see.
"""


class WorkspaceBootError(RuntimeError):
    """Boot couldn't reach a runnable ``app.run()``.

    Carries the reason in the message so the on-device traceback
    points at the recovery action without the user having to
    grep through this module.
    """


def boot():
    """Locate the active project and run it.

    Reads ``/active.py``'s ``PROJECT_NAME``, imports
    ``projects.<PROJECT_NAME>.app``, and calls ``app.run()``.  Errors
    surface as :class:`WorkspaceBootError` with a descriptive
    message so the device REPL or ``run.py repl --tail`` shows the
    user where the boot pipeline broke.

    Raises:
        WorkspaceBootError: ``/active.py`` is missing or has no
            ``PROJECT_NAME``; the named project's ``app.py`` can't be
            imported; or ``app.py`` exists but has no ``run()``
            attribute.
    """
    try:
        import active
    except ImportError as exception:
        raise WorkspaceBootError(
            "/active.py missing — deploy may not have run, or "
            "the project was deployed without the boot shim. "
            "Original ImportError: " + str(exception),
        ) from exception
    project_name = getattr(active, "PROJECT_NAME", None)
    if not project_name:
        raise WorkspaceBootError(
            "/active.py exists but has no PROJECT_NAME attribute. "
            "Deploy should write `PROJECT_NAME = \"<name>\"` at the top.",
        )
    module_path = "projects." + project_name + ".app"
    try:
        # __import__ with fromlist returns the leaf module directly
        # (no manual getattr walk).  Keep parameters positional so
        # the signature works on CP / MP / CPython without keyword
        # mismatches across versions.
        app_module = __import__(module_path, None, None, ["app"])
    except ImportError as exception:
        raise WorkspaceBootError(
            "could not import " + module_path + ": " + str(exception)
            + ".  Check that the project was deployed and its imports "
            "resolved against /lib/.",
        ) from exception
    run_function = getattr(app_module, "run", None)
    if run_function is None:
        raise WorkspaceBootError(
            module_path + " has no run() function.  Define "
            "`def run(): ...` in app.py — that's the workspace-runtime "
            "boot contract.",
        )
    run_function()
