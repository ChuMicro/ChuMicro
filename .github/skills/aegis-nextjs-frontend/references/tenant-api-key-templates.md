# Tenant API Key Templates (Public Auth Endpoints)

This file documents the **required** backend-proxy pattern for Aegis's gated public auth endpoints. After backend image v40+, six Aegis endpoints require an `X-Tenant-Api-Key` header on every request:

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/request-password-reset`
- `POST /api/auth/reset-password`
- `POST /api/auth/verify-email`
- `POST /api/auth/check-verification-token`

> **Related — same key, different use case:** `GET /api/sites/{site_id}/users/{user_id}` is also tenant-key-gated, but it's a **server-to-server** lookup for backend authz (resolve a `user_id` to its current `role`). It is not proxied to the browser. See `backend-auth-templates.md` for that pattern.

The header is a per-tenant secret (64-char hex) issued by the Aegis admin dashboard. **It must live server-side in your Next.js deployment**, never in browser-shipped code, because the whole point of the gate is to prevent direct-to-Aegis abuse from automated callers. Browsers are public — anything in browser JS is publishable.

This means the scaffolded Next.js app must:

1. Hold `AEGIS_TENANT_API_KEY` in a server-only env var.
2. Expose `/api/frontend/auth/*` proxy routes that forward to Aegis with the header attached.
3. Have its `browserClient` call the local proxy routes instead of Aegis directly.

---

## CRITICAL — Substitution Notes

- Replace `{aegis_api_url}` with the tenant's Aegis backend URL (e.g., `https://aegis.example.com`).
- The tenant API key is per-site; each scaffolded app gets its own.
- `AEGIS_API_URL` (server-side) and `NEXT_PUBLIC_AEGIS_API_URL` (browser-side, used only for the *unprotected* `getSiteByDomain` lookup) can have the same value but the server-side one does not need to be public.

---

## 1. Environment Variables

Add to `.env.example` (server-side only, no `NEXT_PUBLIC_` prefix):

```
# Aegis backend URL (server-side only, used by proxy routes)
AEGIS_API_URL={aegis_api_url}

# Per-tenant secret for X-Tenant-Api-Key header on public auth endpoints.
# Get this from the Aegis admin dashboard. Never expose in browser code.
AEGIS_TENANT_API_KEY={paste_from_aegis_admin_dashboard}

# Your site_id from Aegis (server-side, used by proxy routes for verify-email/etc.)
AEGIS_SITE_ID={your_site_id}
```

`NEXT_PUBLIC_AEGIS_API_URL` and `NEXT_PUBLIC_SITE_DOMAIN` from the original config still apply (browser uses them for the public `getSiteByDomain` bootstrap; that endpoint is not gated).

---

## 2. Server-Side Aegis Client Helper

**File:** `lib/serverAuthClient.ts`

```typescript
import { AuthClient } from 'byteforge-aegis-client-js';

const AEGIS_API_URL = process.env.AEGIS_API_URL!;
const AEGIS_TENANT_API_KEY = process.env.AEGIS_TENANT_API_KEY!;
const AEGIS_SITE_ID = parseInt(process.env.AEGIS_SITE_ID!, 10);

/**
 * Server-side Aegis client preconfigured with the tenant API key and site ID.
 * The client auto-attaches X-Tenant-Api-Key on every request and includes
 * site_id in bodies that need it.
 */
export function getServerAuthClient(): AuthClient {
  return new AuthClient({
    apiUrl: AEGIS_API_URL,
    siteId: AEGIS_SITE_ID,
    tenantApiKey: AEGIS_TENANT_API_KEY,
    autoRefresh: false,
  });
}
```

---

## 3. Proxy Route Templates

All six routes follow the same pattern: parse body, call the server-side AuthClient, return result. The AuthClient handles the `X-Tenant-Api-Key` header injection automatically.

**Requires:** `byteforge-aegis-client-js@2.9.0` or newer.

### `app/api/frontend/auth/register/route.ts`

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerAuthClient } from '@/lib/serverAuthClient';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { email, password } = body;

    if (!email) {
      return NextResponse.json({ error: 'email is required' }, { status: 400 });
    }

    const client = getServerAuthClient();
    const result = await client.register(email, password);

    if (result.success) {
      return NextResponse.json(result.data, { status: 201 });
    }
    return NextResponse.json(
      { error: result.error },
      { status: result.statusCode || 400 },
    );
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Internal error' },
      { status: 500 },
    );
  }
}
```

### `app/api/frontend/auth/login/route.ts`

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerAuthClient } from '@/lib/serverAuthClient';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { email, password } = body;

    if (!email || !password) {
      return NextResponse.json(
        { error: 'email and password are required' },
        { status: 400 },
      );
    }

    const client = getServerAuthClient();
    const result = await client.login(email, password);

    if (result.success) {
      return NextResponse.json(result.data);
    }
    return NextResponse.json(
      { error: result.error },
      { status: result.statusCode || 401 },
    );
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Internal error' },
      { status: 500 },
    );
  }
}
```

### `app/api/frontend/auth/request-password-reset/route.ts`

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerAuthClient } from '@/lib/serverAuthClient';

export async function POST(request: NextRequest) {
  try {
    const { email } = await request.json();
    if (!email) {
      return NextResponse.json({ error: 'email is required' }, { status: 400 });
    }

    const client = getServerAuthClient();
    const result = await client.requestPasswordReset(email);

    if (result.success) {
      return NextResponse.json(result.data);
    }
    return NextResponse.json(
      { error: result.error },
      { status: result.statusCode || 400 },
    );
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Internal error' },
      { status: 500 },
    );
  }
}
```

### `app/api/frontend/auth/reset-password/route.ts`

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerAuthClient } from '@/lib/serverAuthClient';

export async function POST(request: NextRequest) {
  try {
    const { token, new_password } = await request.json();
    if (!token || !new_password) {
      return NextResponse.json(
        { error: 'token and new_password are required' },
        { status: 400 },
      );
    }

    const client = getServerAuthClient();
    const result = await client.resetPassword(token, new_password);

    if (result.success) {
      return NextResponse.json(result.data);
    }
    return NextResponse.json(
      { error: result.error },
      { status: result.statusCode || 400 },
    );
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Internal error' },
      { status: 500 },
    );
  }
}
```

### `app/api/frontend/auth/verify-email/route.ts`

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerAuthClient } from '@/lib/serverAuthClient';

export async function POST(request: NextRequest) {
  try {
    const { token, password } = await request.json();
    if (!token) {
      return NextResponse.json({ error: 'token is required' }, { status: 400 });
    }

    const client = getServerAuthClient();
    const result = await client.verifyEmail(token, password);

    if (result.success) {
      return NextResponse.json(result.data);
    }
    return NextResponse.json(
      { error: result.error },
      { status: result.statusCode || 400 },
    );
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Internal error' },
      { status: 500 },
    );
  }
}
```

### `app/api/frontend/auth/check-verification-token/route.ts`

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerAuthClient } from '@/lib/serverAuthClient';

export async function POST(request: NextRequest) {
  try {
    const { token } = await request.json();
    if (!token) {
      return NextResponse.json({ error: 'token is required' }, { status: 400 });
    }

    const client = getServerAuthClient();
    const result = await client.checkVerificationToken(token);

    if (result.success) {
      return NextResponse.json(result.data);
    }
    return NextResponse.json(
      { error: result.error },
      { status: result.statusCode || 400 },
    );
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Internal error' },
      { status: 500 },
    );
  }
}
```

---

## 4. Updated Browser Client Pattern

The browser-side `browserClient.ts` should call the local proxy routes for the six gated endpoints, **not Aegis directly**. The original singleton `AuthClient` pattern from `auth-templates.md` still works for unprotected endpoints (`getSiteByDomain`, `me`, `change-password`, `logout`, `refresh`).

**Recommended split:**

```typescript
// lib/browserClient.ts (new — proxies through backend)
async function postProxy<T>(path: string, body: unknown): Promise<{ success: true; data: T } | { success: false; error: string; statusCode: number }> {
  try {
    const response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (response.ok) {
      return { success: true, data: data as T };
    }
    return { success: false, error: data.error || 'Unknown error', statusCode: response.status };
  } catch (error) {
    return { success: false, error: error instanceof Error ? error.message : 'Network error', statusCode: 0 };
  }
}

export const browserAuthProxy = {
  register: (email: string, password?: string) =>
    postProxy('/api/frontend/auth/register', { email, password }),
  login: (email: string, password: string) =>
    postProxy('/api/frontend/auth/login', { email, password }),
  requestPasswordReset: (email: string) =>
    postProxy('/api/frontend/auth/request-password-reset', { email }),
  resetPassword: (token: string, newPassword: string) =>
    postProxy('/api/frontend/auth/reset-password', { token, new_password: newPassword }),
  verifyEmail: (token: string, password?: string) =>
    postProxy('/api/frontend/auth/verify-email', { token, password }),
  checkVerificationToken: (token: string) =>
    postProxy('/api/frontend/auth/check-verification-token', { token }),
};
```

Auth pages (`login/page.tsx`, `verify-email/page.tsx`, etc.) call `browserAuthProxy.*` instead of the singleton `AuthClient` for these six methods. The login page still uses the singleton's `setTokensFromLoginResponse` after the proxy returns the login response, so token storage works the same way.

---

## 4b. Alternative: Proxy Lives in a Sibling Backend (No Next.js API Routes)

If the project **already has a separate backend** (Flask, FastAPI, Express, etc.) that the frontend calls for non-auth business logic, host the 6 proxy endpoints there instead of in Next.js API routes. This avoids duplicating an API surface across two services. Reference implementation: `hivemake.ai` (Flask `hivemake-server` at `api.hivemake.ai`).

### When to use this variant

- The tenant has a backend that's already calling Aegis for other reasons (e.g., validating bearer tokens via `/api/auth/me`, see `backend-auth-templates.md`).
- The frontend already targets that backend for everything else; adding 6 thin proxy routes is cheaper than introducing a Next.js API layer.
- The backend can hold `AEGIS_TENANT_API_KEY` in its own env and inject it via `byteforge-aegis-client-python` or `byteforge-aegis-client-js`.

### Architecture differences

| | Skill default (Next.js routes) | Sibling-backend variant |
|---|---|---|
| Proxy host | `app/api/frontend/auth/*` in this Next.js | `/api/auth/*` in the sibling backend (e.g., `api.example.com`) |
| Tenant key holder | This Next.js's server-side env | The sibling backend's env |
| Frontend client | `browserAuthProxy` fetch shim → `/api/frontend/auth/*` | A second `AuthClient` configured with `apiUrl = <backend_url>` |
| `siteId` exposure | `AEGIS_SITE_ID` server-side | Either same, or baked as `NEXT_PUBLIC_AEGIS_SITE_ID` (site_id alone is not a secret — see note below) |

### Pattern: two AuthClients in the browser

The sibling-backend variant is cleaner because the second `AuthClient` reuses the typed Aegis interface — no fetch shim needed. The sibling backend's proxy routes mirror Aegis's API surface (`/api/auth/login` → forwards to Aegis's `/api/auth/login`).

```typescript
// lib/browserClient.ts — sibling-backend variant
import { AuthClient } from 'byteforge-aegis-client-js';

const AEGIS_API_URL = process.env.NEXT_PUBLIC_AEGIS_API_URL!;
const BACKEND_API_URL = process.env.NEXT_PUBLIC_BACKEND_API_URL!; // e.g. https://api.example.com
const SITE_ID = parseInt(process.env.NEXT_PUBLIC_AEGIS_SITE_ID!, 10);

let aegisSingleton: AuthClient | null = null;
let proxySingleton: AuthClient | null = null;

// Used for Bearer-gated calls (refresh, me, logout, confirm-email-change).
export function getAuthClient(): AuthClient {
  if (aegisSingleton) return aegisSingleton;
  aegisSingleton = new AuthClient({ apiUrl: AEGIS_API_URL, siteId: SITE_ID, autoRefresh: false });
  // ...hydrate tokens from localStorage...
  return aegisSingleton;
}

// Used for the 6 tenant-key-gated calls. Backend attaches the tenant key.
export function getProxyClient(): AuthClient {
  if (proxySingleton) return proxySingleton;
  proxySingleton = new AuthClient({ apiUrl: BACKEND_API_URL, siteId: SITE_ID, autoRefresh: false });
  return proxySingleton;
}
```

Auth pages call `getProxyClient().login(email, password)` etc. for the gated endpoints, and `getAuthClient().refreshAuthToken()` etc. for Bearer-gated ones. No `browserAuthProxy` shim, no `app/api/frontend/auth/*` routes.

### Sibling backend (Python/Flask example)

The Flask side uses the Python client's `tenant_api_key` config and exposes thin pass-throughs:

```python
# lib/aegis.py
from byteforge_aegis_client import AegisClient, AegisClientConfig

_tenant_client: AegisClient | None = None

def aegis_tenant_client() -> AegisClient:
    global _tenant_client
    if _tenant_client is None:
        _tenant_client = AegisClient(AegisClientConfig(
            api_url=os.environ['AEGIS_API_URL'],
            site_id=int(os.environ['AEGIS_SITE_ID']),
            tenant_api_key=os.environ['AEGIS_TENANT_API_KEY'],
        ))
    return _tenant_client
```

```python
# blueprints/auth.py — one route per gated Aegis endpoint
@blp.route('/api/auth/login', methods=['POST'])
def login():
    body = request.get_json()
    result = aegis_tenant_client().login(email=body['email'], password=body['password'])
    return jsonify(asdict(result)), 200
```

Other languages: the `byteforge-aegis-client-js` (`>=2.9.0`) and `byteforge-aegis-client-python` (`>=1.3.0`) packages both auto-attach `X-Tenant-Api-Key` when `tenant_api_key` is set on the config — same idea, different language.

### Gotcha: the JS AuthClient always sends `site_id` in the body

`byteforge-aegis-client-js` always includes `site_id` in the JSON body for `register`, `login`, `request_password_reset`, `reset_password`, `verify_email`, and `check_verification_token` (it pulls `siteId` from `AuthClientConfig` and adds it to the request payload). Your proxy doesn't *need* the value — the sibling backend uses its env-configured `site_id` via the tenant client — but a strict-validation framework will **reject the call with 422 "Unknown field"** if your input schema doesn't tolerate the extra field.

This bites:
- **flask-smorest / marshmallow** — default is to raise on unknown fields
- **FastAPI / pydantic** — when models are configured with `extra="forbid"`
- **Express + AJV / zod / yup** — when `additionalProperties: false` / `.strict()` is set

**Fix on the proxy side: silently drop unknown fields.**

Marshmallow:

```python
from marshmallow import EXCLUDE, Schema, fields

class _ProxyRequestSchema(Schema):
    class Meta:
        unknown = EXCLUDE  # JS client sends site_id; we ignore it.

class LoginRequestSchema(_ProxyRequestSchema):
    email = fields.Email(required=True)
    password = fields.String(required=True)
```

Pydantic:

```python
class LoginRequest(BaseModel):
    model_config = ConfigDict(extra='ignore')  # default in v2 anyway
    email: EmailStr
    password: str
```

zod / yup: use `.strip()` / non-strict mode (the default for both).

Symptom in the wild: the form-submit flow looks "stuck" — the AuthClient sees `response.ok === false` from a 422 and surfaces the marshmallow `Unknown field` error as a generic `Unknown error` to the React component, so the spinner clears with an unhelpful message. A direct `curl` probe (which doesn't include `site_id`) returns the expected 401 from Aegis, masking the real bug.

### Note on `NEXT_PUBLIC_AEGIS_SITE_ID`

Hivemake bakes `AEGIS_SITE_ID` into the client bundle as `NEXT_PUBLIC_AEGIS_SITE_ID` so the browser can construct the request body. This is **safe** — site_id alone gives a caller no auth power; the gate is the tenant key, which stays server-side. If the frontend already does `getSiteByDomain(NEXT_PUBLIC_SITE_DOMAIN)` to resolve the id at runtime, you don't need this var at all.

---

## 5. Migration Notes for Existing Scaffolds

If updating an existing scaffold from the old direct-to-Aegis pattern:

1. **Add env vars:** `AEGIS_API_URL`, `AEGIS_TENANT_API_KEY`, `AEGIS_SITE_ID` (server-side).
2. **Bump dependency:** `byteforge-aegis-client-js` to `>=2.9.0`.
3. **Add server helper:** `lib/serverAuthClient.ts` (above).
4. **Add 6 proxy routes** under `app/api/frontend/auth/*` *(or in your sibling backend — see section 4b)*.
5. **If using a sibling backend with strict input validation** (flask-smorest, FastAPI w/ `extra="forbid"`, AJV/zod with `additionalProperties: false`), make the proxy schemas tolerate unknown fields — the JS client always sends `site_id` in the body and a strict schema will 422 on it. See "Gotcha" in section 4b.
6. **Update auth pages** to call the proxy routes (via `browserAuthProxy` or equivalent) instead of `getAuthClient().login(...)` etc.
7. **Get the tenant key** from the Aegis admin dashboard (Site → Settings → Tenant API Key).
8. **Redeploy** with the env var set. The frontend will fail with 401 on every register/login/etc. call until the env var is in place.

---

## Why This Design

- **Server-side secret holding** — Browsers can't be trusted with credentials. The proxy is the only architecture where the secret can be reliably hidden.
- **Per-tenant key (not shared)** — Compromise of one tenant's key doesn't compromise others. Rotation is per-site via the admin dashboard.
- **Header-based, not body-based** — Easier to log/inspect/strip at gateways. Matches `MASTER_API_KEY` and `Authorization` patterns already in Aegis.
- **AuthClient handles header injection** — `byteforge-aegis-client-js@2.9.0+` reads `tenantApiKey` from `AuthClientConfig` and attaches `X-Tenant-Api-Key` automatically. No manual header management in proxy routes.

---

## Version Compatibility

| Component | Minimum Version |
|-----------|----------------|
| Aegis backend (`byteforge-aegis`) | image v40+ (with `tenant_api_key` migration applied) |
| TypeScript client (`byteforge-aegis-client-js`) | `2.9.0` |
| Python client (`byteforge-aegis-client-python`) | `1.3.0` |
