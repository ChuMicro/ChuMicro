# third_party_template — portability fixture for chumicro-deploy

A deliberately non-chumicro project layout that uses
`chumicro-deploy`'s public API to deploy onto a device.  The fixture
ships:

- A **custom FileSource** (`my_template.CustomLayoutFileSource`) that
  reads files from this template's `project/source/` + `project/helpers/`
  directories — a layout that looks nothing like chumicro's
  `libraries/` mono-repo shape.
- A **deploy manifest** (`project/deploy.json`) specifying which file
  in the template is the entrypoint and where each file should land
  on-device.
- `project/source/app.py` + `project/helpers/greeter.py` — sample
  payload a real third-party template might ship.

The fixture exists under
`workbench/deploy/tests/fixtures/third_party_template/` so it can be
imported directly by `test_third_party_portability.py` without
needing a real `pip install`.  A real third-party template repo
would ship an equivalent tree plus its own `pyproject.toml`
declaring whatever dependencies its loader needs — none from
chumicro itself beyond the `chumicro-deploy` PyPI package.

Nothing in this fixture imports from chumicro's mono repo
(`libraries/`, `support/`, `scripts/`); the only chumicro dependency
is `chumicro_deploy` (which a real third party `pip install`s from
PyPI).  If that invariant ever breaks, the portability test fails
and this fixture is the proof point.
