# Backend Aegis Identity Resolution

This file documents how a **backend** resolves Aegis identities to user records — including `role` for authorization. Two complementary endpoints exist depending on what you're starting with:

| Starting point | Endpoint | When to use |
|---|---|---|
| User's bearer token (e.g., from inbound `Authorization` header) | `GET /api/auth/me` | The frontend just sent us a request with the user's session token; who are they? |
| User's Aegis `user_id` (e.g., stored alongside an internal API key) | `GET /api/sites/{site_id}/users/{user_id}` | An inbound non-Aegis credential resolves to a user_id; what's their role? |

The frontend itself does not call either — it already has user info from `/api/auth/login`. These patterns are for the backend services the frontend talks to.

## Why `/api/auth/me` Exists

Before this endpoint, a downstream service holding an Aegis `auth_token` had three bad options:

1. Query the Aegis DB directly (breaks the service boundary).
2. Force the user to re-authenticate against each service (bad UX).
3. Build a custom "exchange" endpoint that trusts a client-asserted `user_id` — **this is exploitable**: anyone who guesses a `user_id` can mint service credentials for that user.

`/api/auth/me` closes the hole. A service forwards the `Authorization: Bearer <aegis_token>` header it received, and Aegis returns the authenticated user. Standard pattern, no shared secrets, no client-asserted identities.

## When to Use It

**Use `/me`** when a backend service receives a request from the frontend (or any other Aegis-authenticated client) and needs to know which user is making the request.

**Do not use `/me`** for:
- The frontend itself on the login page — use `/api/auth/login` and store the user info from the response.
- Polling / keep-alive checks — the token's `expires_at` is available client-side, no round-trip needed.

## Caching Guidance

- Cache `token → user` with a short TTL (default `30` seconds here) keyed by the token string.
- Do not cache the HTTP response object — Aegis already sends `Cache-Control: no-store` and HTTP proxies must honor that.
- Invalidate the cache entry on any 401 from `/me` (the token was revoked or expired between calls).

## Endpoint Contract

**Request:**
```
GET /api/auth/me
Authorization: Bearer <aegis_auth_token>
```

**Response 200 — standard Aegis user shape:**
```json
{
  "id": 42,
  "site_id": 1,
  "email": "user@example.com",
  "is_verified": true,
  "role": "user",
  "created_at": 1745280000,
  "updated_at": 1745280000
}
```

**Response 401 — any auth failure:**
```json
{ "error": "<message>" }
```

Aegis returns 401 for every failure mode (missing header, malformed header, unknown token, expired token) with **no distinction between them**. This is intentional to avoid leaking which kind of failure occurred. Your middleware should treat all 401s as "not authenticated" without trying to parse the message.

---

## Next.js API Route Helper (TypeScript)

For backends that are Next.js API routes (either in the same project as the frontend or a separate Next.js service).

**Requires:** `byteforge-aegis-client-js@2.8.0` or newer.

**File:** `lib/aegisAuth.ts`

```typescript
import { AuthClient } from 'byteforge-aegis-client-js';
import type { NextRequest } from 'next/server';

const AEGIS_API_URL = process.env.AEGIS_API_URL || '{aegis_api_url}';
const CACHE_TTL_MS = 30_000;

export interface AegisUser {
  id: number;
  site_id: number;
  email: string;
  is_verified: boolean;
  role: string;
  created_at: number;
  updated_at: number;
}

interface CacheEntry {
  user: AegisUser;
  expiresAt: number;
}

const tokenCache = new Map<string, CacheEntry>();

function extractBearerToken(request: NextRequest): string | null {
  const header = request.headers.get('authorization');
  if (!header || !header.startsWith('Bearer ')) {
    return null;
  }
  return header.slice(7);
}

async function resolveUser(token: string): Promise<AegisUser | null> {
  const cached = tokenCache.get(token);
  if (cached && cached.expiresAt > Date.now()) {
    return cached.user;
  }

  const client = new AuthClient({ apiUrl: AEGIS_API_URL, autoRefresh: false });
  client.setAuthToken(token);
  const result = await client.me();

  if (!result.success) {
    tokenCache.delete(token);
    return null;
  }

  tokenCache.set(token, { user: result.data, expiresAt: Date.now() + CACHE_TTL_MS });
  return result.data;
}

export async function authenticateRequest(request: NextRequest): Promise<AegisUser | null> {
  const token = extractBearerToken(request);
  if (!token) {
    return null;
  }
  return resolveUser(token);
}
```

**Usage in a route handler:**

```typescript
// app/api/protected/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { authenticateRequest } from '@/lib/aegisAuth';

export async function GET(request: NextRequest): Promise<NextResponse> {
  const user = await authenticateRequest(request);
  if (!user) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  return NextResponse.json({ message: `Hello ${user.email}`, user_id: user.id });
}
```

**Notes:**
- The in-process `Map` cache is per-server-instance. In a multi-replica deployment each replica hits `/me` independently on first request for a token — acceptable given the 30-second TTL and the low cost of `/me`. Swap to Redis if you need cross-replica sharing.
- `AEGIS_API_URL` is a **server-side** env var here, distinct from the client-side `NEXT_PUBLIC_AEGIS_API_URL`. They can have the same value, but the server one does not need to be public.

---

## Flask Decorator (Python)

For sibling Flask backends that receive Aegis-authenticated requests from the frontend.

**Requires:** `byteforge-aegis-client-python@1.2.0` or newer.

**File:** `app/decorators/aegis_auth.py`

```python
import os
import time
from functools import wraps
from typing import Callable

from flask import g, jsonify, request
from byteforge_aegis_client import AegisClient, AegisUnauthorized

AEGIS_API_URL = os.environ.get('AEGIS_API_URL', '{aegis_api_url}')
CACHE_TTL_SECONDS = 30

_token_cache: dict[str, tuple[dict, float]] = {}


def _extract_bearer_token() -> str | None:
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        return None
    return header[7:]


def _resolve_user(token: str) -> dict | None:
    cached = _token_cache.get(token)
    if cached is not None and cached[1] > time.time():
        return cached[0]

    client = AegisClient(api_url=AEGIS_API_URL)
    client.set_auth_token(token)
    try:
        user = client.me()
    except AegisUnauthorized:
        _token_cache.pop(token, None)
        return None

    _token_cache[token] = (user, time.time() + CACHE_TTL_SECONDS)
    return user


def aegis_auth_required(func: Callable) -> Callable:
    @wraps(func)
    def wrapper(*args, **kwargs):
        token = _extract_bearer_token()
        if token is None:
            return jsonify({'error': 'Unauthorized'}), 401

        user = _resolve_user(token)
        if user is None:
            return jsonify({'error': 'Unauthorized'}), 401

        g.current_user = user
        return func(*args, **kwargs)

    return wrapper
```

**Usage on a flask-smorest view:**

```python
from flask import g
from flask.views import MethodView
from flask_smorest import Blueprint

from app.decorators.aegis_auth import aegis_auth_required

bp = Blueprint('protected', __name__, url_prefix='/api/protected')


@bp.route('/')
class ProtectedView(MethodView):
    @aegis_auth_required
    def get(self):
        user = g.current_user
        return {'message': f'Hello {user["email"]}', 'user_id': user['id']}
```

**Notes:**
- `g.current_user` is the dict Aegis returned. It has the standard user shape (`id`, `site_id`, `email`, `is_verified`, `role`, `created_at`, `updated_at`).
- `AegisUnauthorized` is a subclass of `AegisApiError`, so existing broad `except AegisApiError` handlers still catch it.
- The module-level `_token_cache` is per-worker. Under gunicorn with N workers you get N independent caches — fine for the 30-second TTL.

---

# User Lookup by ID (`GET /api/sites/{site_id}/users/{user_id}`)

The second pattern: backend has a `user_id` and needs to fetch the user record (typically for the `role` field). This happens when a non-Aegis credential — an internal API key, a service-issued token, a cron job's stored identity — maps to an Aegis user_id, but no Aegis bearer is present.

## Why This Endpoint Exists

Without it, a backend doing API-key-based authz had three bad options:

1. Trust the API key's stored `role` field — but then revoking/changing a user's Aegis role doesn't propagate.
2. Use `MASTER_API_KEY` to call `GET /api/sites/{site_id}/users` — overkill, and tenants must not hold the master key.
3. Force every API-key call to also carry an Aegis bearer — bad UX, often impossible (cron, server-to-server).

`GET /api/sites/{site_id}/users/{user_id}` closes the hole. Tenant-key-gated, scoped to your site, returns the standard user record.

## When to Use It

**Use this** when a backend has an Aegis `user_id` and needs the current user record (especially `role`) without a user bearer present.

Common patterns:
- API-key auth: incoming key → look up the key's `aegis_user_id` → fetch role from Aegis.
- Periodic jobs: stored user_id → check whether the user is still admin/active.

**Do not use this** as a stand-in for `/me` — if you have a bearer, use `/me`. Bearer-based lookup proves the caller *is* the user. user_id-based lookup just confirms what role a user has — anyone with the tenant key can ask about any user_id in their site.

## Caching Guidance

Identical to `/me`: short TTL (30s), keyed by `user_id`, invalidate on 401. Role changes propagate within one TTL.

## Endpoint Contract

**Request:**
```
GET /api/sites/{site_id}/users/{user_id}
X-Tenant-Api-Key: <tenant_api_key>
```

The `site_id` in the path **must match** the site the supplied tenant key belongs to. Cross-site probes (key for site A, path site B) and unknown user_ids return the same uniform 401 as missing-key — anti-enumeration.

**Response 200 — standard Aegis user shape:**
```json
{
  "id": 42,
  "site_id": 1,
  "email": "user@example.com",
  "is_verified": true,
  "role": "admin",
  "created_at": 1745280000,
  "updated_at": 1745280000
}
```

**Response 401 — uniform on every failure mode** (missing/wrong key, unknown user, cross-site probe).

---

## Flask Example (Python)

The Python client (`byteforge-aegis-client-python>=1.6.0`) has a typed wrapper. The `tenant_api_key` on `AegisClientConfig` auto-attaches the header on every call.

**Requires:** `byteforge-aegis-client-python>=1.6.0`.

```python
# lib/aegis.py — singleton tenant client (reuse across modules)
import os
from byteforge_aegis_client import AegisClient, AegisClientConfig, AegisUnauthorized

_tenant_client: AegisClient | None = None


def aegis_tenant_client() -> AegisClient:
    global _tenant_client
    if _tenant_client is None:
        _tenant_client = AegisClient(AegisClientConfig(
            api_url=os.environ['AEGIS_API_URL'],
            site_id=int(os.environ['AEGIS_SITE_ID']),
            tenant_api_key=os.environ['AEGIS_TENANT_API_KEY'],
            auto_refresh=False,
        ))
    return _tenant_client
```

```python
# decorators/api_key_auth.py — example: API-key middleware that fetches role
import time
from functools import wraps
from flask import g, jsonify, request

from byteforge_aegis_client import AegisUnauthorized
from lib.aegis import aegis_tenant_client

CACHE_TTL_SECONDS = 30
_role_cache: dict[int, tuple[str, float]] = {}


def _resolve_role(user_id: int) -> str | None:
    cached = _role_cache.get(user_id)
    if cached is not None and cached[1] > time.time():
        return cached[0]

    try:
        user = aegis_tenant_client().get_user(user_id=user_id)
    except AegisUnauthorized:
        _role_cache.pop(user_id, None)
        return None

    role = user.role.value if hasattr(user.role, 'value') else user.role
    _role_cache[user_id] = (role, time.time() + CACHE_TTL_SECONDS)
    return role


def admin_required(func):
    """Example decorator: resolves API-key → user_id (your code), then
    confirms with Aegis that the user is currently an admin."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        user_id = _your_api_key_resolver(request)  # your existing logic
        if user_id is None:
            return jsonify({'error': 'Unauthorized'}), 401

        role = _resolve_role(user_id)
        if role != 'admin':
            return jsonify({'error': 'Forbidden'}), 403

        g.current_user_id = user_id
        g.current_role = role
        return func(*args, **kwargs)

    return wrapper
```

---

## Next.js API Route Example (TypeScript)

The TS client (`byteforge-aegis-client-js>=2.11.0`) ships a typed `getUser(userId, siteId?)` method. Pair it with a tenant-key-configured singleton — the same one you'd use for any other server-side Aegis call.

**Requires:** `byteforge-aegis-client-js>=2.11.0`.

**File:** `lib/aegisUserLookup.ts`

```typescript
import { AuthClient } from 'byteforge-aegis-client-js';
import type { User } from 'byteforge-aegis-client-js';

const AEGIS_API_URL = process.env.AEGIS_API_URL!;
const AEGIS_TENANT_API_KEY = process.env.AEGIS_TENANT_API_KEY!;
const AEGIS_SITE_ID = parseInt(process.env.AEGIS_SITE_ID!, 10);
const CACHE_TTL_MS = 30_000;

interface CacheEntry {
  user: User;
  expiresAt: number;
}

let tenantClient: AuthClient | null = null;
const userCache = new Map<number, CacheEntry>();

function getTenantClient(): AuthClient {
  if (tenantClient) return tenantClient;
  tenantClient = new AuthClient({
    apiUrl: AEGIS_API_URL,
    siteId: AEGIS_SITE_ID,
    tenantApiKey: AEGIS_TENANT_API_KEY,
    autoRefresh: false,
  });
  return tenantClient;
}

export async function getAegisUser(userId: number): Promise<User | null> {
  const cached = userCache.get(userId);
  if (cached && cached.expiresAt > Date.now()) {
    return cached.user;
  }

  const result = await getTenantClient().getUser(userId);
  if (!result.success) {
    userCache.delete(userId);
    if (result.statusCode === 401) {
      return null;
    }
    throw new Error(`Aegis user lookup failed: ${result.statusCode} ${result.error}`);
  }

  userCache.set(userId, { user: result.data, expiresAt: Date.now() + CACHE_TTL_MS });
  return result.data;
}
```

**Usage in a route handler:**

```typescript
// app/api/admin/something/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { getAegisUser } from '@/lib/aegisUserLookup';
import { resolveUserIdFromApiKey } from '@/lib/yourApiKeyAuth';

export async function GET(request: NextRequest): Promise<NextResponse> {
  const userId = await resolveUserIdFromApiKey(request);
  if (userId === null) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const user = await getAegisUser(userId);
  if (user === null || user.role !== 'admin') {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
  }

  // ...admin-only logic...
  return NextResponse.json({ ok: true });
}
```

**Notes:**
- `AEGIS_TENANT_API_KEY` and `AEGIS_SITE_ID` are the same server-side env vars used by the public-auth proxy routes (see `tenant-api-key-templates.md`). One key serves both purposes.
- A 401 means *something* failed (key, user_id, or cross-site). Treat it as "this user is unknown to me," never as a hint about which specific failure occurred.
- The in-process Map is per-replica; same caveats as the `/me` cache.

---

## Placeholder Replacement Guide

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `{aegis_api_url}` | Full URL to the Aegis backend API | `https://aegis.reallybadapps.com` |

---

## Version Compatibility

### `/api/auth/me` (bearer introspection)

| Component | Minimum Version |
|-----------|----------------|
| Aegis backend (`byteforge-aegis`) | Image version 39 (commit `c96b412` or later) |
| TypeScript client (`byteforge-aegis-client-js`) | `2.8.0` |
| Python client (`byteforge-aegis-client-python`) | `1.2.0` |

If the backend is older than image version 39, `/api/auth/me` returns 404 — upgrade Aegis before rolling out middleware based on this pattern.

### `GET /api/sites/{site_id}/users/{user_id}` (user_id lookup)

| Component | Minimum Version |
|-----------|----------------|
| Aegis backend (`byteforge-aegis`) | Image with commit `4508056` or later (post-tenant-key-gate) |
| TypeScript client (`byteforge-aegis-client-js`) | `2.11.0` (typed `client.getUser(userId)`) |
| Python client (`byteforge-aegis-client-python`) | `1.6.0` (typed `client.get_user(user_id)`) |

Older backends return 404 for this path — upgrade Aegis before rolling out the user-lookup pattern.
