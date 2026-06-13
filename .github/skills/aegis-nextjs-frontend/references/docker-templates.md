# Docker Templates Reference

This file contains Docker deployment templates for Aegis-powered Next.js frontends, including a multi-stage Dockerfile, docker-compose example, and a health check API route.

---

## Dockerfile

Three-stage build optimized for production Next.js standalone output. Uses `CR_PAT` build arg to authenticate against private GitHub npm packages.

```dockerfile
# =============================================================
# Stage 1: Dependencies
# Install all npm dependencies, including private GitHub packages.
# =============================================================
FROM node:20-alpine AS deps
WORKDIR /app

# GitHub token for private packages
ARG CR_PAT

# Install git for GitHub dependencies
RUN apk add --no-cache git

# Configure git to use token for GitHub HTTPS URLs
RUN git config --global url."https://${CR_PAT}@github.com/".insteadOf "https://github.com/"

# Copy package files
COPY package.json package-lock.json ./

# Install dependencies
RUN npm ci

# =============================================================
# Stage 2: Builder
# Build the Next.js application with environment variables
# baked into the client-side bundle.
# =============================================================
FROM node:20-alpine AS builder
WORKDIR /app

# Build-time arguments for NEXT_PUBLIC_* env vars (baked into client bundle)
ARG NEXT_PUBLIC_AEGIS_API_URL={aegis_api_url}
ARG NEXT_PUBLIC_SITE_DOMAIN={site_domain}

# Set as environment variables for the build
ENV NEXT_PUBLIC_AEGIS_API_URL=$NEXT_PUBLIC_AEGIS_API_URL
ENV NEXT_PUBLIC_SITE_DOMAIN=$NEXT_PUBLIC_SITE_DOMAIN

# Copy dependencies from deps stage
COPY --from=deps /app/node_modules ./node_modules

# Copy source code
COPY . .

# Build the application
RUN npm run build

# =============================================================
# Stage 3: Runner
# Minimal production image using Next.js standalone output.
# Runs as non-root user for security.
# =============================================================
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV DEBUG_LOCAL=false
# Loki logging vars — set via docker-compose or deployment config
# ENV LOKI_URL=https://loki.example.com
# ENV LOKI_USER=
# ENV LOKI_PASS=
# ENV LOKI_CA_PATH=

# Create non-root user for security
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy built application
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3000/api/health || exit 1

CMD ["node", "server.js"]
```

---

## docker-compose.example.yaml

```yaml
version: '3.8'

services:
  {project-name}-frontend:
    image: {registry_url}:latest
    # Or build locally with custom configuration:
    # build:
    #   context: .
    #   args:
    #     - CR_PAT=${CR_PAT}
    #     - NEXT_PUBLIC_AEGIS_API_URL={aegis_api_url}
    #     - NEXT_PUBLIC_SITE_DOMAIN={site_domain}
    ports:
      - "3000:3000"
    environment:
      # Server-side Aegis config (NOT baked into the client bundle).
      # The /api/frontend/auth/* proxy routes use these to call Aegis on
      # behalf of the browser. AEGIS_TENANT_API_KEY must never be exposed
      # to the browser — keep these unprefixed (no NEXT_PUBLIC_).
      - AEGIS_API_URL=${AEGIS_API_URL}
      - AEGIS_TENANT_API_KEY=${AEGIS_TENANT_API_KEY}
      - AEGIS_SITE_ID=${AEGIS_SITE_ID}
      - DEBUG_LOCAL=false
      - LOKI_URL=${LOKI_URL}
      - LOKI_USER=${LOKI_USER}
      - LOKI_PASS=${LOKI_PASS}
      # - LOKI_CA_PATH=/app/ca.pem
    restart: unless-stopped
```

---

## Reverse Proxy Contract

These containers must run behind a reverse proxy that forwards three headers — without them, the next-intl middleware emits broken absolute redirects (e.g., a 307 from `/` to `https://your-host:3000/en` containing the local listener port instead of the public port):

| Header | Why it matters |
|--------|----------------|
| `X-Forwarded-Proto` | Sets the public scheme on `Location` headers (so they use `https://`, not `http://`). |
| `X-Forwarded-Host`  | Sets the public hostname when the inbound `Host` header is rewritten by the proxy. |
| `X-Forwarded-Port`  | Sets the public port — **without this, Next.js falls back to the local listener port (`3000`).** |

The scaffolded `proxy.ts` ships a defensive fallback that rewrites a malformed redirect's host using the inbound `Host` header (see `i18n-templates.md`). That fallback covers misconfigured proxies that still forward `Host` correctly, plus direct-access development like `docker run -p 3000:3000`. It is **not** a substitute for setting the `X-Forwarded-*` headers — fix the proxy.

### nginx

```nginx
location / {
    proxy_pass http://{project-name}-frontend:3000;

    proxy_set_header Host              $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host  $host;
    proxy_set_header X-Forwarded-Port  $server_port;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;

    # Required for Next.js streaming responses and HMR in dev.
    proxy_http_version 1.1;
    proxy_set_header Upgrade    $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

### Caddy

```caddy
example.com {
    reverse_proxy {project-name}-frontend:3000 {
        # Caddy sets X-Forwarded-Proto / X-Forwarded-Host / X-Forwarded-For
        # automatically. X-Forwarded-Port must be added explicitly.
        header_up X-Forwarded-Port {server_port}
    }
}
```

### Symptom Reference

| 307 `Location` looks like | Likely cause |
|---------------------------|--------------|
| `https://your-host:3000/en` | Missing `X-Forwarded-Port` (Next.js fell back to listener port). |
| `http://your-host/en` (when site is HTTPS) | Missing `X-Forwarded-Proto`. |
| Redirects to a different hostname than the user requested | Missing `X-Forwarded-Host` and inbound `Host` was rewritten. |

---

## Health Check API Route

**File:** `app/api/health/route.ts`

```typescript
import { NextResponse } from 'next/server';

export async function GET(): Promise<NextResponse> {
  return NextResponse.json({
    status: 'healthy',
    service: '{ProjectName} Frontend',
    timestamp: Math.floor(Date.now() / 1000),
  });
}
```

---

## Placeholder Replacement Guide

All placeholders in these templates **must** be replaced before use. The table below lists every placeholder, what it represents, and an example value.

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `{aegis_api_url}` | Full URL to the Aegis backend API | `https://api.example.com` |
| `{site_domain}` | The frontend domain (no protocol) | `app.example.com` |
| `{project-name}` | Kebab-case project name for the docker-compose service | `my-app` |
| `{registry_url}` | Docker registry image URL | `ghcr.io/org/my-app-frontend` |
| `{ProjectName}` | PascalCase project name for the health check response | `MyApp` |

---

## Critical Notes

### Private GitHub Dependencies and CR_PAT

The Dockerfile uses `git config` in Stage 1 to inject the `CR_PAT` (Classic Personal Access Token or fine-grained token) so that `npm ci` can resolve private GitHub packages. This approach works because:

1. The `git config --global url.` rewrite rule transparently converts any `https://github.com/` URL to include the token.
2. `npm ci` uses this git configuration when cloning `git+https://` dependencies.

**Requirements for this to work:**

- The `CR_PAT` token must have `read:packages` scope (for GitHub Packages) or `repo` scope (for private repo dependencies).
- **`package-lock.json` must use `git+https://` URLs, NOT `git+ssh://` URLs.** If your lockfile contains `git+ssh://git@github.com/...` references, Docker builds will fail because there is no SSH key available in the container. To fix this, ensure `package.json` references use HTTPS format:
  ```json
  "dependencies": {
    "@org/private-pkg": "git+https://github.com/org/private-pkg.git#semver:^1.0.0"
  }
  ```
  Then delete `node_modules` and `package-lock.json` and run `npm install` to regenerate the lockfile with HTTPS URLs.

### Next.js Standalone Output

The Dockerfile assumes Next.js is configured with standalone output. Ensure `next.config.ts` (or `next.config.mjs`) includes:

```typescript
const nextConfig = {
  output: 'standalone',
};
```

Without this, the `.next/standalone` directory will not be generated and Stage 3 will fail.

### NEXT_PUBLIC_* Variables Are Baked at Build Time

`NEXT_PUBLIC_*` environment variables are embedded into the JavaScript bundle at build time. They **cannot** be changed at runtime. This is why they are declared as `ARG` values in Stage 2 rather than `ENV` values in Stage 3. If you need to change these values, you must rebuild the Docker image.

### Server-Side Aegis Variables Are Runtime, Not Build-Time

`AEGIS_API_URL`, `AEGIS_TENANT_API_KEY`, and `AEGIS_SITE_ID` are **runtime** env vars. They are read by the `/api/frontend/auth/*` proxy routes on the server side — not baked into the client bundle. Do **not** prefix them with `NEXT_PUBLIC_` (that would publish the tenant key to every browser, defeating the entire gate). Pass them through `docker-compose` `environment:` or your orchestrator's secret-management instead. Changing them does not require a rebuild — just restart the container.

### Build Command

```bash
docker build \
  --build-arg CR_PAT="$CR_PAT" \
  --build-arg NEXT_PUBLIC_AEGIS_API_URL="https://api.example.com" \
  --build-arg NEXT_PUBLIC_SITE_DOMAIN="app.example.com" \
  -t my-app-frontend:latest .
```
