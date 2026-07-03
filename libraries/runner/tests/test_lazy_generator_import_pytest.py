"""Import-time isolation of the generator machinery (M50).

A plain periodic-blink app that only calls ``add`` / ``add_periodic``
must not drag ``chumicro_runner._generator`` (~9 KB of source, two
classes) into RAM.  This runs a fresh interpreter so ``sys.modules``
starts clean, then confirms a bare ``import chumicro_runner`` leaves
``_generator`` unimported until the ``GeneratorHandle`` re-export or
``add_generator`` names it.

CPython-only: uses ``subprocess`` + ``sys.executable`` to control the
module cache, which real silicon can't do.
"""

#: CPython-only lane (spawns a subprocess to get a clean import cache).
__chumicro_runtimes__ = ("cpython",)

import subprocess
import sys


def _run(snippet: str) -> "subprocess.CompletedProcess[str]":
    """Run *snippet* in a fresh interpreter; return the completed process."""
    return subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
    )


def test_import_runner_does_not_load_generator_module():
    """A bare ``import chumicro_runner`` leaves ``_generator`` out of
    ``sys.modules``; touching ``GeneratorHandle`` then loads it."""
    result = _run(
        "import sys\n"
        "import chumicro_runner\n"
        "assert 'chumicro_runner._generator' not in sys.modules\n"
        "chumicro_runner.GeneratorHandle\n"
        "assert 'chumicro_runner._generator' in sys.modules\n"
    )
    assert result.returncode == 0, result.stderr


def test_add_periodic_path_never_loads_generator_module():
    """Registering only a periodic handler keeps ``_generator``
    unimported for the life of the app."""
    result = _run(
        "import sys\n"
        "from chumicro_runner import Runner\n"
        "from chumicro_timing.testing import FakeTicks\n"
        "runner = Runner(ticks=FakeTicks())\n"
        "runner.add_periodic(lambda now_ms: None, period_ms=10)\n"
        "runner.tick()\n"
        "assert 'chumicro_runner._generator' not in sys.modules\n"
    )
    assert result.returncode == 0, result.stderr
