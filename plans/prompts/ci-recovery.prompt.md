# CI/Release Recovery Plan

Last verified: 2026-04-05

## If CI infrastructure breaks

Revert only CI files — do NOT revert library content (READMEs, source, tests):

```bash
# Revert CI infrastructure files only, back to pre-CI state (c14aed5):
git checkout c14aed5 -- \
  .github/ \
  scripts/check_version.py \
  scripts/check_api.py \
  scripts/bundle.py \
  requirements-dev.txt
git commit -m "Revert CI infrastructure to pre-CI state"
```

This preserves all library code, READMEs, VERSION files, and planning docs.

## Current state quick reference

- **Releases:** manual only (workflow_dispatch), inputs: `libraries` filter + `dry_run`
- **PyPI:** OIDC trusted publishing, environment `pypi`, one pending publisher at a time
- **Bundle:** `ChuMicro/chumicro-bundle` exists, needs `BUNDLE_TOKEN` secret
- **Branches:** `develop` + `main` in sync, protection rules not yet configured
- **Versions:** all libraries at 0.1.0
- **Decisions:** 0002, 0018, 0019, 0020

