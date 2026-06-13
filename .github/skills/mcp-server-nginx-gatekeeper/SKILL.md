---
name: mcp-server-nginx-gatekeeper
description: Use this skill when the user asks to "add a new MCP server behind nginx", "wire an MCP into the mcp.<domain> vhost", "expose an MCP container with gatekeeper auth", or otherwise needs to put a Streamable-HTTP MCP server (FastMCP or low-level SDK) behind nginx with ByteForge Gatekeeper auth (`auth_request /auth`). Emits a shared `conf.d/snippets/mcp-location.conf` (proxy/auth/streaming headers all in one place) and either a single new `location /mcp-<name>` block (brownfield) or the full umbrella vhost from scratch (greenfield). Includes the `.well-known` OAuth-discovery bypass that forces MCP clients like Claude Code to fall back to bearer-token auth, the `/mcp-<name>` → `/mcp` rewrite trio that makes path-prefix routing survive Streamable-HTTP's absolute upstream endpoint, and the buffering/timeout settings that keep streaming connections alive.
---

# MCP server nginx vhost with Gatekeeper auth

This skill wires a Streamable-HTTP MCP server (FastMCP or low-level SDK) into an nginx vhost that delegates authorization to ByteForge Gatekeeper via `auth_request /auth`.

Two paths:

- **Brownfield** — the umbrella `mcp.<DOMAIN>` vhost already exists and has at least one MCP server under it (the typical "I want to add another MCP" case). The skill appends a new `location /mcp-<NAME>` block, ensures the shared snippet is present, and ensures the `.well-known` bypass is present.
- **Greenfield** — no umbrella vhost exists yet. The skill emits the full `mcp.<DOMAIN>` server block (TLS, resolver, gatekeeper auth subrequest include, `.well-known` bypass, first MCP location), all wired through the same shared snippet.

In both paths, the per-MCP location block is a thin 8-line wrapper that sets `$mcp_upstream` and `$mcp_port`, runs the three rewrites, and `include`s the shared snippet — the heavy lifting (auth_request, proxy headers, buffering, timeouts) lives in `conf.d/snippets/mcp-location.conf` so adding the fourth MCP doesn't mean copy-pasting 30 lines for the fourth time.

Each load-bearing decision is documented in **Traps** below — read that section before editing anything the skill emits.

## When to Use This Skill

- Adding a new MCP server to an existing `mcp.<DOMAIN>` umbrella vhost
- Bringing up the umbrella vhost on a fresh host where MCP servers will live behind gatekeeper auth
- Refactoring an existing `mcp.<DOMAIN>` vhost whose MCP location blocks each duplicate the same proxy/auth/streaming headers
- Debugging why a Claude Code MCP client keeps trying OAuth discovery instead of using the bearer token in `.mcp.json`
- Debugging why `/mcp-<name>/messages/` 404s (you're using SSE behind a path prefix — switch to streamable-http)

## What This Skill Creates

1. **`conf.d/snippets/mcp-location.conf`** — the shared snippet (auth_request, proxy headers, streaming/buffering settings) that every MCP location `include`s
2. **A per-MCP `location /mcp-<NAME>` block** — sets the upstream var and port, runs the three `^/mcp-<NAME>(/.*)?` → `/mcp` rewrites, and `include`s the snippet
3. **(Greenfield only) the full umbrella vhost** — HTTP→HTTPS, TLS 443, resolver, gatekeeper `/auth` include, `.well-known` bypass, first MCP location
4. **(Brownfield, optional) a refactor of existing MCP location blocks** — collapses duplicated 30-line blocks down to 8 lines each that `include` the new snippet
5. **Smoke-test commands** — three curls that prove auth, bypass, and streaming all work
6. **Failure Decoder** — symptom → cause → fix table

## Step 1: Gather Information

Ask the user these before generating anything. Substitute consistently throughout.

1. **"What is the umbrella MCP domain?"** (e.g., `mcp.example.com`)
   - Stored as `<DOMAIN>`

2. **"What short name identifies this MCP server in the URL path?"** (e.g., `loki`, `materia`, `weather`)
   - Stored as `<NAME>` — must be lowercase, no slashes, no path separators
   - Becomes the URL prefix `/mcp-<NAME>`

3. **"What is the Docker service name of the MCP container?"** (e.g., `loki-reader-mcp`)
   - Stored as `<UPSTREAM_CONTAINER>` — must be reachable by hostname on the docker network nginx is attached to

4. **"What port does the MCP container listen on inside the docker network?"** (default: `8000`)
   - Stored as `<UPSTREAM_PORT>`

5. **"Does the umbrella `<DOMAIN>` vhost already exist in nginx?"**
   - If **yes** → brownfield path (Step 2 verifies, Step 4 appends)
   - If **no** → greenfield path (Step 5 emits the full vhost)
   - If unsure, run `grep -rn "server_name <DOMAIN>" /etc/nginx/` (or your nginx config path) to check

6. **"Is the gatekeeper auth snippet at `conf.d/snippets/auth-gatekeeper.conf` already present?"**
   - This skill assumes that snippet defines `location = /auth` (internal subrequest target). If absent, point the user at the `gatekeeper-nginx-setup` skill — that skill is the source of the snippet. Do **not** redefine `/auth` here.

7. **(Brownfield only) "How many MCP location blocks already exist in this vhost, and do they duplicate the same proxy/auth/streaming headers?"**
   - If **0 existing** → just append the new block + the snippet
   - If **1+ existing, inlined** → offer the optional refactor in Step 6
   - Run `grep -n "location /mcp-" <vhost-file>` to enumerate

## Step 2: Verify Prerequisites

Confirm the following are in place. Each maps to a trap in **Traps** below.

1. **Resolver directive** — the snippet uses `proxy_pass http://$mcp_upstream:$mcp_port;` to defer DNS to request time, which requires a `resolver` visible to the server block. Check:
   ```bash
   grep -rn "^\s*resolver " /etc/nginx/
   ```
   - For container nginx on a docker user network: `resolver 127.0.0.11 valid=10s ipv6=off;`. The `ipv6=off` flag is required if any upstream resolved through this resolver is on a dual-stack hostname (Cloudflare-fronted, public-DNS, etc.) — without it, nginx may pick an AAAA record that the IPv4-only docker bridge can't route, and `auth_request` returns 403 across every protected route. Safe to include unconditionally.
   - If missing → proxy_pass fails silently with "no resolver defined" → 502 at request time. Add it once in the server block (greenfield does this) or in nginx.conf's http block.

2. **`auth-gatekeeper.conf` snippet** — must `include` cleanly in the server block and define `location = /auth` (internal). Verify with:
   ```bash
   grep -n "location = /auth" /etc/nginx/conf.d/snippets/auth-gatekeeper.conf
   ```

3. **MCP server transport** — the MCP server MUST be running with `streamable-http` transport, not `sse`. SSE's `/messages/` is a relative URL the SDK hands the client, and a relative URL behind a path prefix (`/mcp-<NAME>`) resolves to `/mcp-<NAME>/messages/` on the client but `/messages/` upstream — guaranteed 404. Streamable-HTTP exposes a single `/mcp` endpoint with no relative-URL gotcha. Confirm with the user before proceeding.

## Step 3: Emit the Shared Snippet

Write `<NGINX_CONFD>/snippets/mcp-location.conf` (where `<NGINX_CONFD>` is the user's `conf.d` location, typically `/etc/nginx/conf.d` or a docker volume mounted there):

```nginx
# Shared MCP location config — included by each `location /mcp-<NAME>` block.
#
# Caller must set the following BEFORE `include`-ing this file:
#   set $mcp_upstream <docker-service-name>;
#   set $mcp_port    <port>;
# and the three rewrites (see per-MCP block).
#
# Why a snippet: every MCP location needs the same ~25 lines of auth/proxy/
# streaming config. A second copy is a typo away from drift; a fourth copy is
# guaranteed to drift. Keep divergent parts (upstream, rewrites) per-location;
# keep invariants here.
#
# Why NOT in conf.d/ root: nginx auto-loads `conf.d/*.conf` at http{} level,
# but this file is location{}-level config (auth_request, proxy_pass, etc.)
# and MUST be explicitly `include`d inside a location{} block. Keeping it
# under conf.d/snippets/ avoids the auto-load — see Trap 7.

auth_request /auth;

auth_request_set $auth_client_id   $upstream_http_x_auth_client_id;
auth_request_set $auth_client_name $upstream_http_x_auth_client_name;
auth_request_set $auth_route_id    $upstream_http_x_auth_route_id;

proxy_pass http://$mcp_upstream:$mcp_port;

proxy_http_version 1.1;
proxy_set_header Host              $host;
proxy_set_header X-Real-IP         $remote_addr;
proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;

# Strip the inbound Authorization header before proxying. Gatekeeper already
# authenticated this request (via the /auth subrequest); some MCP servers
# choke on a residual bearer they don't know what to do with. The downstream-
# facing X-Client-* headers below carry the identity instead. See Trap 4.
proxy_set_header Authorization "";

# Authenticated client info from the /auth subrequest, forwarded so the MCP
# upstream can attribute requests without re-validating the token.
proxy_set_header X-Client-ID   $auth_client_id;
proxy_set_header X-Client-Name $auth_client_name;
proxy_set_header X-Route-ID    $auth_route_id;

# Streamable-HTTP requires these. Without `proxy_buffering off`, nginx
# accumulates the chunked response and the client sees 60 seconds of silence
# followed by a wall of events. The 3600s timeouts keep idle-but-healthy
# streaming connections from being killed by nginx's 60s defaults.
proxy_buffering         off;
proxy_request_buffering off;
proxy_read_timeout      3600s;
proxy_send_timeout      3600s;
```

This file is written **once per host**. Subsequent MCP additions just `include` it.

## Step 4: Add the Per-MCP Location Block

For brownfield (umbrella vhost exists): append inside the `server { server_name <DOMAIN>; ... }` block, after the `.well-known` bypass.

For greenfield: this block is part of Step 5's full vhost.

```nginx
# <NAME> MCP server
location /mcp-<NAME> {
    set $mcp_upstream <UPSTREAM_CONTAINER>;
    set $mcp_port     <UPSTREAM_PORT>;

    rewrite ^/mcp-<NAME>$       /mcp break;
    rewrite ^/mcp-<NAME>/$      /mcp break;
    rewrite ^/mcp-<NAME>/(.+)   /$1  break;

    include /etc/nginx/conf.d/snippets/mcp-location.conf;
}
```

Three rewrites, not one, on purpose — see Trap 2.

If this is the **first MCP being added to a brand-new umbrella vhost** (or a brownfield vhost that somehow lacks the bypass), also ensure the `.well-known` bypass is present, somewhere before the per-MCP `location` block:

```nginx
# OAuth discovery bypass. MCP clients (Claude Code, others) probe
# `<DOMAIN>/.well-known/oauth-authorization-server` to decide whether to
# negotiate OAuth or fall back to the static bearer token in their config.
# Returning 404 unauthenticated forces the bearer-token path, which is what
# we want — Gatekeeper does the auth, the MCP server stays dumb. See Trap 3.
location ~ ^/mcp-[^/]+/\.well-known/ {
    return 404;
}
```

This regex location only needs to exist **once** per umbrella vhost — it matches every `/mcp-*/.well-known/...` path. The brownfield path verifies it's already there with `grep -n "well-known" <vhost-file>`; if missing, add it once before any `location /mcp-*`.

## Step 5 (Greenfield only): Emit the Full Umbrella vhost

If no `mcp.<DOMAIN>` vhost exists yet, emit this entire server block. Adjust SSL cert paths to the host's nginx convention.

```nginx
# HTTP -> HTTPS redirect
server {
    listen 80;
    server_name <DOMAIN>;
    return 301 https://$host$request_uri;
}

# HTTPS umbrella vhost for all MCP servers
server {
    listen 443 ssl;
    server_name <DOMAIN>;

    # Docker DNS resolver — prevents stale IP caching when MCP containers
    # restart. The variable-form `proxy_pass http://$mcp_upstream:$mcp_port`
    # in snippets/mcp-location.conf REQUIRES this. Without it, nginx fails
    # with "no resolver defined" at request time → 502. See Trap 5.
    #
    # ipv6=off: if the auth subrequest or any proxy target is on a dual-stack
    # public hostname (Cloudflare-fronted, etc.), nginx may pick the AAAA
    # record and connect() over IPv6 — but a default docker bridge is IPv4-
    # only, so the subrequest fails with ENETUNREACH → 403 to client.
    resolver 127.0.0.11 valid=10s ipv6=off;

    ssl_certificate     /etc/nginx/ssl/<DOMAIN>.crt;
    ssl_certificate_key /etc/nginx/ssl/<DOMAIN>.key;
    ssl_protocols TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;

    # Optional ByteForge stack snippets — include if the host already uses them.
    # include /etc/nginx/conf.d/snippets/cloudflare-real-ip.conf;
    # include /etc/nginx/conf.d/snippets/scanner-blocklist.conf;

    # Defines `location = /auth` (internal) → gatekeeper /authz subrequest.
    # Source: the `gatekeeper-nginx-setup` skill. Do NOT redefine /auth here.
    include /etc/nginx/conf.d/snippets/auth-gatekeeper.conf;

    # OAuth discovery bypass — see Trap 3 for why this returns 404, not 401.
    location ~ ^/mcp-[^/]+/\.well-known/ {
        return 404;
    }

    # First MCP server — copy this block (adjusting <NAME>, upstream, port)
    # for each additional MCP.
    location /mcp-<NAME> {
        set $mcp_upstream <UPSTREAM_CONTAINER>;
        set $mcp_port     <UPSTREAM_PORT>;

        rewrite ^/mcp-<NAME>$       /mcp break;
        rewrite ^/mcp-<NAME>/$      /mcp break;
        rewrite ^/mcp-<NAME>/(.+)   /$1  break;

        include /etc/nginx/conf.d/snippets/mcp-location.conf;
    }
}
```

## Step 6 (Brownfield, optional): Refactor existing inline MCP blocks

Apply this **only** if the user has 1+ existing MCP location blocks that inline the proxy/auth/streaming headers (the duplication this skill exists to remove). Skip if existing blocks already `include` the snippet.

For each existing inline block:

**Before** (~30 lines):
```nginx
location /mcp-foo {
    auth_request /auth;
    auth_request_set $auth_client_id $upstream_http_x_auth_client_id;
    auth_request_set $auth_client_name $upstream_http_x_auth_client_name;
    auth_request_set $auth_route_id $upstream_http_x_auth_route_id;

    set $upstream_foo_mcp foo-container;

    rewrite ^/mcp-foo$ /mcp break;
    rewrite ^/mcp-foo/$ /mcp break;
    rewrite ^/mcp-foo/(.+) /$1 break;

    proxy_pass http://$upstream_foo_mcp:8000;

    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Authorization "";

    proxy_set_header X-Client-ID $auth_client_id;
    proxy_set_header X-Client-Name $auth_client_name;
    proxy_set_header X-Route-ID $auth_route_id;

    proxy_buffering off;
    proxy_request_buffering off;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
```

**After** (~8 lines):
```nginx
location /mcp-foo {
    set $mcp_upstream foo-container;
    set $mcp_port     8000;

    rewrite ^/mcp-foo$       /mcp break;
    rewrite ^/mcp-foo/$      /mcp break;
    rewrite ^/mcp-foo/(.+)   /$1  break;

    include /etc/nginx/conf.d/snippets/mcp-location.conf;
}
```

**Important**: the snippet uses generic var names `$mcp_upstream` / `$mcp_port`. If existing blocks used per-MCP names like `$upstream_foo_mcp`, rename to `$mcp_upstream` during refactor. nginx variables are per-request, evaluated inside the matched location — reusing `$mcp_upstream` across sibling location blocks is fine; each request only enters one of them.

Confirm with the user before refactoring existing blocks. The before/after is mechanical, but it's a working production config — show the diff and reload with `nginx -t` before `nginx -s reload`.

## Step 7: Reload and Verify

```bash
# Inside the nginx container (or on the host, depending on layout)
nginx -t          # syntax check
nginx -s reload   # apply
```

Smoke tests (from outside the host):

```bash
# 1. Auth required — without a bearer token, gatekeeper /auth returns 401.
curl -i https://<DOMAIN>/mcp-<NAME>

# 2. OAuth discovery bypass — should return 404 (not 401), causing Claude Code
#    to fall back to the static bearer in .mcp.json instead of negotiating OAuth.
curl -i https://<DOMAIN>/mcp-<NAME>/.well-known/oauth-authorization-server

# 3. Authenticated MCP request — should return a JSON-RPC initialize response.
curl -i -H "Authorization: Bearer <TOKEN>" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' \
        https://<DOMAIN>/mcp-<NAME>
```

Then add to `.mcp.json` on the client:

```json
{
  "mcpServers": {
    "<NAME>": {
      "type": "http",
      "url": "https://<DOMAIN>/mcp-<NAME>",
      "headers": { "Authorization": "Bearer <TOKEN>" }
    }
  }
}
```

Note: `"type": "http"`, **not** `"sse"`. The transport on the wire is Streamable-HTTP, even when the underlying SDK class is named ambiguously.

## Traps

These are the load-bearing decisions in the emitted config. They look stylistic; they aren't.

### Trap 1 — Streamable-HTTP, not SSE

The MCP SDK's SSE transport mounts two endpoints: `/sse` (the EventSource) and `/messages/` (the POST sink). The SDK hands the client a **relative** URL for `/messages/` on connect. Behind a path prefix like `/mcp-<NAME>`, the client resolves that relative URL to `/mcp-<NAME>/messages/`, but nothing upstream is mounted there (the SDK mounted `/messages/`). Result: every client POST 404s.

Streamable-HTTP exposes a single `/mcp` endpoint with no client-side URL discovery, so path-prefix routing just works.

**Fix**: configure the MCP server with `MCP_TRANSPORT=streamable-http` and tell the client `"type": "http"`. Do not try to fix this with nginx rewrites — the relative URL is built in the client.

### Trap 2 — The three rewrites

`location /mcp-<NAME>` matches `/mcp-<NAME>`, `/mcp-<NAME>/`, and `/mcp-<NAME>/anything`. Without rewrites, the proxy_pass forwards the path unmodified — but the upstream only mounts `/mcp`. You need to map all three forms.

Order matters: nginx evaluates rewrites top to bottom, and `break` stops further rewrite processing in the location. The literal-match rewrites for `^/mcp-<NAME>$` and `^/mcp-<NAME>/$` come first; the greedy `^/mcp-<NAME>/(.+)` comes last and strips the prefix off any subpath. Subpaths the upstream doesn't recognize will 404 from the SDK, which is the right behavior — `/mcp-<NAME>/foo` was never going to mean anything.

### Trap 3 — `.well-known` bypass returns 404, not 401

If you protect `/mcp-<NAME>/.well-known/oauth-authorization-server` with `auth_request /auth`, gatekeeper returns 401 for the unauthenticated probe. Claude Code interprets 401 on a `.well-known/oauth-*` URL as "OAuth is available — let's negotiate" and starts an OAuth flow that will never complete, because there's no OAuth provider behind this endpoint — just gatekeeper bearer auth.

Returning 404 (no auth_request on this regex) tells the client "no OAuth here", and it falls back to the static bearer in `.mcp.json`.

This is why the regex location `~ ^/mcp-[^/]+/\.well-known/` lives **outside** any `auth_request` directive, and is matched before the per-MCP prefix locations (regex locations beat prefix locations in nginx).

### Trap 4 — Strip the inbound `Authorization` header

After `auth_request /auth` succeeds, the original request still carries the client's `Authorization: Bearer <token>` header. Most MCP servers don't expect to see it (they trust the gatekeeper-injected `X-Client-*` headers) and some choke on it outright. `proxy_set_header Authorization "";` clears it before proxying.

If the upstream MCP server **does** need the original bearer (rare — usually only if it's doing its own auth on top), remove this line for that MCP only and document the deviation in the per-MCP location block. Do **not** delete it from the snippet — that would silently change behavior for every MCP that depends on the strip.

### Trap 5 — Resolver required for variable proxy_pass

The snippet uses `proxy_pass http://$mcp_upstream:$mcp_port;`. The variable form forces nginx to resolve the upstream **at request time**, not at config-load time. That's exactly what we want — MCP containers restart and get new IPs on the docker network, and a static `proxy_pass http://foo-container:8000` would cache the first IP forever.

But variable form requires a `resolver` directive. Without it, nginx fails with "no resolver defined" at request time → 502 to the client, "host not found" in error.log. The greenfield vhost includes `resolver 127.0.0.11 valid=10s ipv6=off` (docker's embedded DNS). The brownfield path verifies one exists.

Add `ipv6=off` to the resolver line if any upstream is on a dual-stack hostname (e.g., Cloudflare-fronted public services like a remote gatekeeper). Without it, nginx may pick the AAAA result, try `connect()` over IPv6, and fail with `ENETUNREACH` because the default docker bridge is IPv4-only. The failure mode is especially nasty: every protected route returns 403, including routes that were working seconds earlier, because the resolver picks IPv6 non-deterministically. The diagnosis is in error.log (`Network is unreachable ... subrequest: "/auth"`), not in the access log or gatekeeper logs.

### Trap 6 — Buffering off, timeouts long

`proxy_buffering off` and `proxy_request_buffering off` are non-negotiable for Streamable-HTTP. With buffering on, nginx accumulates response chunks until either the buffer fills or the upstream closes the stream — the client sees a long silence followed by a wall of events. The whole point of streaming is incremental delivery.

`proxy_read_timeout 3600s` and `proxy_send_timeout 3600s` survive long idle periods on a stream. nginx's defaults (60s) will kill a perfectly healthy streaming connection that happens to go quiet for a minute.

### Trap 7 — Snippet lives under `conf.d/snippets/`, not `conf.d/`

nginx auto-loads `conf.d/*.conf` at the **http{}** level. The MCP snippet is **location{}**-level config — `auth_request`, `proxy_pass`, `proxy_set_header` are not valid at http scope. If you put `mcp-location.conf` directly in `conf.d/`, nginx will fail to start with `"X" directive is not allowed here`.

The `snippets/` subdirectory keeps the snippet outside auto-loading, and each `location` block explicitly `include`s it. This is the same pattern used by `auth-gatekeeper.conf`, `cloudflare-real-ip.conf`, and `scanner-blocklist.conf` in the ByteForge stack.

## Failure Decoder

| Symptom | Likely Cause | Fix |
|---|---|---|
| `nginx: [emerg] "auth_request" directive is not allowed here` on reload | Snippet placed in `conf.d/` root (auto-loaded into http{} scope) | Move to `conf.d/snippets/`; ensure no `*.conf` glob picks it up. See Trap 7 |
| `502 Bad Gateway` immediately on first request; error log says `no resolver defined to resolve` | Missing `resolver` directive | Add `resolver 127.0.0.11 valid=10s;` to the server block. See Trap 5 |
| `502 Bad Gateway` shortly after container restart, was working before | Cached pre-restart IP — `valid=10s` should expire within seconds; or upstream is genuinely down | `docker ps` to confirm container is up; `docker logs <UPSTREAM_CONTAINER>` for crashes |
| `403 Forbidden` from nginx on every `/mcp-*` route, including ones that worked minutes ago. error.log shows `connect() to [<v6>]:... failed (101: Network is unreachable) ... subrequest: "/auth"` | Resolver missing `ipv6=off`; auth/proxy upstream is dual-stack but docker bridge is IPv4-only | Add `ipv6=off` to the resolver directive. See Trap 5 |
| `401 Unauthorized` even with what should be a valid bearer token | Token doesn't match a gatekeeper-registered route, or `auth-gatekeeper.conf` not `include`d in this vhost | Confirm `include …/auth-gatekeeper.conf` is inside the server block; check gatekeeper's route + token config |
| `404 Not Found` from upstream on POST after SSE connect | Using SSE transport behind a path prefix — `/messages/` resolved relative on the client | Switch server + client to streamable-http. See Trap 1 |
| Claude Code stuck in OAuth-discovery loop, never uses the bearer in `.mcp.json` | `.well-known` returns 401 (protected) instead of 404 | Verify the `~ ^/mcp-[^/]+/\.well-known/` location is present and returns 404 unconditionally. See Trap 3 |
| Stream connects, then 60 seconds of silence, then everything arrives at once | `proxy_buffering` not off, or `proxy_read_timeout` at default | Confirm snippet is `include`d in the location block. See Trap 6 |
| MCP server returns "missing required header" or rejects the request | Either `Authorization` not stripped (upstream confused by stale bearer) OR `X-Client-*` headers not arriving | Confirm `proxy_set_header Authorization "";` and the three `X-Client-*` lines are present in the snippet. See Trap 4 |
| Two MCP locations route to the same upstream | Copy-paste bug — both blocks set `$mcp_upstream` to the same value | Each location's `set` is location-scoped; check the literal value in each block |
| `nginx -t` says `unknown "mcp_upstream" variable` | A `proxy_pass http://$mcp_upstream:$mcp_port;` somewhere outside a location block (e.g., directly in `server{}`) — `set` only works inside `location{}` | Move the upstream/port `set` lines and the include into a `location {}` block |

## Marketplace Registration

If you're adding this skill to a marketplace repo (e.g., `byteforge-claude-skills`), append the skill path to `.claude-plugin/marketplace.json`:

```json
"skills": [
    ...,
    "./skills/mcp-server-nginx-gatekeeper"
]
```

And update the plugin's umbrella `description` to mention "MCP server nginx vhost with Gatekeeper auth" alongside the other skills.
