---
name: uv-supply-chain-hardening
description: Harden a Python project's dependency supply chain by switching Docker builds from pip to uv, pinning every dependency to the currently-installed version with hashes, and adding a release-age gate so freshly-uploaded (possibly compromised) packages can't be pulled in. Use when locking down dependencies, defending against supply-chain attacks, or migrating a Dockerized Python build from pip to uv.
---

# uv Supply-Chain Hardening

This skill converts a Python project from a loose `pip install -r requirements.txt`
build into a **locked, hash-verified, release-age-gated** build using
[uv](https://github.com/astral-sh/uv). It is the response to the wave of
supply-chain attacks targeting Python (and especially crypto) projects, where a
maintainer account is compromised and a malicious version is published to PyPI.

The defense has three layers:

1. **Pin every dependency** to an exact version — no floating ranges, so a build
   can't silently pull a newer (compromised) release.
2. **Verify hashes** — every PyPI distribution is checked against a SHA256 in the
   lockfile, so a tampered-with artifact on the registry is rejected.
3. **Release-age gate** — refuse any distribution published in the last N days, so
   a freshly-uploaded malicious version isn't pulled in before the community has a
   chance to catch and yank it.

## When to Use This Skill

- You have a Python project (with `requirements.txt` and/or `pyproject.toml`) whose
  Docker build runs `pip install` against unpinned or loosely-pinned dependencies.
- You want reproducible, tamper-evident builds.
- You're worried about a dependency (or one of its transitive deps) being hijacked.
- You have private Git dependencies and need them to coexist with hash-locking.

## What This Skill Changes

1. **`requirements.in`** (NEW) — human-edited source-of-truth list of direct deps.
2. **`requirements.txt`** (REWRITTEN) — machine-generated, fully-pinned, hashed lock.
3. **`pyproject.toml`** — adds `[tool.uv] exclude-newer` and pins the build backend
   (or a root **`uv.toml`** if the repo has no `pyproject.toml`).
4. **`Dockerfile`** — installs via a digest-pinned `uv` instead of `pip`; private-dep
   token stays a build-time `ARG`/secret (never baked into the image).
5. **`requirements-private.txt`** (NEW, *optional*) — first-party libs installed at
   HEAD when the user wants their own libraries to always track latest (Step 5b).

Nothing about the application code changes — this is purely the dependency pipeline.

---

## Step 0: Establish the Baseline

**IMPORTANT — pin to what is _installed_, not to "latest".** The whole point is
reproducing the environment you've actually been running and testing against. If
you just run `uv pip compile` with no constraints, it resolves to the newest
versions allowed, which can jump you across several releases you never tested
(and, worse, is exactly the surface a supply-chain attack rides in on).

First, confirm uv is available and capture the currently-installed versions:

```bash
# Inside the project's activated virtualenv
uv --version || pip install uv            # or: brew install uv / pipx install uv
pip freeze > /tmp/installed-constraints.txt
```

`/tmp/installed-constraints.txt` is the constraint set that anchors the compile to
exactly what you have installed today.

**Ask the user:**

1. **"How many days should the release-age gate be?"**
   - Default: **7 days**. Long enough that most malicious releases get caught and
     yanked; short enough you still get timely security patches.

2. **"Do you have private Git dependencies?"** (yes/no)
   - If yes, note the token env var name (commonly `CR_PAT` for a GitHub PAT).

3. **"Before we freeze, are there any of your own libraries you want to update
   first?"**
   - Pinning captures a moment in time. If the user maintains internal libs with
     pending fixes, pull those in and re-`pip install` _before_ freezing, so the
     lock captures the intended versions.

4. **"Should your own private libraries be pinned, or always track latest?"**
   - A common, legitimate stance: pin the **third-party** attack surface, but let
     your **first-party** libs (the ones requiring a token) float to the latest
     commit on every build — you review your own code and want fixes without a
     manual SHA bump. If they choose this, those libs do **not** get pinned in the
     lock; they go in a separate `requirements-private.txt` installed at HEAD. See
     **Step 5b** — it changes Steps 1, 2, and 4.

5. **"What Python version does the *container* run?"**
   - You must compile the lock for the container's Python (`--python-version`), not
     your laptop's. A local 3.14 venv resolving for a 3.13 image picks different
     wheels/markers. Read it off the `FROM python:X.Y` line.

---

## Step 1: Create `requirements.in` (source of truth)

`requirements.in` lists only your **direct** dependencies — the things you actually
import — with no version pins (the lock supplies those). This is the file a human
edits; `requirements.txt` is never hand-edited again.

```
# requirements.in — direct dependencies only. Edit this, then recompile
# requirements.txt with:
#   uv pip compile requirements.in --generate-hashes -o requirements.txt
#
# Pins and hashes for the full transitive tree live in requirements.txt.

example-http-client
example-db-driver
some-public-lib

# Private Git dependency — pinned to an immutable commit SHA, not a branch.
# The commit SHA is the integrity anchor (a branch can be force-pushed; a SHA
# can't). ${TOKEN_ENV} is expanded from the build environment at install time;
# never commit a literal token here.
internal-lib @ git+https://${CR_PAT}@github.com/your-org/internal-lib.git@<commit-sha>
```

**CRITICAL replacements:**
- Direct dependency names → the user's actual top-level imports (mine these from the
  existing `pyproject.toml` `dependencies` and/or the un-hashed `requirements.txt`).
- `internal-lib @ git+...@<commit-sha>` → each private dep, **pinned by full commit
  SHA**. If it's currently pinned to a branch or unpinned, resolve the current commit
  (`git ls-remote https://github.com/your-org/internal-lib.git <branch>`) and pin it.
- `${CR_PAT}` → the user's token env var name.

> **Why a commit SHA for Git deps:** Git distributions cannot carry a PyPI-style
> hash in the lock (see Step 5). The commit SHA _is_ the hash — it's the only thing
> anchoring the integrity of a Git dependency, so it is non-negotiable for these.

> **⚠️ Token-baking via a library's OWN `pyproject.toml` (the subtle leak — check
> this every time).** Distinct from the Dockerfile `ENV` leak in Step 4/6. If one of
> your private libraries declares its *own* dependencies as
> `git+https://{env:CR_PAT}@github.com/...` (the hatch `{env:...}` context form),
> **hatchling expands the token at build time into the wheel's `Requires-Dist`
> metadata** — so a live PAT gets frozen into every image built from that lib, even
> with a flawless Dockerfile. `${VAR}` in a *requirements* file is fine (that file is
> never packaged); `{env:VAR}` inside a *package's* `[project.dependencies]` is not.
> **Fix the library:** declare its deps with token-free URLs
> (`git+https://github.com/...`) and let git `insteadOf` supply auth at install —
> this stays compatible with unpinned/always-latest deps. Then **rotate the PAT**,
> since older built images still carry it. Scan for it in Step 6.

---

## Step 2: Compile the Locked, Hashed `requirements.txt`

Compile from `requirements.in`, constrained to the installed versions, with hashes:

```bash
# A raw `pip freeze` includes VCS/editable lines (`pkg @ git+...`, `-e ...`,
# `pkg @ file://...`) that uv rejects as constraints — keep only `name==version`:
grep -E '^[A-Za-z0-9._-]+==[0-9]' /tmp/installed-constraints.txt > /tmp/constraints.txt

uv pip compile requirements.in \
  --generate-hashes \
  --python-version 3.13 \
  -c /tmp/constraints.txt \
  -o requirements.txt
```

- `--generate-hashes` → writes a SHA256 (often several, one per wheel/sdist) for
  every PyPI distribution. This is what makes registry tampering detectable.
- `--python-version <X.Y>` → **resolve for the Python the container runs, not your
  laptop's.** Compiling under a different interpreter (local 3.14, image 3.13) can
  select different wheels/markers. Match the `FROM python:X.Y` in the Dockerfile.
- `-c /tmp/constraints.txt` → **pins to the versions you already have installed**
  rather than resolving to latest. This is the step people forget; without it the
  lock can leap forward across untested releases.
- The output is the full transitive tree, every package pinned to `==` with hashes.

**Verify the pin matched the baseline.** Diff the new pins against what you had:

```bash
# Sanity check: the compiled versions should match installed ones (modulo
# package-name normalization like Flask -> flask, PyYAML -> pyyaml).
diff <(grep -oE '^[a-zA-Z0-9_.-]+==[0-9][^ ]*' requirements.txt | sort) \
     <(sort /tmp/installed-constraints.txt)
```

Expected differences are only name-case/separator normalization. If a version
actually _moved_, investigate before accepting it — that's the exact thing this
process exists to make visible.

> **uv preserves existing pins on recompile.** Once `requirements.txt` exists, a
> later `uv pip compile` keeps the current pins unless you pass `--upgrade` (or
> `--upgrade-package NAME`). So routine recompiles (e.g. after adding one new dep to
> `requirements.in`) won't silently bump everything else — only deliberate upgrades
> do. Document this in the file header so the next editor knows the lock is sticky.

---

## Step 3: Add the Release-Age Gate + Pin the Build Backend (`pyproject.toml`)

Two additions to `pyproject.toml`.

**(a) The release-age gate** under `[tool.uv]`:

```toml
[tool.uv]
# Supply-chain defense: refuse any distribution published in the last 7 days when
# resolving/locking, so a freshly-uploaded (possibly compromised) version can't be
# pulled in before the community catches and yanks it. Applies to BOTH
# `uv pip compile` and `uv pip install`. This is a rolling window evaluated at
# run time — not a fixed date — so it keeps protecting future installs.
exclude-newer = "7 days"
```

- `exclude-newer` accepts a friendly duration (`"7 days"`) or an ISO-8601 timestamp.
  Prefer the duration: it's a **rolling** gate that keeps working on every future
  build, whereas a fixed timestamp goes stale.
- Replace `7 days` with the answer from Step 0.

> **No `pyproject.toml`? (a Flask/service repo, not a package.)** Put the setting in
> a **`uv.toml`** at the repo root instead — uv reads it for both compile and
> install. In `uv.toml` the keys are top-level (no `[tool.uv]` table):
> ```toml
> # uv.toml
> exclude-newer = "7 days"
> ```
> And **skip part (b)** below — a repo that never builds a wheel has no build backend
> to pin.

**(b) Pin the build backend** under `[build-system]` — otherwise the backend itself
(e.g. hatchling/setuptools) is an unpinned dependency resolved at wheel-build time,
and is just as hijackable as any other:

```toml
[build-system]
# Pinned (not floating) so the build backend can't be swapped for a newer,
# potentially compromised release at build time. exclude-newer keeps it >=7 days
# old; bump deliberately when upgrading.
requires = ["hatchling==1.29.0"]
build-backend = "hatchling.build"
```

**CRITICAL:** use the backend the project already uses, pinned to its installed
version (`pip show hatchling` / `pip show setuptools`). Don't switch backends.

---

## Step 4: Convert the Dockerfile from pip to uv

Replace the `pip install` flow with a `uv` install. Three things matter here, each
of which closes a real hole.

```dockerfile
FROM python:3.13-alpine

# 1) Bring in the uv binary, PINNED BY IMMUTABLE DIGEST — not just the version tag.
# A version tag can be re-pushed to point at a different (malicious) binary; the
# @sha256 digest cannot. This binary installs everything else, so it must be the
# most trusted thing in the build. To upgrade uv, bump BOTH the tag and the digest.
COPY --from=ghcr.io/astral-sh/uv:0.9.28@sha256:<digest> /uv /uvx /bin/

# 2) Private-dep token as a BUILD ARG ONLY. It is available to the RUN steps below
# for cloning private Git deps, but is deliberately NOT promoted to ENV — promoting
# it bakes a live credential into the final image's environment (visible via
# `docker inspect`). ARG alone is enough for ${CR_PAT} expansion in RUN steps.
ARG CR_PAT

RUN apk add --no-cache git gcc musl-dev postgresql-dev   # build deps as needed

WORKDIR /app
COPY requirements.txt pyproject.toml README.md ./
COPY src/ ./src/                                          # your package sources

# 3) Install the locked, hash-verified dependencies. uv verifies every hash present
# in requirements.txt; ${CR_PAT} is expanded from the build ARG for private Git deps.
RUN uv pip install --system -r /app/requirements.txt

# Install the application package itself for its entry points. --no-deps because
# every dependency is already pinned and installed from the lock above.
RUN uv pip install --system --no-deps .

# ... non-root user, ENV, EXPOSE, ENTRYPOINT as before ...
```

**CRITICAL points:**

- **`--system`** installs into the image's Python (there's no venv inside the
  container), matching how `pip install` behaved before.
- **Get the current uv digest** so you can fill in `<digest>`:
  ```bash
  docker pull ghcr.io/astral-sh/uv:0.9.28
  docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/astral-sh/uv:0.9.28
  ```
  Pin the version tag to whatever uv version you standardized on, then pin its digest.
- **Remove any `ENV CR_PAT=${CR_PAT}` line** if one existed. This is the single most
  important fix: the `ENV` form leaks the token into the published image. See the
  verification step below.
- If the project has **no private deps**, drop the `ARG CR_PAT` line and `git` from
  the apk install.
- **Prefer a BuildKit secret over `ARG` when the build supports it.** `ARG CR_PAT`
  passed via `--build-arg` is recorded in `docker history` and can surface in build
  logs; a secret mount never touches a layer at all:
  ```dockerfile
  RUN --mount=type=secret,id=cr_pat \
      export CR_PAT=$(cat /run/secrets/cr_pat) \
      && git config --global url."https://${CR_PAT}@github.com/".insteadOf "https://github.com/" \
      && uv pip install --system -r requirements.txt \
      && git config --global --unset url."https://${CR_PAT}@github.com/".insteadOf
  ```
  Build with `docker build --secret id=cr_pat,env=CR_PAT ...`. The `insteadOf`
  rewrite means your requirements/lock can use **token-free** `https://github.com/`
  URLs — no credential in any committed file. If an existing `build-publish.sh`
  already passes `--secret`, keep that interface (don't regress it to `ARG`).

---

## Step 5: The `--require-hashes` / Git-dependency Tradeoff

You may consider adding `--require-hashes` to the install for maximum strictness. Be
aware of the catch and decide consciously:

- **PyPI deps** all carry hashes in the lock, so they're verified regardless.
- **Git dependencies cannot be hashed** — there's no immutable artifact hash for a
  `git+https://...` source, only the commit SHA (which you already pinned in Step 1).
- `--require-hashes` is **all-or-nothing**: it rejects the _entire_ requirements file
  if any single line lacks a hash. So you can't use it unless you split the install
  into two steps — hashed PyPI deps in one file, unhashable Git deps in another.

**Recommendation:** unless the user wants the split, **omit `--require-hashes`**. uv
still verifies every hash that _is_ present (all the PyPI deps), so registry tampering
is already caught; `--require-hashes` would only additionally block a _future
unhashed line_ from sneaking in. Note this as an accepted tradeoff rather than
silently skipping it.

If the user does want it, split:
```dockerfile
RUN uv pip install --system --require-hashes -r /app/requirements-pypi.txt
RUN uv pip install --system -r /app/requirements-git.txt
```

---

## Step 5b: First-Party Libraries That Should Track Latest (the `--override` split)

Use this **only if the user chose "always track latest" for their own libs** in
Step 0. The default model pins everything; this variant pins the **third-party**
attack surface but lets **first-party** libs float to the latest commit on every
build.

**Why a plain compile won't do it — two uv behaviors collide:**

1. **uv resolves the *entire* graph; pip deduped by name.** pip tolerated your
   private libs declaring each other with `{env:CR_PAT}`/unpinned URLs because the
   top-level requirement already "satisfied" them. uv actually fetches each
   transitive git URL from a library's metadata — and if it uses `{env:CR_PAT}` (uv
   can't expand it) or floats to `HEAD` (conflicting with a top-level pin), the
   compile fails with an auth or URL-conflict error.
2. uv pins a git dep to its **resolved HEAD commit** in the output even when the
   input had no SHA — so a single lock would freeze your first-party libs to
   compile-time HEAD, defeating "always latest."

**The split that solves both:**

`requirements-private.txt` — first-party libs, **token-free and unpinned**. Used
twice: as the `--override` for the compile *and* as the install list in Docker.
```
internal-core @ git+https://github.com/your-org/internal-core.git
internal-models @ git+https://github.com/your-org/internal-models.git
```

`requirements.in` — third-party direct deps **plus** the private libs (token-free),
so the compile discovers and locks their third-party sub-tree. The private lines are
stripped from the output afterward.

Compile (token injected only into git's process config, never a committed file):
```bash
export GIT_CONFIG_COUNT=1 \
  GIT_CONFIG_KEY_0="url.https://${CR_PAT}@github.com/.insteadOf" \
  GIT_CONFIG_VALUE_0="https://github.com/"
uv pip compile requirements.in \
  --override requirements-private.txt \
  --generate-hashes --python-version 3.13 \
  -c /tmp/constraints.txt \
  -o requirements.full.txt
# Strip the first-party git lines → requirements.txt holds only the locked, hashed
# third-party tree (their PyPI sub-deps stay; the private libs themselves do not).
grep -vE '^(internal-core|internal-models) @ git\+' requirements.full.txt > requirements.txt
rm requirements.full.txt
```
- `--override requirements-private.txt` forces uv to resolve those packages from
  your token-free URLs instead of the `{env:CR_PAT}@HEAD` ones in their metadata.
- Note any **transitive public git deps** that remain in the lock (e.g. a logging
  lib pulled from GitHub) — they're unhashable, which is why `--require-hashes`
  needs the Step 5 split. Leave them in `requirements.txt` so the `--no-deps`
  install below can satisfy them.

Dockerfile — two installs:
```dockerfile
RUN uv pip install --system -r requirements.txt                                # pinned + hashed third-party
RUN uv pip install --system --no-config --no-deps -r requirements-private.txt  # first-party at HEAD
```
- `--no-deps` because every sub-dep is already installed + locked by step 1.
- `--no-config` so `exclude-newer` (uv.toml) can't reject a first-party commit
  pushed within the gate window — you *want* the newest first-party commit. Without
  it, a lib commit younger than the gate fails the build.

**⚠️ The cache trap (bites every rebuild).** A `RUN uv pip install ... requirements-private.txt`
layer is cached on the command string + the file's contents — neither changes when
the upstream branch moves, so Docker **silently reuses the old commit** and "always
latest" quietly becomes "whatever was latest the first time." To actually pull the
newest first-party code you must `docker build --no-cache` (or bust the cache above
that layer, e.g. an `ARG GIT_REV` passed each build). This is also why, right after
merging a fix to a first-party lib, the next publish must be `--no-cache`.

---

## Step 6: Verify the Build — and That the Token Did Not Leak

Do a clean, no-cache build to prove the locked install works end to end:

```bash
# Load the token into the build environment (private deps only)
export CR_PAT=...        # or: set -a; source .env; set +a

./build-publish.sh --no-cache      # or: docker build --no-cache --build-arg CR_PAT=$CR_PAT -t app:test .
```

Then **prove the token is not baked into the image** — this is the regression that
the `ARG`-not-`ENV` change prevents, and it's worth confirming every time:

```bash
# Should print NOTHING. If it prints CR_PAT=..., the token leaked into the image.
docker inspect app:test --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -i CR_PAT

# Belt-and-suspenders: scan the whole image filesystem history for the token value.
docker history --no-trunc app:test | grep -i cr_pat || echo "clean"

# CRITICAL: scan installed package METADATA for a baked token. This catches the
# {env:CR_PAT} library-metadata leak (Step 1 callout) that the ENV and history
# checks above completely miss — the token lives in a .dist-info/METADATA file,
# not the image config. Should print nothing.
docker run --rm --entrypoint sh app:test -c \
  'grep -rl "ghp_\|github_pat_" /usr/local/lib/python*/site-packages/*.dist-info/METADATA 2>/dev/null' \
  || echo "no token in metadata"
```

> **Verify the *published* image, not just the local build.** After
> `build-publish.sh` pushes, `docker rmi` the tag, `docker pull` it fresh, and
> re-run the scans above against the pulled image. A warm build/layer cache can mask
> a stale or token-bearing layer that only the registry copy reveals.

> **If a token was ever exposed** (printed to a terminal, or baked into a previously
> published image via the old `ENV` line), fixing the Dockerfile only stops _future_
> images from carrying it. Images already pushed still contain it, and a leaked token
> stays valid until rotated. Flag this to the user and recommend rotating the token;
> let them decide.

---

## Gotchas Worth Remembering

These are the non-obvious things that cost time the first time through:

1. **Compile without constraints jumps to latest.** Always pass
   `-c <pip-freeze-output>` on the first compile, or you'll lock to versions you
   never tested. (Step 2.)
2. **uv keeps existing pins on recompile.** Adding one dep to `requirements.in` and
   recompiling won't bump the rest — only `--upgrade` does. This is a feature; rely
   on it. (Step 2.)
3. **`exclude-newer` is rolling and applies to install too**, not just compile. A
   `uv pip install` inside Docker is also gated, so a base-image rebuild won't pull a
   day-old package either. (Step 3.)
4. **The build backend is a dependency too.** Pinning app deps but leaving
   `requires = ["hatchling"]` floating leaves a hole at wheel-build time. (Step 3.)
5. **`ARG` is enough; `ENV` leaks.** `${CR_PAT}` expands in `RUN` from an `ARG`
   alone. The `ENV` form additionally persists the value into the image. (Step 4/6.)
6. **Git deps are unhashable** — the commit SHA is their integrity anchor, which is
   why Step 1 insists on pinning them by SHA, and why `--require-hashes` needs a
   split. (Step 1/5.)
7. **Pin the uv binary by digest, not just tag** — it's the root of trust for the
   whole install. (Step 4.)
8. **`{env:CR_PAT}` in a library's own pyproject bakes the PAT into its wheel
   metadata.** hatchling expands it at build time into `Requires-Dist`, so the token
   ships in every image — invisible to env/history checks. Scan
   `*.dist-info/METADATA`, fix the lib to token-free URLs, rotate the PAT. (Step
   1/6.)
9. **uv resolves the whole graph; pip dedups by name.** A private lib that declares
   its own `{env:CR_PAT}`/unpinned deps will fail or conflict the compile. Use
   `--override` to force those packages to your chosen source. (Step 5b.)
10. **uv pins git deps to a resolved commit even from a no-SHA input.** A single lock
    therefore freezes first-party libs to compile-time HEAD — split them out and
    install `--no-deps` at HEAD if you want always-latest. (Step 5b.)
11. **Docker caches HEAD git installs.** The `requirements-private.txt` install layer
    reuses the old commit until you `--no-cache` (or cache-bust). "Always latest"
    silently rots otherwise — and a just-merged lib fix won't ship without it. (Step
    5b.)
12. **Compile for the container's Python, not your laptop's.** `--python-version X.Y`
    matching `FROM python:X.Y`, or you lock the wrong wheels/markers. (Step 0/2.)
13. **A raw `pip freeze` breaks `-c`.** Strip VCS/editable/`file://` lines (keep only
    `name==version`) before using it as a constraints file. (Step 2.)
14. **`exclude-newer` gates installs too — including first-party HEAD.** A first-party
    commit younger than the gate fails the build; run that install with `--no-config`.
    (Step 5b.)

---

## Design Principles

1. **Reproduce what you tested** — pin to installed versions, not to latest.
2. **Make tampering detectable** — hashes on every PyPI artifact.
3. **Buy time against fresh malware** — a rolling release-age gate.
4. **Pin the whole chain** — app deps, the build backend, the uv binary, and (via
   commit SHA) Git deps. A single floating link defeats the rest.
5. **Keep credentials out of artifacts** — build-time `ARG`, never image `ENV`;
   verify with `docker inspect`.
6. **Decide tradeoffs out loud** — e.g. skipping `--require-hashes` is fine, but say
   so and say why, rather than leaving it silently unaddressed.

## Composes With

- **flask-docker-deployment** / **mcp-docker-deployment** — run this _after_ the
  Docker build exists to harden its dependency install (replaces the pip flow).
- **python-lib-setup** — when your internal libraries are the Git deps being pinned
  by commit SHA here.
