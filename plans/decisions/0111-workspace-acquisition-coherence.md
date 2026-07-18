# Decision 0111: Workspace package acquisition coherence

Status: `accepted`
Date: `2026-07-18`
Summary: One release ships four artifacts; support packages publish on a VERSION file, experimental rewrites optional-deps, and a fresh workspace defaults to experimental until stable ships.
Related: Decision [0101](0101-ship-channel-selection-contract.md) (channel is a repo), [0078](0078-library-acquisition-is-host-local.md) (host-local acquisition), [0032](0032-workbench-host-tools.md) (workbench is PyPI-only), [0082](0082-test-harness-as-infrastructure-library.md) (test-harness placement), [0038](0038-workspace-bootstrap-via-clone.md) (clone bootstrap), [0023](0023-standalone-promote-workflow.md) (stable promotion).

## Context

A release produces four artifacts from one source tree: the PyPI wheel (importable package only), the PyPI sdist (whole tree with tests and examples), the device bundle for mip and circup, and the host libraries channel that `chumicro-workspace library add` reads. Each has a different consumer, and a first real end-to-end publish exposed three ways they disagreed. A downstream workspace could not install a library's `[test]` extra (it named unpublished stable projects), a fresh regular-mode clone pointed every default at the stable channel that is still mid-publication, and `run.py repl` failed because no artifact declared `chumicro-repl`. This record fixes those and names the coherence questions that remain open.

## Decision

- **Support packages publish once they carry a VERSION file.** `support/` holds host-only infrastructure kept out of the device bundle, the same as workbench (Decision 0032). Such a package stays unpublished until it gains a VERSION file, at which point `release_matrix` picks it up as `kind=support` (PyPI only, no bundle). `chumicro-test-harness` is the first, so the `[test]` extra every library declares becomes installable. The package keeps living in `support/`.

- **Experimental release rewrites optional-dependencies, not just runtime dependencies.** `patch-experimental` appends `-experimental` to intra-chumicro entries in both `[project].dependencies` and `[project.optional-dependencies]`. Without the second rewrite, `pip install chumicro-<lib>-experimental[test]` resolves against stable test tooling that does not exist on the pre-release channel. Non-chumicro extras such as `pytest` are left untouched.

- **A fresh workspace defaults to the experimental channel until stable is complete.** `DEFAULT_CHANNEL` in `curated_libraries.py` and the template's tooling manifest both target experimental. Experimental carries the full, current set; a stable default would 404 or serve a stale snapshot on a clone made today. This is a launch-window default with an explicit revert: at stable launch, once the promotion wave lands every library and `ChuMicro-Bundle` goes public, `DEFAULT_CHANNEL` returns to `stable` and the template manifest drops the `-experimental` suffixes.

- **Regular-mode bootstrap installs the chumicro tooling from a requirements manifest.** The workspace template's `run.py setup`, in regular mode, installs `requirements.txt` (`chumicro-workspace`, `-repl`, `-pytest-device`, `-checks`), then the workspace package plus its third-party `[dev]` tools. The manifest is one line per package so what a workspace runs is legible and diffable, and it is the fix for the `run.py repl` gap. Dev mode is unchanged: its sibling checkout already supplies those packages editable. `requirements.txt` is tool-owned (`template_zones.py`), so `update` keeps it in step with the CLI it pins.

## Rejected

- **Bundling tests into the wheel for the workspace.** The workspace acquires library source (tests and examples included) from the libraries channel, not from PyPI (Decision 0078), and CPython pip users do not want tests. The wheel stays lean; the sdist already carries the tree.
- **Re-pointing every doc default at experimental permanently.** The auto-experimental, manual-promote model (Decision 0023) is intact; the experimental default is a launch-window measure, not the end state.
- **Authoring the tooling list only in pyproject.** A one-per-line `requirements.txt` reads better than a buried `[dev]` extra and matches how the mono-repo states its own dev tooling.

## Consequences

- The experimental channel is self-consistent: a library, its runtime deps, and its `[test]` extra all resolve on it.
- A fresh regular-mode clone works today; the revert to a stable default is a two-file change gated on the promotion wave finishing.
- Existing workspaces pick up `requirements.txt` only after they upgrade `chumicro-workspace` to the release carrying the zone entry and re-run `update`; fresh clones get it immediately.
- Two coherence questions surfaced here are resolved in Decision [0112](0112-release-identity-and-mpy-abi.md): a release emits a manifest correlating its snapshot to each package version and the two channel tags, and the device bundle will carry parallel mpy folders picked by a runtime-aware resolver at the next ABI bump.
