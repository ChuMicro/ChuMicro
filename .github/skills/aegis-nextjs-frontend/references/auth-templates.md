# Auth Utility Templates

## CRITICAL - Substitution Notes

- Replace `{aegis_api_url}` with the actual Aegis API URL for the target project (e.g., `https://aegis.example.com/api`)
- Replace `{site_domain}` with the actual site domain for the target project (e.g., `myapp.example.com`)
- The `useAuth.ts` file is identical across all projects; no substitution is needed
- `byteforge-aegis-client-js` v2.0 supports refresh tokens with auto-refresh enabled by default
- localStorage keys used: `auth_token`, `refresh_token`, `token_expires_at`, `user_id`, `site_id`, `site_name`

## Token Refresh Architecture

The `browserClient.ts` uses a **singleton AuthClient** that persists tokens in memory and syncs to localStorage on refresh. This ensures:

- Tokens are refreshed proactively (5-minute buffer before expiry)
- The `useAuth` hook checks expiry on mount and every 60 seconds
- Failed refresh (expired refresh token, network error) triggers automatic logout
- Login page uses `initAuthClientFromLogin()` to set up the singleton after successful login
- `clearAuthClient()` is the single source of truth for clearing all auth state

## Browser-vs-Backend Call Split

After Aegis backend v40+, six public auth endpoints are gated by `X-Tenant-Api-Key`. Browser code cannot call these directly; the scaffold ships a `browserAuthProxy` shim that posts to local `/api/frontend/auth/*` proxy routes (see `tenant-api-key-templates.md`).

- **Use `browserAuthProxy.*`** for: `login`, `register`, `requestPasswordReset`, `resetPassword`, `verifyEmail`, `checkVerificationToken`.
- **Use `getAuthClient()`** for: `getSiteByDomain` (public bootstrap), `me`, `changePassword`, `logout`, `refreshAuthToken`, `confirmEmailChange` (Bearer-token gated, unchanged).

---

## lib/browserClient.ts

```typescript
/**
 * Browser-side auth client using byteforge-aegis-client-js directly.
 * Uses a singleton AuthClient that persists tokens in memory and syncs to localStorage.
 */

import { AuthClient } from 'byteforge-aegis-client-js';
import type { LoginResponse, RefreshTokenResponse, ApiResponse } from 'byteforge-aegis-client-js';

const AEGIS_API_URL = process.env.NEXT_PUBLIC_AEGIS_API_URL || '{aegis_api_url}';
const SITE_DOMAIN = process.env.NEXT_PUBLIC_SITE_DOMAIN || '{site_domain}';

let singleton: AuthClient | null = null;

/**
 * Returns the singleton AuthClient, hydrating from localStorage on first call.
 */
export function getAuthClient(): AuthClient {
  if (singleton) {
    return singleton;
  }

  const siteIdStr = typeof window !== 'undefined' ? localStorage.getItem('site_id') : null;
  const siteId = siteIdStr ? parseInt(siteIdStr, 10) : undefined;

  singleton = new AuthClient({
    apiUrl: AEGIS_API_URL,
    siteId,
    autoRefresh: false,
  });

  if (typeof window !== 'undefined') {
    const authToken = localStorage.getItem('auth_token');
    const refreshToken = localStorage.getItem('refresh_token');

    if (authToken) {
      singleton.setAuthToken(authToken);
    }
    if (refreshToken) {
      singleton.setRefreshToken(refreshToken);
    }
  }

  return singleton;
}

/**
 * Called after login succeeds. Sets tokens on the singleton and stores everything in localStorage.
 */
export function initAuthClientFromLogin(loginResponse: LoginResponse, siteId: number, siteName: string): void {
  localStorage.setItem('auth_token', loginResponse.auth_token.token);
  localStorage.setItem('refresh_token', loginResponse.refresh_token.token);
  localStorage.setItem('token_expires_at', loginResponse.auth_token.expires_at.toString());
  localStorage.setItem('user_id', loginResponse.auth_token.user_id.toString());
  localStorage.setItem('site_id', siteId.toString());
  localStorage.setItem('site_name', siteName);

  // Reset singleton so it picks up the new siteId and tokens
  singleton = new AuthClient({
    apiUrl: AEGIS_API_URL,
    siteId,
    autoRefresh: false,
  });
  singleton.setTokensFromLoginResponse(loginResponse);
}

interface RefreshResult {
  success: boolean;
  expiresAt?: number;
}

/**
 * Calls refreshAuthToken() on the singleton, updates localStorage on success.
 */
export async function refreshAuthTokens(): Promise<RefreshResult> {
  const client = getAuthClient();
  const result: ApiResponse<RefreshTokenResponse> = await client.refreshAuthToken();

  if (!result.success) {
    return { success: false };
  }

  const { auth_token, refresh_token } = result.data;

  localStorage.setItem('auth_token', auth_token.token);
  localStorage.setItem('token_expires_at', auth_token.expires_at.toString());
  client.setAuthToken(auth_token.token);

  if (refresh_token) {
    localStorage.setItem('refresh_token', refresh_token.token);
    client.setRefreshToken(refresh_token.token);
  }

  return { success: true, expiresAt: auth_token.expires_at };
}

/**
 * Returns true if the auth token is expired or expiring within the buffer window.
 */
export function isTokenExpired(bufferSeconds: number = 300): boolean {
  const expiresAtStr = localStorage.getItem('token_expires_at');
  if (!expiresAtStr) {
    return true;
  }

  const expiresAt = parseInt(expiresAtStr, 10);
  const nowSeconds = Math.floor(Date.now() / 1000);
  return nowSeconds >= (expiresAt - bufferSeconds);
}

/**
 * Clears the singleton tokens and all auth-related localStorage keys.
 */
export function clearAuthClient(): void {
  if (singleton) {
    singleton.clearAllTokens();
  }
  singleton = null;

  localStorage.removeItem('auth_token');
  localStorage.removeItem('refresh_token');
  localStorage.removeItem('token_expires_at');
  localStorage.removeItem('user_id');
  localStorage.removeItem('site_id');
  localStorage.removeItem('site_name');
}

export function getSiteDomain(): string {
  return SITE_DOMAIN;
}

/**
 * Proxy shim for the six gated public auth endpoints. After Aegis backend v40+
 * these endpoints require an X-Tenant-Api-Key header that must live server-side
 * (see references/tenant-api-key-templates.md). The browser calls our local
 * /api/frontend/auth/* routes; the server attaches the header and forwards to
 * Aegis. Auth pages should call browserAuthProxy.* for these methods, not the
 * singleton AuthClient.
 */
type ProxyResult<T> =
  | { success: true; data: T }
  | { success: false; error: string; statusCode: number };

async function postProxy<T>(path: string, body: unknown): Promise<ProxyResult<T>> {
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
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Network error',
      statusCode: 0,
    };
  }
}

export const browserAuthProxy = {
  register: (email: string, password?: string) =>
    postProxy('/api/frontend/auth/register', { email, password }),
  login: (email: string, password: string) =>
    postProxy<LoginResponse>('/api/frontend/auth/login', { email, password }),
  requestPasswordReset: (email: string) =>
    postProxy('/api/frontend/auth/request-password-reset', { email }),
  resetPassword: (token: string, newPassword: string) =>
    postProxy('/api/frontend/auth/reset-password', { token, new_password: newPassword }),
  verifyEmail: (token: string, password?: string) =>
    postProxy('/api/frontend/auth/verify-email', { token, password }),
  checkVerificationToken: (token: string) =>
    postProxy<{ password_required: boolean; email: string }>(
      '/api/frontend/auth/check-verification-token',
      { token },
    ),
};

export { AuthClient };
export type { LoginResponse };
```

---

## lib/useAuth.ts

```typescript
'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { clearAuthClient, isTokenExpired, refreshAuthTokens } from './browserClient';

const REFRESH_CHECK_INTERVAL_MS = 60_000;

interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  userId: string | null;
  siteId: string | null;
  siteName: string | null;
  token: string | null;
  refreshToken: string | null;
  tokenExpiresAt: number | null;
}

export function useAuth(): AuthState {
  const [state, setState] = useState<AuthState>({
    isAuthenticated: false,
    isLoading: true,
    userId: null,
    siteId: null,
    siteName: null,
    token: null,
    refreshToken: null,
    tokenExpiresAt: null,
  });

  const isRefreshing = useRef(false);

  const attemptRefresh = useCallback(async (): Promise<boolean> => {
    if (isRefreshing.current) {
      return false;
    }

    isRefreshing.current = true;
    try {
      const result = await refreshAuthTokens();
      if (result.success && result.expiresAt) {
        const newToken = localStorage.getItem('auth_token');
        const newRefreshToken = localStorage.getItem('refresh_token');
        setState((prev) => ({
          ...prev,
          token: newToken,
          refreshToken: newRefreshToken,
          tokenExpiresAt: result.expiresAt ?? null,
        }));
        return true;
      }
      return false;
    } catch {
      return false;
    } finally {
      isRefreshing.current = false;
    }
  }, []);

  useEffect(() => {
    const token = localStorage.getItem('auth_token');
    const refreshTokenVal = localStorage.getItem('refresh_token');
    const tokenExpiresAtStr = localStorage.getItem('token_expires_at');
    const userId = localStorage.getItem('user_id');
    const siteId = localStorage.getItem('site_id');
    const siteName = localStorage.getItem('site_name');

    if (!token) {
      setState({
        isAuthenticated: false,
        isLoading: false,
        userId,
        siteId,
        siteName,
        token: null,
        refreshToken: null,
        tokenExpiresAt: null,
      });
      return;
    }

    setState({
      isAuthenticated: true,
      isLoading: false,
      userId,
      siteId,
      siteName,
      token,
      refreshToken: refreshTokenVal,
      tokenExpiresAt: tokenExpiresAtStr ? parseInt(tokenExpiresAtStr, 10) : null,
    });

    // If token is expired or expiring soon, attempt refresh immediately
    if (isTokenExpired()) {
      attemptRefresh().then((success) => {
        if (!success) {
          logout();
        }
      });
    }
  }, [attemptRefresh]);

  // Periodic refresh check
  useEffect(() => {
    if (!state.isAuthenticated) {
      return;
    }

    const intervalId = setInterval(() => {
      if (isTokenExpired()) {
        attemptRefresh().then((success) => {
          if (!success) {
            logout();
          }
        });
      }
    }, REFRESH_CHECK_INTERVAL_MS);

    return () => clearInterval(intervalId);
  }, [state.isAuthenticated, attemptRefresh]);

  return state;
}

export function logout(): void {
  clearAuthClient();
  window.location.href = '/';
}
```

### Note on clearNoteForgeApiKey

If your project has additional API clients that cache tokens (e.g., a `noteforgeClient.ts` with `clearNoteForgeApiKey()`), import and call that in `logout()` as well:

```typescript
import { clearNoteForgeApiKey } from './noteforgeClient';

export function logout(): void {
  clearAuthClient();
  clearNoteForgeApiKey();
  window.location.href = '/';
}
```
