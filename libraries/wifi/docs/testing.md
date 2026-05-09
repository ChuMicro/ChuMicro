# Testing Helpers

<!-- GENERATION INSTRUCTIONS — delete this block once the page is written.

     This page documents the fakes in the library's `testing` submodule.
     If this library does NOT expose injectable services that downstream
     consumers need to fake, delete all testing-helper references:
       1. Delete this file (`docs/testing.md`)
       2. Delete `src/chumicro_wifi/testing.py`
       3. Remove the `- Testing Helpers: testing.md` line from `mkdocs.yml` nav
       4. Remove the Testing Helpers link from `docs/index.md`
       5. Remove the Testing helpers link from `README.md`

     Libraries that accept dependencies via constructor injection (time,
     I/O, network) should provide ready-made fakes so downstream tests
     don't have to invent their own mocks.

     To fill this in, read:
       1. `src/chumicro_wifi/testing.py` — the fake classes/functions
       2. `tests/` — see how the fakes are used in this library's own tests
       3. Existing examples: libraries/timing/docs/testing.md,
          libraries/runner/docs/testing.md

     Structure:
       - Open with one sentence: what the module provides and why.
       - One section per fake class, showing a realistic test snippet.
       - A "Usage from other libraries" section with a cross-library import.
       - An "API Reference" section with a ::: autodoc directive. -->

`chumicro_wifi.testing` provides ...

## Usage

<!-- Show a realistic test snippet using the fake.  Import from the public
     testing submodule.  Use descriptive variable names. -->

```python
from chumicro_wifi.testing import Fake...

def test_example():
    ...
```

## Usage from other libraries

Libraries that depend on `chumicro-wifi` can import the fakes directly:

```python
from chumicro_wifi.testing import Fake...
```

Project convention: libraries that expose injectable services ship their own test fakes alongside the production code.

## API Reference

::: chumicro_wifi.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi) · \
[PyPI](https://pypi.org/project/chumicro-wifi/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
