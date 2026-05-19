# Decision 0078: Library acquisition is host-local; the one deploy bundles it

Status: `accepted`
Date: `2026-05-18`
Related: Decision [0077](0077-one-device-staging-path.md) (the one device-staging path — this ADR removes the last out-of-band `/lib` writer it names), Decision [0059](0059-deploy-example-front-door.md) (front-door command shape — sibling collapse in the same phase), Decision [0018](0018-distribution-bundle-repo.md) (bundle repos / PyPI — acquisition *channels* are unchanged; only the destination moves), Decision [0042](0042-library-dependency-policy.md) (transitive deps install recursively; the AST walker is the deploy-time opt-out — still the only filter), `plans/workstreams/deploy-path-unification.md` Phase 3.

## Context

`install-libraries` AST-walks a project for `chumicro_*` imports, then subprocess-shells `circup install` / `mpremote mip install` **straight onto the board's flash**. That `/lib` write never passes through the deploy walker, so a library installed this way is an additive orphan the next clean-slate deploy can't reconcile — the out-of-band `/lib` writer Decision 0077 names in its meta-finding and charters for retirement. Decision 0077 fixed the *production* additive default; this is the remaining second channel.

Dev mode already solved the same problem the right way: a sibling chumicro checkout's `libraries/<name>/src/` is registered in `workspace.yml`'s `library_sources:` map, and the one import-graph deploy bundles each module like any payload. Regular mode (a template-repo user with no sibling checkout) had no equivalent — hence the board-push shortcut.

## Decision

**Library acquisition is a host-local operation. No command writes a device `/lib` except the one deploy stage (Decision 0077).** A library reaches a board only by being resolvable to host source the import-graph walk can see, then bundled by that one deploy.

- `install-libraries` keeps its command surface and its host-side primitives (the `chumicro_*` AST walk, import-name→package-name map, channel selection). Only the subprocess board-push is deleted.
- It now fetches each discovered `chumicro_<name>` into a workspace-local, gitignored, tool-managed tree at `<workspace>/_libraries/<name>/src/` — the `_generated/`-style build-artifact convention (reproducible from the project's imports + the bundle; never committed). Acquisition backends, in priority order: `pip install --target` (primary), then `mip install --target` / `circup` pointed at the local path — every backend writes the **local tree, never a device or a CIRCUITPY mount**.
- Each fetched library is registered into the same managed `library_sources:` block dev mode uses. Regular mode becomes dev mode pointed at a fetched local tree instead of a sibling checkout — one resolution mechanism, one deploy, for both modes.
- Transitive deps land in the local tree as Decision 0042 describes (recursive); the AST walker + import graph remain the only thing that decides what actually ships, exactly as on the dev-mode path.

## Rejected

- **Keep the board-push as a "regular-mode convenience."** The convenience *is* the additive-orphan disease Decision 0077 exists to stop; a second staging channel is exactly the seam drift regrows in.
- **Fold acquisition into `deploy` (auto-fetch on import-graph miss).** Couples a network fetch into the staging path, weakens the air-gap / `--offline` story, and re-tangles "acquire" with "stage" — the separation this phase is establishing.
- **Acquire into the host venv's site-packages.** Not a `libraries/<name>/src/`-shaped tree the import-graph walk can root on; conflates host-test deps with device payload.
- **Block on functional PyPI/bundle publishing.** The publishing channels (Decision 0018) are non-functional today and tracked separately; this ADR fixes acquisition *shape*, which is independent of whether the artifacts currently resolve.

## Consequences

- The last out-of-band `/lib` writer is gone; Decision 0077's "nothing stages to a device outside the one mechanism" holds with no exceptions on the CLI surface. Phase 5's drift lint (Decision 0074) has no sanctioned bypass to except.
- Dev mode and regular mode converge on `library_sources:` + the one import-graph deploy — the mode difference shrinks to *where the source tree came from* (sibling checkout vs `_libraries/` fetch).
- `_libraries/` joins `_generated/` as a gitignored, tool-managed workspace artifact dir; the workspace-template `.gitignore` and the regular-mode README (workspace-template gap #4b) update to the fetch-then-deploy recipe — `install-libraries` no longer "puts libraries on the board," it makes them locally resolvable.
- Independent of the sibling Collapse A in this phase (`deploy-example` → thin front-end; `Deployer.deploy()` deleted as the single-stage-primitive consequence of Decision 0077). Both are tracked in the deploy-path-unification workstream Phase 3; this ADR records only the acquisition tradeoff.
