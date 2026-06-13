---
name: gatekeeper-nginx-setup
description: Use this skill when the user asks to set up nginx in front of a ByteForge Gatekeeper deployment, configure the gatekeeper vhost, fix Cloudflare Error 1000 / `:3000` redirect leaks for a Gatekeeper site, or wire `auth_request` CORS for a service protected by Gatekeeper's `/authz`. Generates a drop-in nginx vhost (HTTP→HTTPS, `/api/*` → Flask backend, `/` → Next.js frontend) with the four traps documented inline so they don't get "simplified" away, plus optional `/authz` + `/health` + `/metrics` and an optional CORS-via-auth_request configuration for protected upstream services.
---

# Gatekeeper nginx vhost setup

This skill produces a complete nginx vhost for a ByteForge Gatekeeper deployment running behind Cloudflare:

- Flask backend container (gunicorn on port 7843)
- Next.js console frontend container (port 3000)
- Cloudflare Origin certificate already installed on the host

It also covers the optional bits that come up in real deployments — root-level `/authz`/`/health`/`/metrics` exposure, and CORS wiring when **another** vhost on this host (or another host) protects its upstream with `auth_request` against Gatekeeper's `/authz`.

The vhost shape, header set, and resolver trick are not arbitrary. Each load-bearing decision is documented in **Traps** below — read that section before editing anything the skill emits.

## When to Use This Skill

- Bringing up a new Cloudflare-fronted Gatekeeper deployment on a fresh host
- Migrating a Gatekeeper deployment to a new domain
- Debugging `307 → https://<DOMAIN>:3000/<locale>` redirect leaks (the i18n trap)
- Debugging Cloudflare Error 1000 (`DNS points to prohibited IP`) on `/api/*` calls (the catch-all trap)
- Adding `auth_request` CORS to a protected upstream service that delegates authz to a Gatekeeper instance
- Auditing an existing Gatekeeper vhost against the documented traps

## What This Skill Creates

1. **An nginx server block** — HTTP→HTTPS redirect, TLS 443 listener with Cloudflare Origin cert, `/api/*` proxy to backend, `/` proxy to frontend with the i18n-safe forwarded headers
2. **A `resolver` check + directive snippet** — needed because the vhost uses `set $var <container>; proxy_pass http://$var:port;` to defer DNS to request time
3. **(Optional) Root-level endpoints** — `/authz`, `/health`, `/metrics` if external systems need them through this vhost
4. **(Optional) `auth_request` + CORS configuration** — for a separate vhost that delegates authz to this Gatekeeper deployment
5. **Smoke-test commands** — four `curl`s that prove every code path works
6. **A failure-decoder table** — symptom → likely cause → fix, mapped to the trap numbers

## Step 1: Gather Information

Ask the user these questions before generating any config. Substitute the answers consistently throughout.

1. **"What is the public domain for this Gatekeeper deployment?"** (e.g., `gatekeeper.example.com`)
   - Stored as `<DOMAIN>`

2. **"What is the Docker service name of the Flask/gunicorn backend container?"** (e.g., `gatekeeper-backend`)
   - Stored as `<BACKEND_CONTAINER>`
   - Must be reachable by hostname on the docker network nginx is attached to

3. **"What is the Docker service name of the Next.js frontend container?"** (e.g., `gatekeeper-frontend`)
   - Stored as `<FRONTEND_CONTAINER>`
   - Must be reachable by hostname on the docker network nginx is attached to

4. **"Where do the Cloudflare Origin certificate files live for this host?"** (default: `/etc/nginx/ssl/<DOMAIN>.crt` and `.key`)
   - Adjust to the host's nginx convention if different

5. **"Is nginx running on the host directly, or as a container on the same docker network as the Gatekeeper containers?"**
   - Determines which `resolver` IP to use:
     - **Container nginx on a docker user network** → `127.0.0.11` (docker's embedded resolver)
     - **Host nginx using systemd-resolved** → `127.0.0.53`
     - **Host nginx using upstream DNS** → whatever the host actually uses

6. **"Do any external systems (load balancers, monitoring, sibling vhosts) need to reach `/authz`, `/health`, or `/metrics` on this domain?"**
   - If **no**, skip Step 4
   - If **yes**, ask which paths and why — `/authz` in particular often wants `internal;`

7. **"Are there any other services on this host (or another host) that delegate authorization to this Gatekeeper instance via `auth_request /authz`?"**
   - If **yes**, walk Step 5 (CORS via auth_request)
   - If **no** or unsure, skip Step 5

## Step 2: Verify a `resolver` directive exists

The vhost emitted in Step 3 uses `set $var <container>; proxy_pass http://$var:port;` deliberately, so nginx defers DNS resolution to **request time** instead of config-load time. That makes the vhost survive container restarts — but it requires a `resolver` directive somewhere included into the http block.

Run this on the host where nginx config lives:

```bash
grep -r "^[[:space:]]*resolver " /etc/nginx/ 2>/dev/null
```

(Adjust the path if nginx config lives in a docker volume or a non-standard location.)

- **A `resolver` line is present** → done, proceed to Step 3.
- **No `resolver` line** → add this once at the top of `nginx.conf`'s `http {}` block (or include a small file that does):

```nginx
# Container nginx on a docker user network — use docker's embedded resolver.
# valid= sets the cache TTL.
resolver 127.0.0.11 valid=10s ipv6=off;

# Host nginx with systemd-resolved:
# resolver 127.0.0.53 valid=10s ipv6=off;
```

Without this, the variable-form `proxy_pass` fails silently with "no resolver defined" and `502 Bad Gateway` at request time. This is **Trap 4** — do not skip it.

## Step 3: Generate the Drop-in vhost

Substitute `<DOMAIN>`, `<BACKEND_CONTAINER>`, `<FRONTEND_CONTAINER>` with the values from Step 1.

```nginx
# HTTP -> HTTPS redirect
server {
    listen 80;
    server_name <DOMAIN>;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name <DOMAIN>;

    ssl_certificate     /etc/nginx/ssl/<DOMAIN>.crt;
    ssl_certificate_key /etc/nginx/ssl/<DOMAIN>.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    add_header X-Frame-Options SAMEORIGIN always;
    add_header X-Content-Type-Options nosniff always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    access_log /var/log/nginx/<DOMAIN>_access.log;
    error_log  /var/log/nginx/<DOMAIN>_error.log;

    # All /api/* (admin, auth, config, webhooks/aegis, ...) goes to the
    # gatekeeper backend. The frontend defines no /api/* routes — routing
    # an unmapped /api/* to Next.js will server-side-fetch the same origin
    # and loop through Cloudflare, producing Error 1000. See Trap 1.
    location /api/ {
        set $gk_backend <BACKEND_CONTAINER>;
        proxy_pass http://$gk_backend:7843;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # 30s, not 10s: the /api/auth/* proxy makes synchronous outbound
        # calls to Aegis, which can occasionally take longer under cold
        # start or upstream DB pressure. The gatekeeper itself responds
        # in single-digit ms; the headroom is for Aegis.
        proxy_read_timeout 30s;
        proxy_send_timeout 30s;
    }

    location / {
        set $gk_frontend <FRONTEND_CONTAINER>;
        proxy_pass http://$gk_frontend:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # X-Forwarded-Host + X-Forwarded-Port are required: without them,
        # Next.js 16's i18n middleware bakes the UPSTREAM port (3000) into
        # the Location header on its locale redirect, and browsers then
        # try to follow https://<DOMAIN>:3000/en, which fails. See Trap 2.
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port 443;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Drop this into the host's nginx layout — typically one of:

- `/etc/nginx/conf.d/<DOMAIN>.conf`
- `/etc/nginx/sites-available/<DOMAIN>` (then `ln -s` into `sites-enabled/`)
- The dockerized equivalent (often a mounted volume)

Confirm with the user which path matches their host before writing the file.

## Step 4 (Optional): Expose Root-Level Backend Endpoints

The Gatekeeper backend exposes three endpoints **at the root**, not under `/api/`:

| Path | Purpose | Add to this vhost? |
|---|---|---|
| `/authz` | nginx `auth_request` target for protected services | **Required** if any vhost — on this host or another — uses `auth_request` against `https://<DOMAIN>/authz`. Optional only when every protected vhost is on the same host and reaches the backend container directly over the docker network (Step 5's same-host pattern). If you are not sure, add it — a 200 from `/authz` for a real consumer is fine; a 307 to `/<locale>/authz` for an off-host consumer breaks `auth_request` with `unexpected status: 307` → 500 to the browser. |
| `/health` | health probe | Add only if external monitoring scrapes via the public URL. Internal docker `HEALTHCHECK` and Prometheus usually hit the container directly. |
| `/metrics` | Prometheus metrics | Same as `/health` — usually internal-only. |

If the user needs any of these on the public vhost, add a single shared backend block **before** `location /` (so the regex match wins over the prefix match):

```nginx
location ~ ^/(authz|health|metrics)$ {
    set $gk_backend <BACKEND_CONTAINER>;
    proxy_pass http://$gk_backend:7843;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

If `/authz` is only consumed by other location blocks on the same nginx (not by external clients), add `internal;` inside the block — that prevents external callers from hitting it directly.

**Default to leaving these out only if no off-host nginx will use this Gatekeeper for `auth_request`.** A 404 from Next.js for `/health` or `/metrics` when nothing depends on them is harmless. But for `/authz` specifically, "default to leaving it out" is wrong if any off-host consumer exists — Next.js's i18n middleware will 307 the path to `/<locale>/authz`, which silently breaks the calling vhost's `auth_request`. See **Failure Decoder**.

## Step 5 (Optional): CORS for Services Protected by Gatekeeper `/authz`

**Skip this step entirely** if the only thing this nginx serves is the Gatekeeper frontend + backend (the vhost from Step 3). It applies when **another** vhost on this host (or another host) uses `auth_request /authz_subrequest;` to delegate authorization to Gatekeeper, and that protected upstream is called by a browser cross-origin (typical: a tenant frontend on `https://app.example.com` calling APIs on `https://api.example.com`).

Without this, every cross-origin call sends an `OPTIONS` preflight, Gatekeeper checks `OPTIONS` against the route's allowed-methods list, finds it isn't configured, and denies — the browser sees a generic CORS error.

### Split of responsibilities

| Concern | Where it lives | Why |
|---|---|---|
| Origin allowlist enforcement | Gatekeeper backend (`CORS_ALLOWED_ORIGINS` env) | One place to manage cross-origin policy across all protected services. |
| `Access-Control-*` response headers on OPTIONS / actual responses | The protected upstream service (Flask-CORS, fastapi-cors, koa/cors, etc.) | nginx can't relay Gatekeeper-built headers cleanly because of phase ordering — see "Why no `auth_request_set`" below. |

### One-time backend setup

Set `CORS_ALLOWED_ORIGINS` in the Gatekeeper backend env (comma-separated, no trailing slash):

```
CORS_ALLOWED_ORIGINS=https://app.example.com,http://localhost:3000
```

Once set, Gatekeeper inspects the `X-Original-Origin` header on every `/authz` call and:

- **Origin allowlisted** → returns 200 → nginx forwards the original request (including OPTIONS) to the upstream.
- **Origin not allowlisted** → returns 403 → nginx denies → the browser's preflight fails → request never leaves the browser.

The upstream service is then responsible for emitting `Access-Control-*` response headers on both the OPTIONS preflight reply and the actual request that follows.

### vhost on the protected service

Add this vhost (or this pattern, applied to an existing vhost). Replace `gatekeeper-backend`, `your-upstream:8080`, and `api.example.com` with the real values.

```nginx
server {
    listen 443 ssl;
    server_name api.example.com;

    # ssl_certificate / ssl_certificate_key as usual ...

    # Internal subrequest target. Adjust hostname/port to wherever Gatekeeper
    # listens (often a docker service name on a shared user network).
    location = /authz_subrequest {
        internal;
        set $gk_backend gatekeeper-backend;
        proxy_pass http://$gk_backend:7843/authz;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";

        # Required: Gatekeeper authorizes against the original request, not the
        # subrequest's own URI/method.
        proxy_set_header X-Original-URI    $request_uri;
        proxy_set_header X-Original-Method $request_method;
        proxy_set_header X-Original-Host   $host;

        # Required for CORS: forward Origin so Gatekeeper can check it against
        # CORS_ALLOWED_ORIGINS. Without this, every cross-origin OPTIONS will
        # be denied with reason=cors_origin_not_allowed (origin field empty).
        proxy_set_header X-Original-Origin     $http_origin;
        proxy_set_header X-Original-User-Agent $http_user_agent;
    }

    location /api/ {
        auth_request /authz_subrequest;

        # Normal upstream proxy. The upstream is responsible for replying to
        # OPTIONS with 200/204 + Access-Control-* headers (Flask-CORS etc.).
        proxy_pass http://your-upstream:8080;
        proxy_set_header Host $host;
        # ... etc
    }
}
```

That's it on the nginx side — no `auth_request_set`, no `if ($request_method = OPTIONS)`, no `add_header` stanza. The architectural reason is below.

### Off-host consumer (nginx on a different host)

If the protected vhost is on a **different host** from the Gatekeeper deployment, the subrequest must go through Gatekeeper's public URL — there is no shared docker network. This requires Step 4 to be applied on the Gatekeeper host (otherwise the subrequest hits Next.js and i18n-redirects to `/<locale>/authz`).

```nginx
location = /authz_subrequest {
    internal;
    proxy_pass https://<GATEKEEPER_DOMAIN>/authz;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";

    # HTTPS upstream — SNI is required; this host's resolver must
    # be able to resolve the public DNS name.
    proxy_ssl_server_name on;
    proxy_ssl_name        <GATEKEEPER_DOMAIN>;
    proxy_set_header Host <GATEKEEPER_DOMAIN>;

    proxy_set_header X-Original-URI        $request_uri;
    proxy_set_header X-Original-Method     $request_method;
    proxy_set_header X-Original-Host       $host;
    proxy_set_header X-Original-Origin     $http_origin;
    proxy_set_header X-Original-User-Agent $http_user_agent;
}
```

Verify Step 4 is applied on the Gatekeeper host **before** enabling this:

```bash
# MUST return 401/403, NOT a 307 to /<locale>/authz.
curl -i -s -o /dev/null -w "HTTP %{http_code}  Location: %{redirect_url}\n" \
  https://<GATEKEEPER_DOMAIN>/authz
```

### Upstream-side CORS

Whatever framework the protected service uses, install its CORS middleware and set the allowed origins to the same list as `CORS_ALLOWED_ORIGINS`. For Flask:

```python
from flask_cors import CORS

CORS(app, resources={
    r"/api/*": {"origins": ["https://app.example.com", "http://localhost:3000"]}
})
```

The redundancy (origin list lives in both Gatekeeper env and upstream code) is intentional: Gatekeeper enforces it as policy at the gateway, and the upstream emits the response headers the browser expects. The upstream's list can be a superset — Gatekeeper rejects anything not on its own allowlist before the upstream is reached.

### Why no `auth_request_set` + `if/return 204` here

Earlier patterns relayed Gatekeeper's CORS response headers into nginx variables via `auth_request_set` and short-circuited OPTIONS with `if ($request_method = OPTIONS) { return 204; }`. **That doesn't work.** nginx processes a request in fixed phases:

```
... → REWRITE phase ────► ACCESS phase ────► CONTENT phase
         ↑                    ↑
         └─ if/return         └─ auth_request fires here
            fires here
```

When the `if` matches, `return 204` short-circuits in the rewrite phase, **before** `auth_request` runs in the access phase. `auth_request_set` therefore never gets populated — every captured variable is empty, and `add_header Access-Control-Allow-Origin $cors_origin` emits an empty value (which the browser drops the response body for). There are workarounds involving `error_page` chains to a named location, but they're brittle across nginx versions and don't compose well with other directives.

The clean answer: **don't try to relay the headers through nginx**. Have the upstream emit them directly, and use Gatekeeper purely for the Origin allowlist enforcement at the auth subrequest level.

### Consumer-side traps

1. **Origin must be on Gatekeeper's allowlist.** If it isn't, `/authz` returns 403 and nginx denies the preflight. Loki entry: `reason: cors_origin_not_allowed`. Fix: add the origin to `CORS_ALLOWED_ORIGINS` in the backend env and restart Gatekeeper.
2. **The upstream must respond to OPTIONS.** If the CORS middleware is missing, OPTIONS will pass authz (Gatekeeper returns 200) but the upstream returns 405 Method Not Allowed. Loki entry shows `CORS preflight allowed` but the browser still fails — check the upstream, not Gatekeeper.
3. **Don't use `add_header Access-Control-Allow-Origin '*'` on the upstream.** The `*` wildcard is incompatible with credentialed requests (browsers reject it when `withCredentials: true`). Echo the specific allowlisted origin instead — every CORS middleware does this when configured with an allowlist.
4. **`X-Original-Origin` is the header name Gatekeeper reads.** nginx's `auth_request` strips the browser's `Origin` header from the subrequest unless you forward it explicitly. Don't rename it.

### Smoke test from anywhere on the public internet

```bash
# Allowed origin -> upstream emits Access-Control-* headers
curl -i -X OPTIONS https://api.example.com/api/some-protected-route \
  -H "Origin: https://app.example.com" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: Content-Type, Authorization"
# Expect: HTTP/2 200 (or 204) with access-control-allow-origin: https://app.example.com,
# access-control-allow-methods, access-control-allow-headers, vary: Origin

# Disallowed origin -> Gatekeeper rejects, nginx returns 403
curl -i -X OPTIONS https://api.example.com/api/some-protected-route \
  -H "Origin: https://evil.example.com" \
  -H "Access-Control-Request-Method: POST"
# Expect: HTTP/2 403 (nginx default), no Access-Control-* headers
```

Cross-check Gatekeeper's Loki for `CORS preflight allowed` (allowed origin) and `CORS preflight denied` with `reason: cors_origin_not_allowed` (disallowed origin) — both should fire for the two curls above.

## Step 6: Apply the Configuration

```bash
# After dropping the file into the right path for this host's nginx layout:
nginx -t && nginx -s reload

# If nginx runs in a container:
# docker exec <nginx-container> nginx -t && docker exec <nginx-container> nginx -s reload
```

If `nginx -t` complains about a missing `resolver`, go back to Step 2.

## Step 7: Smoke Tests

Run these from anywhere on the public internet (a laptop on a different network is fine — these go through Cloudflare):

```bash
# 1. Frontend root -> should 307 to /<locale> on the SAME origin (no :3000 leak)
curl -i -s -o /dev/null -w 'status=%{http_code}\nlocation=%{redirect_url}\n' \
  https://<DOMAIN>/

# 2. Public config endpoint -> 200 with JSON
curl -i https://<DOMAIN>/api/config

# 3. Auth probe -> 400 with {"error":"Invalid or expired verification token"}
curl -i -X POST https://<DOMAIN>/api/auth/check-verification-token \
  -H 'Content-Type: application/json' \
  -d '{"token":"probe"}'

# 4. Admin probe -> 401
curl -s -o /dev/null -w '%{http_code}\n' https://<DOMAIN>/api/admin/clients
```

### Expected status matrix

| Path | Expected | What it proves |
|---|---|---|
| `GET /` | 307 → `https://<DOMAIN>/<locale>` (no `:3000`) | `X-Forwarded-*` headers landed correctly |
| `GET /api/config` | 200, JSON `{aegisApiUrl, siteName, siteDomain}` | `/api/*` routes to backend; `/api/config` reachable |
| `POST /api/auth/check-verification-token` | 400 JSON | Backend reachable, Aegis tenant key valid |
| `GET /api/admin/clients` | 401 JSON | Admin namespace reachable, auth enforced |

Any deviation → consult the **Failure Decoder** below.

## Traps — Do Not "Simplify" These Away

These four decisions look like noise on a casual read. Each one fixes a real outage. Do not let a future edit collapse any of them.

1. **`location /api/` is intentionally a broad prefix block, not per-route.** Don't break it out into `location /api/admin/`, `location /api/auth/`, `location /api/config`, etc. Every time the backend adds a new public endpoint (and it will), a per-route allowlist would silently route the new path to Next.js, which then server-side-fetches its own origin and Cloudflare returns Error 1000 — `DNS points to prohibited IP`. Catch-all on `/api/` is the safe shape.

2. **`X-Forwarded-Host` and `X-Forwarded-Port: 443` on the `/` block are not optional.** Next.js 16 (with `next-intl` middleware) builds absolute redirect URLs from request metadata. Without these headers, the upstream port (3000) leaks into `Location`. Symptom: hitting `/` returns `307` with `Location: https://<DOMAIN>:3000/en` — broken in every browser.

3. **The `set $var <container>; proxy_pass http://$var:port;` pattern is intentional.** Writing `proxy_pass http://<container>:7843;` literally makes nginx resolve the hostname at config-load time. If the container is down when nginx reloads, nginx refuses to start. The `set` indirection defers resolution until request time, so the vhost survives container churn.

4. **The variable-form `proxy_pass` (Trap 3) requires a `resolver` directive.** See Step 2. Without one, request-time DNS lookup fails and you get `502 Bad Gateway`. The required directive lives once in the http block, not per-location.

## Failure Decoder

| Symptom | Likely cause | Fix |
|---|---|---|
| `/` redirects to `https://<DOMAIN>:3000/...` | Missing `X-Forwarded-Host` / `X-Forwarded-Port` | Add them on the `/` block (Trap 2) |
| `/api/<anything>` returns 403 with Cloudflare HTML (`errorCode: 1000`, `<title>DNS points to prohibited IP</title>`) | nginx routed `/api/*` to Next.js → server-side-fetch loop through Cloudflare | Make `location /api/` a single broad block targeting the backend (Trap 1) |
| `502 Bad Gateway` on first request after container restart | Variable-form `proxy_pass` with no resolver, or a stale glibc lookup | Confirm `resolver` directive is present in the http block (Trap 4); restart nginx after adding |
| `nginx -t` fails with `host not found in upstream "<container>"` | Container down + literal (non-variable) `proxy_pass` | Use `set $var <container>; proxy_pass http://$var:port;` (Trap 3) |
| `/api/auth/*` returns 401 `"Invalid or missing tenant API key"` | Backend env mismatch — `AEGIS_TENANT_API_KEY` / `AEGIS_SITE_ID` don't match Aegis's `sites` row | Out of nginx scope; fix backend env |
| `/api/config` returns 200 but JSON is `{"aegisApiUrl":"","siteName":"gatekeeper","siteDomain":""}` | Backend env vars `AEGIS_API_URL` / `SITE_NAME` / `SITE_DOMAIN` missing | Out of nginx scope; set them in backend container env and restart |
| Browser shows "Failed to load configuration from /api/config: ..." | The frontend successfully reached `/api/config` but got a non-200 response | Run smoke test 2 above; whatever curl shows is what the browser sees |
| `auth request unexpected status: 307` in nginx error log, `Location: https://<gatekeeper-host>/<locale>/authz` (e.g. `/en/authz`) | Off-host `auth_request` consumer reached Gatekeeper's public URL, but the Gatekeeper vhost has no explicit `/authz` location → fell through to Next.js → next-intl redirected to a localized path. `auth_request` only accepts 2xx/401/403, so nginx returns 500 to the client. | Apply Step 4's `location ~ ^/(authz\|health\|metrics)$` block on the Gatekeeper vhost. Re-test with the curl in Step 5's "Off-host consumer" subsection. |

## Report Back

After applying, confirm:

- Output of all four smoke tests
- The vhost file path used
- That `nginx -t` passed and reload succeeded
- Which optional root-level endpoints (`/authz`, `/health`, `/metrics`) were added, if any, and why
- Whether Step 5 (CORS via auth_request) was applied to any sibling vhosts on this host
