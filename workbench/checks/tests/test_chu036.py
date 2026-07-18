"""Tests for CHU036: no subscript-dunder attribute use in device code.

Covers the flag on device library source and device-marked examples in
both the call and the bare-reference form, the exemptions (super()
override, a self / cls receiver, host code, a noqa line, a bare
definition), and the silent no-op when no trees exist.
"""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu036 import CHU036


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


_BUG = "flag = [False]\nflag.__setitem__(0, True)\n"
_DEVICE_MARKER = '__chumicro_runtimes__ = ("circuitpython", "micropython")\n'


def test_flags_device_library_source(tmp_path: Path):
    _write(tmp_path / "libraries" / "mqtt" / "src" / "chumicro_mqtt" / "c.py", _BUG)
    findings = CHU036.check(tmp_path)
    assert len(findings) == 1
    assert findings[0].code == "CHU036"
    assert findings[0].line == 2


def test_flags_device_marked_example(tmp_path: Path):
    _write(
        tmp_path / "libraries" / "mqtt" / "examples" / "telemetry.py",
        _DEVICE_MARKER + _BUG,
    )
    findings = CHU036.check(tmp_path)
    assert len(findings) == 1


def test_getitem_and_delitem_also_flagged(tmp_path: Path):
    body = "d = {}\nd.__getitem__('k')\nd.__delitem__('k')\n"
    _write(tmp_path / "libraries" / "kv" / "src" / "chumicro_kv" / "c.py", body)
    assert len(CHU036.check(tmp_path)) == 2


def test_bare_reference_flagged(tmp_path: Path):
    # Captured for later, never called inline — still an AttributeError on a
    # built-in receiver on-device.
    body = "flag = [False]\nhandler = flag.__setitem__\n"
    _write(tmp_path / "libraries" / "mqtt" / "src" / "chumicro_mqtt" / "c.py", body)
    findings = CHU036.check(tmp_path)
    assert len(findings) == 1
    assert findings[0].line == 2


def test_self_receiver_not_flagged(tmp_path: Path):
    # ``self`` binds a user-defined class, which exposes its own dunders
    # on-device, so calling one on ``self`` is safe.
    body = (
        "class D:\n"
        "    def __setitem__(self, k, v):\n"
        "        self._d = v\n"
        "    def copy_into(self, k, v):\n"
        "        self.__setitem__(k, v)\n"
    )
    _write(tmp_path / "libraries" / "kv" / "src" / "chumicro_kv" / "c.py", body)
    assert CHU036.check(tmp_path) == []


def test_cls_receiver_not_flagged(tmp_path: Path):
    body = (
        "class D:\n"
        "    def __setitem__(self, k, v):\n"
        "        pass\n"
        "    @classmethod\n"
        "    def seed(cls, obj, k, v):\n"
        "        cls.__setitem__(obj, k, v)\n"
    )
    _write(tmp_path / "libraries" / "kv" / "src" / "chumicro_kv" / "c.py", body)
    assert CHU036.check(tmp_path) == []


def test_attribute_of_self_still_flagged(tmp_path: Path):
    # ``self.buf`` may be a built-in list; only a direct ``self`` receiver is
    # exempt, not an attribute reached through it.
    body = (
        "class D:\n"
        "    def store(self, k, v):\n"
        "        self.buf.__setitem__(k, v)\n"
    )
    _write(tmp_path / "libraries" / "kv" / "src" / "chumicro_kv" / "c.py", body)
    findings = CHU036.check(tmp_path)
    assert len(findings) == 1
    assert findings[0].line == 3


def test_super_override_not_flagged(tmp_path: Path):
    body = (
        "class D(dict):\n"
        "    def __setitem__(self, k, v):\n"
        "        super().__setitem__(k, v)\n"
    )
    _write(tmp_path / "libraries" / "kv" / "src" / "chumicro_kv" / "c.py", body)
    assert CHU036.check(tmp_path) == []


def test_definition_not_flagged(tmp_path: Path):
    body = "class D:\n    def __setitem__(self, k, v):\n        self._d = v\n"
    _write(tmp_path / "libraries" / "kv" / "src" / "chumicro_kv" / "c.py", body)
    assert CHU036.check(tmp_path) == []


def test_host_code_not_flagged(tmp_path: Path):
    # workbench src is CPython tooling with no device runtime marker.
    _write(
        tmp_path / "workbench" / "deploy" / "src" / "chumicro_deploy" / "c.py",
        _BUG,
    )
    assert CHU036.check(tmp_path) == []


def test_unmarked_example_not_flagged(tmp_path: Path):
    # No __chumicro_runtimes__ marker → host example, attribute form is fine.
    _write(tmp_path / "libraries" / "mqtt" / "examples" / "host_only.py", _BUG)
    assert CHU036.check(tmp_path) == []


def test_noqa_suppresses(tmp_path: Path):
    body = "flag = [False]\nflag.__setitem__(0, True)  # noqa: CHU036\n"
    _write(tmp_path / "libraries" / "mqtt" / "src" / "chumicro_mqtt" / "c.py", body)
    assert CHU036.check(tmp_path) == []


def test_no_trees_is_silent(tmp_path: Path):
    assert CHU036.check(tmp_path) == []
