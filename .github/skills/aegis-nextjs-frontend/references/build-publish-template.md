# Build & Publish Template Reference

This file contains the `build-publish.sh` template for Aegis-powered Next.js frontends. It differs from the `flask-docker-deployment` pattern in three important ways:

1. **Three build args**, not one. `NEXT_PUBLIC_AEGIS_API_URL` and `NEXT_PUBLIC_SITE_DOMAIN` are baked into the client JavaScript bundle at build time and **cannot** be changed at runtime. They must be passed to `docker build`, not just to the running container.
2. **Up-front validation**. All three values (`CR_PAT`, `NEXT_PUBLIC_AEGIS_API_URL`, `NEXT_PUBLIC_SITE_DOMAIN`) are validated before `docker build` is invoked. A silent fallback to whatever default is in `browserClient.ts` is a nasty failure mode — the image builds successfully but points at the wrong backend.
3. **Two tiers**. The site domain and Aegis API URL rarely change per-developer, so we offer a baked-in variant where they are hardcoded at the top of the script. This requires gitignoring `build-publish.sh`.

Pick **one** tier per project. Do not mix.

---

## Tier 1: Standard (values sourced from environment)

**When to use:**
- CI/CD pipelines
- Teams with multiple developers deploying to different environments
- Any setup where secrets are already managed via environment injection

**Requirements:**
- `CR_PAT`, `NEXT_PUBLIC_AEGIS_API_URL`, and `NEXT_PUBLIC_SITE_DOMAIN` must be exported in the shell before running the script

**File: `build-publish.sh`**

```bash
#!/bin/sh

# VERSION file path
VERSION_FILE="VERSION"

# Parse command line arguments
NO_CACHE=""
if [ "$1" = "--no-cache" ]; then
    NO_CACHE="--no-cache"
    echo "Building with --no-cache flag"
fi

# Validate required build arguments up front — a silent fallback here means
# the image builds but the client bundle points at the wrong backend.
if [ -z "$CR_PAT" ]; then
    echo "Error: CR_PAT is not set. Required for installing private GitHub npm packages."
    exit 1
fi

if [ -z "$NEXT_PUBLIC_AEGIS_API_URL" ]; then
    echo "Error: NEXT_PUBLIC_AEGIS_API_URL is not set. This value is baked into the client bundle at build time."
    exit 1
fi

if [ -z "$NEXT_PUBLIC_SITE_DOMAIN" ]; then
    echo "Error: NEXT_PUBLIC_SITE_DOMAIN is not set. This value is baked into the client bundle at build time."
    exit 1
fi

# Check if VERSION file exists, if not create it with version 1
if [ ! -f "$VERSION_FILE" ]; then
    echo "1" > "$VERSION_FILE"
    echo "Created VERSION file with initial version 1"
fi

# Read current version from file
CURRENT_VERSION=$(cat "$VERSION_FILE" 2>/dev/null)

# Validate that the version is a number
if ! echo "$CURRENT_VERSION" | grep -qE '^[0-9]+$'; then
    echo "Error: Invalid version format in $VERSION_FILE. Expected a number, got: $CURRENT_VERSION"
    exit 1
fi

# Increment version
VERSION=$((CURRENT_VERSION + 1))

echo "Building version $VERSION (incrementing from $CURRENT_VERSION)"

# Build the image with optional --no-cache flag
# NEXT_PUBLIC_* vars are baked into the client bundle at build time and cannot be changed at runtime
docker build $NO_CACHE \
    --build-arg CR_PAT="$CR_PAT" \
    --build-arg NEXT_PUBLIC_AEGIS_API_URL="$NEXT_PUBLIC_AEGIS_API_URL" \
    --build-arg NEXT_PUBLIC_SITE_DOMAIN="$NEXT_PUBLIC_SITE_DOMAIN" \
    --platform linux/amd64 \
    -t {registry_url}:$VERSION .

# Tag the same image as latest
docker tag {registry_url}:$VERSION {registry_url}:latest

# Push both tags
docker push {registry_url}:$VERSION
docker push {registry_url}:latest

# Update the VERSION file with the new version
echo "$VERSION" > "$VERSION_FILE"
echo "Updated $VERSION_FILE to version $VERSION"
```

---

## Tier 2: Baked-in (values hardcoded at top)

**When to use:**
- Developer laptops where the target deployment is stable
- Projects with one canonical production target and re-typing the values every build is annoying

**Critical:** This variant bakes deployment config into the script. **`build-publish.sh` must be added to `.gitignore`** so the site-specific values are not committed. `CR_PAT` is still read from the environment because it is a secret.

**File: `build-publish.sh`**

```bash
#!/bin/sh

# Baked-in deployment configuration for this environment.
# This file is gitignored — safe to hold site-specific values.
NEXT_PUBLIC_AEGIS_API_URL="{aegis_api_url}"
NEXT_PUBLIC_SITE_DOMAIN="{site_domain}"

# VERSION file path
VERSION_FILE="VERSION"

# Parse command line arguments
NO_CACHE=""
if [ "$1" = "--no-cache" ]; then
    NO_CACHE="--no-cache"
    echo "Building with --no-cache flag"
fi

# Check if VERSION file exists, if not create it with version 1
if [ ! -f "$VERSION_FILE" ]; then
    echo "1" > "$VERSION_FILE"
    echo "Created VERSION file with initial version 1"
fi

# Read current version from file
CURRENT_VERSION=$(cat "$VERSION_FILE" 2>/dev/null)

# Validate that the version is a number
if ! echo "$CURRENT_VERSION" | grep -qE '^[0-9]+$'; then
    echo "Error: Invalid version format in $VERSION_FILE. Expected a number, got: $CURRENT_VERSION"
    exit 1
fi

# Increment version
VERSION=$((CURRENT_VERSION + 1))

echo "Building version $VERSION (incrementing from $CURRENT_VERSION)"

# CR_PAT is still required from the environment (secret, not baked in)
if [ -z "$CR_PAT" ]; then
    echo "Error: CR_PAT is not set. Required for installing private GitHub npm packages."
    exit 1
fi

# Build the image with optional --no-cache flag
# NEXT_PUBLIC_* vars are baked into the client bundle at build time and cannot be changed at runtime
docker build $NO_CACHE \
    --build-arg CR_PAT="$CR_PAT" \
    --build-arg NEXT_PUBLIC_AEGIS_API_URL="$NEXT_PUBLIC_AEGIS_API_URL" \
    --build-arg NEXT_PUBLIC_SITE_DOMAIN="$NEXT_PUBLIC_SITE_DOMAIN" \
    --platform linux/amd64 \
    -t {registry_url}:$VERSION .

# Tag the same image as latest
docker tag {registry_url}:$VERSION {registry_url}:latest

# Push both tags
docker push {registry_url}:$VERSION
docker push {registry_url}:latest

# Update the VERSION file with the new version
echo "$VERSION" > "$VERSION_FILE"
echo "Updated $VERSION_FILE to version $VERSION"
```

---

## Placeholder Replacement Guide

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `{registry_url}` | Docker registry image URL (no tag) | `ghcr.io/jmazzahacks/my-app-frontend` |
| `{aegis_api_url}` | Full URL to the Aegis backend API (Tier 2 only) | `https://aegis.reallybadapps.com` |
| `{site_domain}` | The frontend domain, no protocol (Tier 2 only) | `app.example.com` |

---

## Post-Create Checklist

After writing `build-publish.sh`:

1. **Make executable:**
   ```bash
   chmod +x build-publish.sh
   ```

2. **Add `VERSION` to `.gitignore`** (version number is environment-local, not source):
   ```
   VERSION
   ```

3. **If Tier 2 (baked-in), also add `build-publish.sh` to `.gitignore`:**
   ```
   VERSION
   build-publish.sh
   ```
   Keep a `build-publish.sh.example` in the repo so new developers have a starting point.

4. **Create an empty `public/` directory** with a `.gitkeep` file. The Dockerfile has `COPY --from=builder /app/public ./public`, which fails if the directory does not exist. Next.js does not create `public/` by default, so the first build will fail without this:
   ```bash
   mkdir -p public && touch public/.gitkeep
   ```

---

## Why Three Build Args and Not One

The `flask-docker-deployment` version of this script only passes `CR_PAT`. That is sufficient for Flask because Flask reads config from the environment at runtime. Next.js is different:

- **`NEXT_PUBLIC_*` variables are compiled into the JavaScript bundle** that ships to the user's browser. They cannot be read from the container's environment at runtime — the build is already done by the time the container starts.
- If you forget to pass `NEXT_PUBLIC_AEGIS_API_URL` as a build arg, the client bundle will fall back to whatever default is in `browserClient.ts` (typically the development URL). The container will start, the health check will pass, but login will fail because the client is calling the wrong backend.

Up-front validation turns a confusing production bug into a loud build-time error.

---

## Running the Script

```bash
# Tier 1 (standard) — export values first
export CR_PAT=ghp_xxxxx
export NEXT_PUBLIC_AEGIS_API_URL=https://aegis.reallybadapps.com
export NEXT_PUBLIC_SITE_DOMAIN=app.example.com
./build-publish.sh

# Fresh build without cache
./build-publish.sh --no-cache

# Tier 2 (baked-in) — only CR_PAT needs to be exported
export CR_PAT=ghp_xxxxx
./build-publish.sh
```
