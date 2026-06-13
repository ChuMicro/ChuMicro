---
name: aegis-nextjs-frontend
description: This skill should be used when the user asks to "create a new website", "spin up a frontend", "set up a Next.js site with aegis auth", "scaffold a new web app with authentication", "create a site with login and i18n", or needs a production-ready Next.js frontend integrated with ByteForge Aegis authentication. Provides complete project scaffolding with auth pages, internationalization, Docker deployment, and a design system.
---

# Next.js Frontend with ByteForge Aegis Authentication

This skill scaffolds a complete Next.js 16 frontend with ByteForge Aegis authentication, internationalization (next-intl), Tailwind CSS v4, and Docker deployment. The generated project includes login, email verification, password reset, and protected dashboard pages out of the box.

## When to Use This Skill

- Starting a new web application that needs user authentication
- Creating a frontend for an existing ByteForge Aegis-powered backend
- Spinning up a new site with login, signup, i18n, and Docker support
- Needing a production-ready Next.js template with auth already wired up

## What This Skill Creates

1. **Next.js 16 project** with App Router and `[locale]` dynamic segments
2. **Full auth flow** - Login, email verification, password reset, email change confirmation, welcome page
3. **Protected dashboard** - Auth-gated page with redirect to login
4. **Internationalization** - next-intl with English translations (extensible to any language)
5. **Auth utilities** - Singleton `browserClient` with token refresh, `useAuth` hook with proactive refresh, `AuthCTA` component
6. **Language switcher** - Scalable dropdown component in header
7. **Design system** - CSS variables, light/dark mode, animations, card/button/input components
8. **Docker deployment** - Multi-stage Dockerfile with standalone output
9. **Health check endpoint** - `/api/health` for container orchestration
10. **Loki logging** - Structured server-side logging with Grafana Loki (production) and console fallback (local dev)
11. **Webhook provisioning docs** - Aegis user.verified webhook contract and reference implementation for tenant-side user provisioning

## Step 1: Gather Project Information

**IMPORTANT**: Before creating any files, ask the user these questions:

1. **"What is your project name?"** (e.g., "DevNotes", "TaskFlow", "ReleasePad")
   - Derive:
     - `{ProjectName}` - Display name (e.g., "DevNotes")
     - `{project-name}` - Kebab case for package.json, Docker, URLs (e.g., "devnotes")
     - `{project_name}` - Snake case for internal use (e.g., "dev_notes")

2. **"What is the site domain?"** (e.g., "devnotes.ai", "taskflow.reallybadapps.com")
   - Used for `NEXT_PUBLIC_SITE_DOMAIN`

3. **"What is the Aegis API URL?"** (default: `https://aegis.reallybadapps.com`)
   - Used for `NEXT_PUBLIC_AEGIS_API_URL` (browser bootstrap) and `AEGIS_API_URL` (server-side proxy)

3a. **"What is the tenant API key for this site? (Get it from the Aegis admin dashboard → Site → Settings → Tenant API Key)"**
   - Used for `AEGIS_TENANT_API_KEY` (server-side only). REQUIRED for the gated public auth endpoints. See Step 5b and `references/tenant-api-key-templates.md`.

3b. **"What is the site_id for this site in Aegis?"** (visible in the admin dashboard)
   - Used for `AEGIS_SITE_ID` (server-side, used by proxy routes for verify-email/etc.).

4. **"What is the container registry URL?"** (e.g., `ghcr.io/org/project-frontend`)
   - Used in docker-compose and build scripts

5. **"What is a one-line description of the project?"** (e.g., "AI-powered release notes platform")
   - Used in metadata, home page subtitle, health check

6. **"Does your backend need to provision users when they verify on Aegis? If yes, what backend handles it?"** (e.g., "Yes, Flask backend" / "Yes, Next.js API routes" / "No")
   - Determines whether to include webhook setup instructions in Step 14

## Step 2: Create Directory Structure

```
{project-name}-frontend/
├── app/
│   ├── layout.tsx
│   ├── globals.css
│   ├── [locale]/
│   │   ├── layout.tsx
│   │   ├── page.tsx                    # Home page (customize per project)
│   │   ├── login/page.tsx
│   │   ├── verify-email/page.tsx
│   │   ├── forgot-password/page.tsx
│   │   ├── reset-password/page.tsx
│   │   ├── confirm-email-change/page.tsx
│   │   ├── welcome/page.tsx
│   │   └── dashboard/page.tsx
│   └── api/health/route.ts
├── i18n/
│   ├── routing.ts
│   ├── request.ts
│   └── navigation.ts
├── lib/
│   ├── browserClient.ts
│   ├── logger.ts
│   └── useAuth.ts
├── components/
│   ├── AuthCTA.tsx
│   └── LanguageSwitcher.tsx
├── messages/
│   └── en.json
├── public/
│   └── .gitkeep                        # required so Dockerfile COPY /app/public succeeds
├── proxy.ts                            # next-intl middleware
├── package.json
├── next.config.ts
├── tsconfig.json
├── tailwind.config.ts
├── postcss.config.mjs
├── global.d.ts
├── .env.example
├── .gitignore                          # includes VERSION (and build-publish.sh if Tier 2)
├── Dockerfile
├── docker-compose.example.yaml
└── build-publish.sh                    # chmod +x, see Step 12
```

## Step 3: Create Configuration Files

Generate each configuration file using the templates in `references/config-templates.md`. These files are mostly boilerplate with placeholder substitutions:

- `package.json` - Dependencies including `byteforge-aegis-client-js`, `byteforge-loki-logging-ts`, `next-intl`, Tailwind v4
- `next.config.ts` - next-intl plugin, transpilePackages for aegis client and loki logging, standalone output
- `tsconfig.json` - ES2017 target, strict mode, `@/*` path alias
- `tailwind.config.ts` - Content paths for app/ and components/
- `postcss.config.mjs` - `@tailwindcss/postcss` plugin
- `global.d.ts` - IntlMessages type declaration
- `.env.example` - `NEXT_PUBLIC_AEGIS_API_URL`, `NEXT_PUBLIC_SITE_DOMAIN`, and Loki logging variables

**CRITICAL**: Replace all instances of `{project-name}`, `{ProjectName}`, `{site_domain}`, `{aegis_api_url}`, and `{project_description}` in every file.

## Step 4: Create i18n Infrastructure

Generate files from `references/i18n-templates.md`:

- `i18n/routing.ts` - Locale definitions (start with `['en']`, add more as needed)
- `i18n/request.ts` - Server-side message loading
- `i18n/navigation.ts` - Locale-aware `Link`, `useRouter`, `usePathname`
- `proxy.ts` - next-intl middleware wrapped with a defensive Host-header fallback that fixes redirect URLs when the upstream proxy doesn't forward `X-Forwarded-Host` / `X-Forwarded-Port`. Matches all paths except `/api`, `/_next`, static files. See `docker-templates.md` for the upstream proxy header contract.

These files are identical across projects. No placeholder substitution needed.

## Step 5: Create Auth Utilities

Generate files from `references/auth-templates.md`:

- `lib/browserClient.ts` - Singleton AuthClient that persists tokens in memory and syncs to localStorage. Includes `initAuthClientFromLogin()`, `refreshAuthTokens()`, `isTokenExpired()`, `clearAuthClient()`, and the `browserAuthProxy` shim that posts to the local `/api/frontend/auth/*` proxy routes (used by auth pages for the six tenant-key-gated endpoints).
- `lib/useAuth.ts` - React hook that reads auth state from localStorage, proactively refreshes tokens (5-minute buffer, 60-second check interval), and auto-logs out on refresh failure.

These files are identical across projects except for the default env variable values (`{aegis_api_url}`, `{site_domain}`).

### Step 5b: Tenant API Key Proxy Routes (Required)

After backend image v40+, six public auth endpoints (`register`, `login`, `request-password-reset`, `reset-password`, `verify-email`, `check-verification-token`) require an `X-Tenant-Api-Key` header that **must live server-side**. This means scaffolded apps need backend proxy routes for these flows — the browser cannot call Aegis directly for them.

Generate from `references/tenant-api-key-templates.md`:

- `lib/serverAuthClient.ts` — server-side `AuthClient` factory configured with `AEGIS_TENANT_API_KEY` and `AEGIS_SITE_ID` from env.
- `app/api/frontend/auth/register/route.ts`
- `app/api/frontend/auth/login/route.ts`
- `app/api/frontend/auth/request-password-reset/route.ts`
- `app/api/frontend/auth/reset-password/route.ts`
- `app/api/frontend/auth/verify-email/route.ts`
- `app/api/frontend/auth/check-verification-token/route.ts`
- (The `browserAuthProxy` helper is already inlined in `lib/browserClient.ts` from Step 5 — auth pages call it instead of the singleton `AuthClient` for the gated endpoints.)

**Ask the user:** "Do you have a tenant API key for this site (from the Aegis admin dashboard)?" If yes, set `AEGIS_TENANT_API_KEY` in `.env.local`. If no, direct them to Aegis admin → Site → Settings → Tenant API Key. The site's `id` becomes `AEGIS_SITE_ID`.

**Also ask:** "Does this project already have a separate backend (Flask, Express, FastAPI, etc.) that the frontend talks to?" If **yes**, host the 6 proxy endpoints in that backend instead of in Next.js API routes — see the "Alternative: Proxy Lives in a Sibling Backend" section in `references/tenant-api-key-templates.md`. Reference implementation: `hivemake.ai`. The Next.js side then uses two `AuthClient` singletons (Aegis-direct + backend-proxy) and skips the `/api/frontend/auth/*` routes and `browserAuthProxy` shim entirely. If **no**, use the default pattern below.

The auth pages (Step 6) call `browserAuthProxy.*` for the six gated endpoints; the singleton `AuthClient` from `auth-templates.md` is still used for unprotected calls (`getSiteByDomain`, `me`, `change-password`, `logout`, `refresh`).

## Step 6: Create Auth Pages

Generate all authentication pages from `references/auth-page-templates.md`:

- `app/[locale]/login/page.tsx` - Email/password form, site lookup, token storage
- `app/[locale]/verify-email/page.tsx` - Token validation, optional password setup
- `app/[locale]/forgot-password/page.tsx` - Email input, always shows success (security)
- `app/[locale]/reset-password/page.tsx` - New password form with confirmation
- `app/[locale]/confirm-email-change/page.tsx` - Auto-confirms on load
- `app/[locale]/welcome/page.tsx` - Success page with confetti animation

**CRITICAL**: In each auth page, replace the branded footer text. The pattern uses a split-color brand display:
```tsx
<span className="text-[var(--foreground)]">{BrandPart1}</span>
<span className="text-[var(--amber-glow)]">{BrandPart2}</span>
```
Replace these spans with the new project's brand name.

## Step 7: Create Components and Layouts

Generate from `references/component-templates.md`:

- `components/AuthCTA.tsx` - Smart button: shows "Sign In" or "Go to Dashboard" based on auth state
- `components/LanguageSwitcher.tsx` - Dropdown with globe icon, scales to any number of languages
- `app/layout.tsx` - Root layout with metadata
- `app/[locale]/layout.tsx` - Locale layout with NextIntlClientProvider

## Step 8: Create Dashboard and Home Page

Generate from `references/page-templates.md`:

- `app/[locale]/dashboard/page.tsx` - Protected page with header, logout, language switcher, placeholder content
- `app/[locale]/page.tsx` - **This page is project-specific**. Use the template as a starting point but customize the hero section, feature cards, and description for the actual project.

## Step 9: Create Design System

Generate `app/globals.css` from `references/design-system.md`.

The design system includes:
- CSS custom properties for colors (ink, paper, amber accent, status colors)
- Light and dark mode via `prefers-color-scheme`
- Google Fonts: Libre Baskerville (display) + DM Sans (body)
- Component classes: `.card`, `.input-field`, `.btn-primary`, `.btn-secondary`, `.spinner`
- Status classes: `.status-success`, `.status-error`
- Animation utilities: `fadeInUp`, `fadeIn`, `scaleIn`, delay classes
- Mesh gradient background and paper texture overlay

## Step 10: Create Translation File

Generate `messages/en.json` from `references/i18n-templates.md`.

Contains all translation keys organized by page: Common, Home, Welcome, Login, Verify, ForgotPassword, ResetPassword, ConfirmEmailChange, Dashboard.

**CRITICAL**: Replace `{ProjectName}` and `{project_description}` in the translation values.

## Step 11: Create Docker Files

Generate from `references/docker-templates.md`:

- `Dockerfile` - 3-stage build (deps → builder → runner) with CR_PAT for private GitHub packages. `NEXT_PUBLIC_AEGIS_API_URL` and `NEXT_PUBLIC_SITE_DOMAIN` are baked in as build args (Stage 2 ARG/ENV).
- `docker-compose.example.yaml` - Service definition with image URL, port mapping, and **server-side runtime env vars** (`AEGIS_API_URL`, `AEGIS_TENANT_API_KEY`, `AEGIS_SITE_ID`) consumed by the `/api/frontend/auth/*` proxy routes. These must NOT be `NEXT_PUBLIC_` — the tenant key must never reach the browser.
- `app/api/health/route.ts` - Returns JSON with status, service name, and unix timestamp

## Step 12: Create Build & Publish Script

Generate `build-publish.sh` from `references/build-publish-template.md`. **Ask the user which tier to use** before generating:

- **Tier 1 (Standard)** — values sourced from environment. Best for CI/CD and teams. Committed to the repo.
- **Tier 2 (Baked-in)** — `NEXT_PUBLIC_AEGIS_API_URL` and `NEXT_PUBLIC_SITE_DOMAIN` hardcoded at the top of the script. Best for developer laptops with a single stable deployment target. Must be gitignored.

**Why this step exists:** The `flask-docker-deployment` `build-publish.sh` pattern only passes `CR_PAT` as a build arg. A Next.js frontend also needs `NEXT_PUBLIC_AEGIS_API_URL` and `NEXT_PUBLIC_SITE_DOMAIN` as build args because those values are baked into the client JavaScript bundle at build time. Blindly copying the Flask pattern produces an image that starts successfully but has the wrong backend URL in the client bundle.

Actions:

1. **Generate `build-publish.sh`** from the chosen tier in the template. Replace `{registry_url}` with the container registry URL from Step 1. For Tier 2, also replace `{aegis_api_url}` and `{site_domain}`.

2. **`chmod +x build-publish.sh`**

3. **Create `public/` with a `.gitkeep`:**
   ```bash
   mkdir -p public && touch public/.gitkeep
   ```
   The Dockerfile has `COPY --from=builder /app/public ./public`, which fails if the directory does not exist. Next.js does not create `public/` by default.

4. **Create or update `.gitignore`** to include:
   ```
   VERSION
   ```
   For Tier 2, also add:
   ```
   build-publish.sh
   ```

## Step 13: Configure Loki Logging

Generate `lib/logger.ts` from `references/logging-templates.md`.

This provides a dual-mode logger:
- **Local dev** (`DEBUG_LOCAL=true`) — Formatted console output, no Loki connection needed
- **Production** (`LOKI_URL` set) — Structured JSON logs shipped to Grafana Loki with batching

After creating `lib/logger.ts`, import the `logger` singleton in all API route handlers (`app/api/**/route.ts`). Use `logger.info()` for success paths and `logger.error()` in catch blocks, always including the `route` field in extra for Loki filtering.

**CRITICAL**: Replace `{project-name}` in the logger template (appears in emitter tags and the default singleton).

**CRITICAL**: `byteforge-loki-logging-ts` is server-side only (uses `node:https`). Never import it in `'use client'` files or Edge Runtime routes.

## Step 14: Configure Aegis Webhook (Optional)

If the user indicated their backend needs to provision users on verification (Step 1, question 6), guide them through webhook setup using `references/webhook-templates.md`.

This step is **backend-agnostic** — the webhook handler can live in a Next.js API route, Flask endpoint, Express server, or any other backend that can receive HTTP POST requests.

Key actions:
1. Explain the webhook contract (payload shape, headers, signing algorithm)
2. Add `AEGIS_WEBHOOK_SECRET` to the project's `.env.example`
3. Provide the appropriate reference implementation:
   - **Next.js**: Use the API route skeleton from the templates
   - **Flask**: Reference the NoteForge implementation pattern
   - **Other**: Walk through the signature verification algorithm and provisioning pattern
4. Remind the user to configure `webhook_url` on their Aegis site via the admin API

If the user does **not** need webhook provisioning, skip this step entirely.

## Step 15: Initialize and Verify

```bash
npm install
npm run build
```

Verify all 10 pages generate (3 locales × pages if multiple languages, or just `/en/*` for single language).

## Design Principles

### Authentication Pattern
- **Singleton AuthClient** in `browserClient.ts` persists tokens in memory and syncs to localStorage
- Login page calls `initAuthClientFromLogin()` instead of manual `localStorage.setItem()` calls
- `useAuth` hook proactively refreshes tokens 5 minutes before expiry (checks every 60s)
- Failed refresh (expired refresh token, network error) triggers automatic logout
- `clearAuthClient()` is the single source of truth for clearing all auth state on logout
- All auth state stored in localStorage (`auth_token`, `refresh_token`, `token_expires_at`, `user_id`, `site_id`, `site_name`)
- Site lookup by domain on login page mount
- Protected pages redirect to `/login` when not authenticated

### Internationalization
- URL structure: `/{locale}/page` (e.g., `/en/login`, `/es/login`)
- `localePrefix: 'always'` ensures locale is always in the URL
- All user-facing text goes through translation keys, never hardcoded
- Language switcher preserves current pathname when switching

### Webhook Provisioning
- **Flow**: User signs up on Aegis → verifies email → Aegis fires `user.verified` webhook → tenant backend provisions user (creates DB record, generates API key, etc.)
- **Signing**: HMAC-SHA256 over `"{timestamp}.{body}"` with shared secret — tenant verifies before processing
- **Idempotent 3-branch pattern**: (1) Aegis ID already exists → no-op, (2) email exists but no Aegis ID → link it, (3) new user → create record
- **Backend-agnostic**: The webhook handler can be any HTTP endpoint — Next.js API route, Flask blueprint, Express middleware, etc.
- **Optional**: Not all projects need webhook provisioning. Only include when the tenant site has its own user records to create.

### Security
- Forgot password always shows success (never reveals if email exists)
- Tokens stored in localStorage with explicit cleanup on logout
- Webhook signatures verified with constant-time comparison and replay protection (300s tolerance)
- Non-root user in Docker container
- Health check endpoint for orchestration

## Integration with Other Skills

### Docker Deployment
The `build-publish.sh` script generated in Step 12 is **specific to this skill** — do not substitute the `flask-docker-deployment` version. Next.js frontends require `NEXT_PUBLIC_AEGIS_API_URL` and `NEXT_PUBLIC_SITE_DOMAIN` as build args (they are baked into the client JavaScript bundle at build time), and the frontend template validates all three build args up front to avoid silent misconfiguration. See `references/build-publish-template.md` for the full template and rationale.

### Database
If the project needs a database, use **postgres-setup** skill.

### Loki Logging (Flask backends)
If the project also has a Flask backend on the same Loki infrastructure, use **byteforge-loki-logging** skill for the Python side. Both skills push to the same Grafana Loki instance and can be queried together using the `application` label.

### Backend Aegis Identity Resolution
When the frontend talks to a custom backend (Next.js API routes, sibling Flask service, etc.), the backend has two ways to resolve Aegis identities to user records — pick whichever fits the calling pattern:

- **`GET /api/auth/me`** — bearer-token introspection. Use when you receive an `Authorization: Bearer <aegis_token>` from a frontend caller and need to know which user it represents. Available as of Aegis image v39 / TS client `2.8.0` / Python client `1.2.0`.
- **`GET /api/sites/{site_id}/users/{user_id}`** — tenant-key-gated user lookup by id. Use when an inbound non-Aegis credential (internal API key, stored service identity, cron job) maps to an Aegis `user_id` but no bearer is present, and you need the current `role` for authorization. Available with the post-tenant-key-gate Aegis backend / TS client `2.11.0` / Python client `1.6.0`.

Both return the same standard user shape including `role`. Neither should be called from the frontend itself — login already returns the user, and these endpoints are for backend authz checks.

See `references/backend-auth-templates.md` for drop-in middleware:
- `/me`: Next.js helper `lib/aegisAuth.ts` and Flask decorator `@aegis_auth_required` with short-TTL token caching.
- User-lookup: Next.js helper `lib/aegisUserLookup.ts` (uses TS client `2.11.0`+ typed `client.getUser`) and a Flask `admin_required` decorator example using Python client `1.6.0`+ typed `client.get_user(user_id)`.

## Additional Resources

### Reference Files

All template code is organized in reference files for progressive loading:

- **`references/config-templates.md`** - package.json, next.config.ts, tsconfig.json, tailwind, postcss, .env
- **`references/i18n-templates.md`** - Routing, request config, navigation, translations (en.json)
- **`references/auth-templates.md`** - browserClient.ts, useAuth.ts
- **`references/tenant-api-key-templates.md`** - 6 backend proxy routes for gated public auth endpoints, server-side AuthClient helper, browserAuthProxy
- **`references/auth-page-templates.md`** - All 6 authentication pages
- **`references/component-templates.md`** - AuthCTA, LanguageSwitcher, layouts
- **`references/page-templates.md`** - Dashboard, home page
- **`references/design-system.md`** - globals.css with full design system
- **`references/logging-templates.md`** - lib/logger.ts with Loki and console dual-mode logging
- **`references/docker-templates.md`** - Dockerfile, docker-compose, health endpoint
- **`references/build-publish-template.md`** - build-publish.sh script (two tiers: env-sourced and baked-in) with auto-versioning, three-build-arg validation, and public/ directory gotcha
- **`references/webhook-templates.md`** - Aegis user.verified webhook contract, signature verification, and provisioning pattern
- **`references/backend-auth-templates.md`** - Backend Aegis identity resolution: `/api/auth/me` bearer introspection (Next.js helper, Flask decorator) plus `GET /api/sites/{site_id}/users/{user_id}` user-lookup-by-id for non-bearer authz (Next.js fetch helper, Flask `admin_required` example using the typed Python `client.get_user`)
