# Auth Page Templates for Aegis Next.js Frontend

## CRITICAL - Placeholder Replacement

Every auth page that displays a branded footer uses a `{ProjectBrandHtml}` placeholder. When scaffolding a new project, you **MUST** replace this placeholder with the project's actual branded HTML. The pattern is:

```tsx
<span className="font-display">
  <span className="text-[var(--foreground)]">{BrandPart1}</span>
  <span className="text-[var(--amber-glow)]">{BrandPart2}</span>
</span>
```

For example, if the project name is "NoteForge":
```tsx
<span className="font-display">
  <span className="text-[var(--foreground)]">Note</span>
  <span className="text-[var(--amber-glow)]">Forge</span>
</span>
```

Or if the project name is "DevNotes":
```tsx
<span className="font-display">
  <span className="text-[var(--foreground)]">Dev</span>
  <span className="text-[var(--amber-glow)]">Notes</span>
</span>
```

Split the project name at a natural boundary: the first word or prefix in `--foreground` color, the second word or suffix in `--amber-glow` color.

**Pages that use `{ProjectBrandHtml}`**: login, verify-email, forgot-password, reset-password, welcome

**Pages that do NOT use `{ProjectBrandHtml}`**: confirm-email-change (no branded footer)

---

## 1. app/[locale]/login/page.tsx

Login form with email/password. Looks up the site via `getSiteDomain()` and `getAuthClient().getSiteByDomain()` (the public lookup is not gated). Calls `browserAuthProxy.login()` which proxies to `/api/frontend/auth/login` (server attaches the tenant API key). On success, calls `initAuthClientFromLogin()` to store tokens in localStorage and initialize the singleton AuthClient, then redirects to `/dashboard`. Includes forgot password link. Uses Suspense wrapper.

Status states: `idle`, `loading`, `success`, `error`.

```tsx
'use client';

import { Suspense, useEffect, useState, FormEvent } from 'react';
import { useTranslations } from 'next-intl';
import { useRouter } from '@/i18n/navigation';
import { Link } from '@/i18n/navigation';
import { browserAuthProxy, getAuthClient, getSiteDomain, initAuthClientFromLogin } from '@/lib/browserClient';

interface Site {
  id: number;
  name: string;
  domain: string;
}

type LoginStatus = 'idle' | 'loading' | 'success' | 'error';

function LoadingDots() {
  return (
    <span className="inline-flex gap-1">
      <span className="w-1.5 h-1.5 bg-current rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
      <span className="w-1.5 h-1.5 bg-current rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
      <span className="w-1.5 h-1.5 bg-current rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
    </span>
  );
}

function LoginContent() {
  const router = useRouter();
  const t = useTranslations('Login');
  const tCommon = useTranslations('Common');
  const [site, setSite] = useState<Site | null>(null);
  const [siteError, setSiteError] = useState<string | null>(null);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState<LoginStatus>('idle');
  const [message, setMessage] = useState('');

  useEffect(() => {
    const fetchSite = async () => {
      const siteDomain = getSiteDomain();
      const client = getAuthClient();
      const result = await client.getSiteByDomain(siteDomain);

      if (result.success && result.data) {
        setSite(result.data as Site);
      } else if (!result.success) {
        setSiteError(result.error || t('siteNotFound'));
      }
    };

    fetchSite();
  }, [t]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();

    if (!site) return;

    setStatus('loading');
    setMessage(t('signingIn'));

    const result = await browserAuthProxy.login(email, password);

    if (result.success && result.data) {
      initAuthClientFromLogin(result.data, site.id, site.name);

      setStatus('success');
      setMessage(t('accessGranted'));

      setTimeout(() => {
        router.push('/dashboard');
      }, 500);
    } else if (!result.success) {
      setStatus('error');
      setMessage(result.error || t('authenticationFailed'));
    }
  };

  // Error state
  if (siteError) {
    return (
      <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
        <div className="relative z-10 w-full max-w-md">
          <div className="card p-8 animate-scale-in">
            <div className="text-center">
              {/* Error icon */}
              <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-[var(--error-red)]/10 flex items-center justify-center">
                <svg className="w-8 h-8 text-[var(--error-red)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>

              <h2 className="font-display text-2xl font-bold mb-3 text-[var(--error-red)]">
                {t('accessDenied')}
              </h2>
              <p className="text-[var(--foreground-muted)] mb-6">{siteError}</p>

              <Link href="/" className="btn-secondary inline-flex">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                </svg>
                {tCommon('backToHome')}
              </Link>
            </div>
          </div>
        </div>
      </main>
    );
  }

  // Loading state
  if (!site) {
    return (
      <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
        <div className="relative z-10 text-center animate-fade-in">
          <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-[var(--amber-glow)]/10 flex items-center justify-center">
            <div className="spinner border-[var(--amber-glow)] border-t-transparent" />
          </div>
          <p className="text-[var(--foreground-muted)] font-medium">
            {t('initializingConnection')}
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
      <div className="relative z-10 w-full max-w-md">
        {/* Back link */}
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-[var(--foreground-muted)] hover:text-[var(--foreground)] transition-colors mb-8 animate-fade-in"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          <span className="text-sm font-medium">{tCommon('back')}</span>
        </Link>

        {/* Login card */}
        <div className="card p-8 md:p-10 animate-scale-in delay-100">
          {/* Header */}
          <div className="text-center mb-8">
            <h1 className="font-display text-2xl md:text-3xl font-bold mb-2">
              {t('title')}
            </h1>
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-[var(--amber-glow)]/10 text-[var(--amber-glow)]">
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9" />
              </svg>
              <span className="text-sm font-semibold">{site.name}</span>
            </div>
          </div>

          {/* Status message */}
          {status !== 'idle' && status !== 'loading' && (
            <div className={`mb-6 text-center animate-fade-in ${
              status === 'success' ? 'status-success' : 'status-error'
            }`}>
              <div className="flex items-center justify-center gap-2">
                {status === 'success' ? (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                ) : (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                )}
                {message}
              </div>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="animate-fade-in-up delay-200">
              <label htmlFor="email" className="block text-sm font-semibold mb-2 text-[var(--foreground)]">
                {t('emailLabel')}
              </label>
              <input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input-field"
                placeholder={t('emailPlaceholder')}
                disabled={status === 'loading' || status === 'success'}
                autoComplete="email"
              />
            </div>

            <div className="animate-fade-in-up delay-300">
              <div className="flex items-center justify-between mb-2">
                <label htmlFor="password" className="block text-sm font-semibold text-[var(--foreground)]">
                  {t('passwordLabel')}
                </label>
                <Link
                  href="/forgot-password"
                  className="text-sm text-[var(--amber-glow)] hover:text-[var(--amber-glow)]/80 transition-colors"
                >
                  {t('forgotPassword')}
                </Link>
              </div>
              <input
                id="password"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input-field"
                placeholder={t('passwordPlaceholder')}
                disabled={status === 'loading' || status === 'success'}
                autoComplete="current-password"
              />
            </div>

            <div className="pt-2 animate-fade-in-up delay-400">
              <button
                type="submit"
                disabled={status === 'loading' || status === 'success'}
                className="btn-primary"
              >
                {status === 'loading' ? (
                  <>
                    <div className="spinner" />
                    {t('signingIn')}
                  </>
                ) : status === 'success' ? (
                  <>
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                    {t('accessGranted')}
                  </>
                ) : (
                  <>
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1" />
                    </svg>
                    {t('signInButton')}
                  </>
                )}
              </button>
            </div>
          </form>
        </div>

        {/* Footer text */}
        <p className="text-center text-sm text-[var(--foreground-muted)] mt-8 animate-fade-in delay-500">
          {ProjectBrandHtml}
          {' '}&middot; {tCommon('secureAuthentication')}
        </p>
      </div>
    </main>
  );
}

export default function LoginPage() {
  const t = useTranslations('Common');

  return (
    <Suspense fallback={
      <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
        <div className="relative z-10 text-center animate-fade-in">
          <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-[var(--amber-glow)]/10 flex items-center justify-center">
            <div className="spinner border-[var(--amber-glow)] border-t-transparent" />
          </div>
          <p className="text-[var(--foreground-muted)] font-medium">{t('loading')}</p>
        </div>
      </main>
    }>
      <LoginContent />
    </Suspense>
  );
}
```

---

## 2. app/[locale]/verify-email/page.tsx

Email verification page. Reads `?token=` from URL. Calls `browserAuthProxy.checkVerificationToken(token)` (proxies to `/api/frontend/auth/check-verification-token`) to determine if a password is required. If password is required, shows password + confirm password form. If not, shows a simple verify button. On success, calls `browserAuthProxy.verifyEmail(token, password?)` and redirects to `/login`. Uses Suspense wrapper.

Status states: `checking`, `idle`, `loading`, `success`, `error`.

```tsx
'use client';

import { Suspense, useEffect, useState, FormEvent } from 'react';
import { useTranslations } from 'next-intl';
import { useRouter, Link } from '@/i18n/navigation';
import { useSearchParams } from 'next/navigation';
import { browserAuthProxy } from '@/lib/browserClient';

type VerifyStatus = 'checking' | 'idle' | 'loading' | 'success' | 'error';

interface TokenInfo {
  passwordRequired: boolean;
  email: string;
}

function VerifyContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const t = useTranslations('Verify');
  const tCommon = useTranslations('Common');

  const [status, setStatus] = useState<VerifyStatus>('checking');
  const [message, setMessage] = useState('');
  const [tokenInfo, setTokenInfo] = useState<TokenInfo | null>(null);
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [validationError, setValidationError] = useState('');

  const token = searchParams.get('token');

  useEffect(() => {
    if (!token) {
      setStatus('error');
      setMessage(t('invalidToken'));
      return;
    }

    const checkToken = async () => {
      const result = await browserAuthProxy.checkVerificationToken(token);

      if (result.success && result.data) {
        setTokenInfo({
          passwordRequired: result.data.password_required,
          email: result.data.email,
        });
        setStatus('idle');
      } else if (!result.success) {
        setStatus('error');
        setMessage(result.error || t('invalidToken'));
      }
    };

    checkToken();
  }, [token, t]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setValidationError('');

    if (!token) return;

    if (tokenInfo?.passwordRequired) {
      if (password !== confirmPassword) {
        setValidationError(t('passwordsDoNotMatch'));
        return;
      }
    }

    setStatus('loading');
    setMessage(t('verifying'));

    const passwordToSend = tokenInfo?.passwordRequired ? password : undefined;
    const result = await browserAuthProxy.verifyEmail(token, passwordToSend);

    if (result.success && result.data) {
      setStatus('success');
      setMessage(t('verificationSuccess'));

      setTimeout(() => {
        router.push('/login');
      }, 1500);
    } else if (!result.success) {
      setStatus('error');
      setMessage(result.error || t('verificationFailed'));
    }
  };

  // Checking token state
  if (status === 'checking') {
    return (
      <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
        <div className="relative z-10 text-center animate-fade-in">
          <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-[var(--amber-glow)]/10 flex items-center justify-center">
            <div className="spinner border-[var(--amber-glow)] border-t-transparent" />
          </div>
          <p className="text-[var(--foreground-muted)] font-medium">
            {t('checkingToken')}
          </p>
        </div>
      </main>
    );
  }

  // Error state (invalid/expired token)
  if (status === 'error' && !tokenInfo) {
    return (
      <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
        <div className="relative z-10 w-full max-w-md">
          <div className="card p-8 animate-scale-in">
            <div className="text-center">
              <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-[var(--error-red)]/10 flex items-center justify-center">
                <svg className="w-8 h-8 text-[var(--error-red)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>

              <h2 className="font-display text-2xl font-bold mb-3 text-[var(--error-red)]">
                {t('verificationFailed')}
              </h2>
              <p className="text-[var(--foreground-muted)] mb-6">{message}</p>

              <Link href="/login" className="btn-secondary inline-flex">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                </svg>
                {t('backToLogin')}
              </Link>
            </div>
          </div>
        </div>
      </main>
    );
  }

  // Success state
  if (status === 'success') {
    return (
      <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
        <div className="relative z-10 w-full max-w-md">
          <div className="card p-8 animate-scale-in">
            <div className="text-center">
              <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-[var(--success-green)]/10 flex items-center justify-center">
                <svg className="w-8 h-8 text-[var(--success-green)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              </div>

              <h2 className="font-display text-2xl font-bold mb-3 text-[var(--success-green)]">
                {t('verificationSuccess')}
              </h2>
              <p className="text-[var(--foreground-muted)]">{t('redirectingToLogin')}</p>

              <div className="mt-4 flex justify-center">
                <div className="spinner border-[var(--amber-glow)] border-t-transparent" />
              </div>
            </div>
          </div>
        </div>
      </main>
    );
  }

  // Form state (idle or loading with tokenInfo)
  return (
    <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
      <div className="relative z-10 w-full max-w-md">
        <Link
          href="/login"
          className="inline-flex items-center gap-2 text-[var(--foreground-muted)] hover:text-[var(--foreground)] transition-colors mb-8 animate-fade-in"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          <span className="text-sm font-medium">{t('backToLogin')}</span>
        </Link>

        <div className="card p-8 md:p-10 animate-scale-in delay-100">
          {/* Header */}
          <div className="text-center mb-8">
            <h1 className="font-display text-2xl md:text-3xl font-bold mb-2">
              {tokenInfo?.passwordRequired ? t('titleSetPassword') : t('title')}
            </h1>
            {tokenInfo?.email && (
              <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-[var(--amber-glow)]/10 text-[var(--amber-glow)]">
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
                <span className="text-sm font-semibold">{tokenInfo.email}</span>
              </div>
            )}
          </div>

          {/* Status/Error message */}
          {(status === 'error' || validationError) && (
            <div className="mb-6 text-center animate-fade-in status-error">
              <div className="flex items-center justify-center gap-2">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
                {validationError || message}
              </div>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-5">
            {tokenInfo?.passwordRequired && (
              <>
                <div className="animate-fade-in-up delay-200">
                  <label htmlFor="password" className="block text-sm font-semibold mb-2 text-[var(--foreground)]">
                    {t('passwordLabel')}
                  </label>
                  <input
                    id="password"
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="input-field"
                    placeholder={t('passwordPlaceholder')}
                    disabled={status === 'loading'}
                    autoComplete="new-password"
                  />
                </div>

                <div className="animate-fade-in-up delay-300">
                  <label htmlFor="confirmPassword" className="block text-sm font-semibold mb-2 text-[var(--foreground)]">
                    {t('confirmPasswordLabel')}
                  </label>
                  <input
                    id="confirmPassword"
                    type="password"
                    required
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="input-field"
                    placeholder={t('confirmPasswordPlaceholder')}
                    disabled={status === 'loading'}
                    autoComplete="new-password"
                  />
                </div>
              </>
            )}

            <div className="pt-2 animate-fade-in-up delay-400">
              <button
                type="submit"
                disabled={status === 'loading'}
                className="btn-primary"
              >
                {status === 'loading' ? (
                  <>
                    <div className="spinner" />
                    {t('verifying')}
                  </>
                ) : (
                  <>
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                    {tokenInfo?.passwordRequired ? t('setPasswordButton') : t('verifyButton')}
                  </>
                )}
              </button>
            </div>
          </form>
        </div>

        {/* Footer text */}
        <p className="text-center text-sm text-[var(--foreground-muted)] mt-8 animate-fade-in delay-500">
          {ProjectBrandHtml}
          {' '}&middot; {tCommon('secureVerification')}
        </p>
      </div>
    </main>
  );
}

export default function VerifyPage() {
  const t = useTranslations('Common');

  return (
    <Suspense fallback={
      <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
        <div className="relative z-10 text-center animate-fade-in">
          <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-[var(--amber-glow)]/10 flex items-center justify-center">
            <div className="spinner border-[var(--amber-glow)] border-t-transparent" />
          </div>
          <p className="text-[var(--foreground-muted)] font-medium">{t('loading')}</p>
        </div>
      </main>
    }>
      <VerifyContent />
    </Suspense>
  );
}
```

---

## 3. app/[locale]/forgot-password/page.tsx

Forgot password page. Looks up the site via `getSiteDomain()` and `getAuthClient().getSiteByDomain()` (the public lookup is not gated). Calls `browserAuthProxy.requestPasswordReset(email)` which proxies to `/api/frontend/auth/request-password-reset` (server attaches the tenant API key and supplies `site_id` from env). Always shows success message regardless of whether the email exists (security best practice). Uses Suspense wrapper.

Status states: `idle`, `loading`, `success`, `error`.

```tsx
'use client';

import { Suspense, useEffect, useState, FormEvent } from 'react';
import { useTranslations } from 'next-intl';
import { Link } from '@/i18n/navigation';
import { browserAuthProxy, getAuthClient, getSiteDomain } from '@/lib/browserClient';

interface Site {
  id: number;
  name: string;
  domain: string;
}

type ForgotPasswordStatus = 'idle' | 'loading' | 'success' | 'error';

function ForgotPasswordContent() {
  const t = useTranslations('ForgotPassword');
  const tLogin = useTranslations('Login');
  const tCommon = useTranslations('Common');

  const [site, setSite] = useState<Site | null>(null);
  const [siteError, setSiteError] = useState<string | null>(null);
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState<ForgotPasswordStatus>('idle');
  const [message, setMessage] = useState('');

  useEffect(() => {
    const fetchSite = async () => {
      const siteDomain = getSiteDomain();
      const client = getAuthClient();
      const result = await client.getSiteByDomain(siteDomain);

      if (result.success && result.data) {
        setSite(result.data as Site);
      } else if (!result.success) {
        setSiteError(result.error || tLogin('siteNotFound'));
      }
    };

    fetchSite();
  }, [tLogin]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();

    if (!site) return;

    setStatus('loading');
    setMessage(t('sending'));

    const result = await browserAuthProxy.requestPasswordReset(email);

    // Always show success for security (don't reveal if email exists)
    if (result.success) {
      setStatus('success');
    } else {
      // Still show success message for security
      setStatus('success');
    }
  };

  // Error state
  if (siteError) {
    return (
      <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
        <div className="relative z-10 w-full max-w-md">
          <div className="card p-8 animate-scale-in">
            <div className="text-center">
              <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-[var(--error-red)]/10 flex items-center justify-center">
                <svg className="w-8 h-8 text-[var(--error-red)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>

              <h2 className="font-display text-2xl font-bold mb-3 text-[var(--error-red)]">
                {tLogin('accessDenied')}
              </h2>
              <p className="text-[var(--foreground-muted)] mb-6">{siteError}</p>

              <Link href="/" className="btn-secondary inline-flex">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                </svg>
                {tCommon('backToHome')}
              </Link>
            </div>
          </div>
        </div>
      </main>
    );
  }

  // Loading state (fetching site)
  if (!site) {
    return (
      <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
        <div className="relative z-10 text-center animate-fade-in">
          <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-[var(--amber-glow)]/10 flex items-center justify-center">
            <div className="spinner border-[var(--amber-glow)] border-t-transparent" />
          </div>
          <p className="text-[var(--foreground-muted)] font-medium">
            {tLogin('initializingConnection')}
          </p>
        </div>
      </main>
    );
  }

  // Success state
  if (status === 'success') {
    return (
      <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
        <div className="relative z-10 w-full max-w-md">
          <div className="card p-8 animate-scale-in">
            <div className="text-center">
              <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-[var(--success-green)]/10 flex items-center justify-center">
                <svg className="w-8 h-8 text-[var(--success-green)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
              </div>

              <h2 className="font-display text-2xl font-bold mb-3 text-[var(--success-green)]">
                {t('successTitle')}
              </h2>
              <p className="text-[var(--foreground-muted)] mb-6">{t('successMessage')}</p>

              <Link href="/login" className="btn-primary inline-flex">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                </svg>
                {t('backToLogin')}
              </Link>
            </div>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
      <div className="relative z-10 w-full max-w-md">
        {/* Back link */}
        <Link
          href="/login"
          className="inline-flex items-center gap-2 text-[var(--foreground-muted)] hover:text-[var(--foreground)] transition-colors mb-8 animate-fade-in"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          <span className="text-sm font-medium">{t('backToLogin')}</span>
        </Link>

        {/* Forgot password card */}
        <div className="card p-8 md:p-10 animate-scale-in delay-100">
          {/* Header */}
          <div className="text-center mb-8">
            <h1 className="font-display text-2xl md:text-3xl font-bold mb-2">
              {t('title')}
            </h1>
            <p className="text-[var(--foreground-muted)]">
              {t('subtitle')}
            </p>
          </div>

          {/* Status message */}
          {status === 'error' && (
            <div className="mb-6 text-center animate-fade-in status-error">
              <div className="flex items-center justify-center gap-2">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
                {message}
              </div>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="animate-fade-in-up delay-200">
              <label htmlFor="email" className="block text-sm font-semibold mb-2 text-[var(--foreground)]">
                {t('emailLabel')}
              </label>
              <input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input-field"
                placeholder={t('emailPlaceholder')}
                disabled={status === 'loading'}
                autoComplete="email"
              />
            </div>

            <div className="pt-2 animate-fade-in-up delay-300">
              <button
                type="submit"
                disabled={status === 'loading'}
                className="btn-primary"
              >
                {status === 'loading' ? (
                  <>
                    <div className="spinner" />
                    {t('sending')}
                  </>
                ) : (
                  <>
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                    </svg>
                    {t('sendResetLink')}
                  </>
                )}
              </button>
            </div>
          </form>
        </div>

        {/* Footer text */}
        <p className="text-center text-sm text-[var(--foreground-muted)] mt-8 animate-fade-in delay-400">
          {ProjectBrandHtml}
          {' '}&middot; {tCommon('secureAuthentication')}
        </p>
      </div>
    </main>
  );
}

export default function ForgotPasswordPage() {
  const t = useTranslations('Common');

  return (
    <Suspense fallback={
      <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
        <div className="relative z-10 text-center animate-fade-in">
          <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-[var(--amber-glow)]/10 flex items-center justify-center">
            <div className="spinner border-[var(--amber-glow)] border-t-transparent" />
          </div>
          <p className="text-[var(--foreground-muted)] font-medium">{t('loading')}</p>
        </div>
      </main>
    }>
      <ForgotPasswordContent />
    </Suspense>
  );
}
```

---

## 4. app/[locale]/reset-password/page.tsx

Reset password page. Reads `?token=` from URL. Shows new password + confirm password form. Calls `browserAuthProxy.resetPassword(token, password)` which proxies to `/api/frontend/auth/reset-password` (server attaches the tenant API key and supplies `site_id` from env). On success, redirects to `/login`. Uses Suspense wrapper.

Status states: `idle`, `loading`, `success`, `error`.

```tsx
'use client';

import { Suspense, useState, FormEvent } from 'react';
import { useTranslations } from 'next-intl';
import { useRouter, Link } from '@/i18n/navigation';
import { useSearchParams } from 'next/navigation';
import { browserAuthProxy } from '@/lib/browserClient';

type ResetPasswordStatus = 'idle' | 'loading' | 'success' | 'error';

function ResetPasswordContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const t = useTranslations('ResetPassword');
  const tCommon = useTranslations('Common');

  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [status, setStatus] = useState<ResetPasswordStatus>('idle');
  const [message, setMessage] = useState('');
  const [validationError, setValidationError] = useState('');

  const token = searchParams.get('token');

  // No token provided
  if (!token) {
    return (
      <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
        <div className="relative z-10 w-full max-w-md">
          <div className="card p-8 animate-scale-in">
            <div className="text-center">
              <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-[var(--error-red)]/10 flex items-center justify-center">
                <svg className="w-8 h-8 text-[var(--error-red)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>

              <h2 className="font-display text-2xl font-bold mb-3 text-[var(--error-red)]">
                {t('resetFailed')}
              </h2>
              <p className="text-[var(--foreground-muted)] mb-6">{t('invalidToken')}</p>

              <Link href="/login" className="btn-secondary inline-flex">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                </svg>
                {t('backToLogin')}
              </Link>
            </div>
          </div>
        </div>
      </main>
    );
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setValidationError('');

    if (password !== confirmPassword) {
      setValidationError(t('passwordsDoNotMatch'));
      return;
    }

    setStatus('loading');
    setMessage(t('resetting'));

    const result = await browserAuthProxy.resetPassword(token, password);

    if (result.success && result.data) {
      setStatus('success');
      setMessage(t('successMessage'));

      setTimeout(() => {
        router.push('/login');
      }, 1500);
    } else if (!result.success) {
      setStatus('error');
      setMessage(result.error || t('resetFailed'));
    }
  };

  // Success state
  if (status === 'success') {
    return (
      <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
        <div className="relative z-10 w-full max-w-md">
          <div className="card p-8 animate-scale-in">
            <div className="text-center">
              <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-[var(--success-green)]/10 flex items-center justify-center">
                <svg className="w-8 h-8 text-[var(--success-green)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              </div>

              <h2 className="font-display text-2xl font-bold mb-3 text-[var(--success-green)]">
                {t('successTitle')}
              </h2>
              <p className="text-[var(--foreground-muted)]">{t('redirectingToLogin')}</p>

              <div className="mt-4 flex justify-center">
                <div className="spinner border-[var(--amber-glow)] border-t-transparent" />
              </div>
            </div>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
      <div className="relative z-10 w-full max-w-md">
        {/* Back link */}
        <Link
          href="/login"
          className="inline-flex items-center gap-2 text-[var(--foreground-muted)] hover:text-[var(--foreground)] transition-colors mb-8 animate-fade-in"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          <span className="text-sm font-medium">{t('backToLogin')}</span>
        </Link>

        {/* Reset password card */}
        <div className="card p-8 md:p-10 animate-scale-in delay-100">
          {/* Header */}
          <div className="text-center mb-8">
            <h1 className="font-display text-2xl md:text-3xl font-bold mb-2">
              {t('title')}
            </h1>
            <p className="text-[var(--foreground-muted)]">
              {t('subtitle')}
            </p>
          </div>

          {/* Status/Error message */}
          {(status === 'error' || validationError) && (
            <div className="mb-6 text-center animate-fade-in status-error">
              <div className="flex items-center justify-center gap-2">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
                {validationError || message}
              </div>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="animate-fade-in-up delay-200">
              <label htmlFor="password" className="block text-sm font-semibold mb-2 text-[var(--foreground)]">
                {t('passwordLabel')}
              </label>
              <input
                id="password"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input-field"
                placeholder={t('passwordPlaceholder')}
                disabled={status === 'loading'}
                autoComplete="new-password"
              />
            </div>

            <div className="animate-fade-in-up delay-300">
              <label htmlFor="confirmPassword" className="block text-sm font-semibold mb-2 text-[var(--foreground)]">
                {t('confirmPasswordLabel')}
              </label>
              <input
                id="confirmPassword"
                type="password"
                required
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="input-field"
                placeholder={t('confirmPasswordPlaceholder')}
                disabled={status === 'loading'}
                autoComplete="new-password"
              />
            </div>

            <div className="pt-2 animate-fade-in-up delay-400">
              <button
                type="submit"
                disabled={status === 'loading'}
                className="btn-primary"
              >
                {status === 'loading' ? (
                  <>
                    <div className="spinner" />
                    {t('resetting')}
                  </>
                ) : (
                  <>
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                    </svg>
                    {t('resetButton')}
                  </>
                )}
              </button>
            </div>
          </form>
        </div>

        {/* Footer text */}
        <p className="text-center text-sm text-[var(--foreground-muted)] mt-8 animate-fade-in delay-500">
          {ProjectBrandHtml}
          {' '}&middot; {tCommon('secureAuthentication')}
        </p>
      </div>
    </main>
  );
}

export default function ResetPasswordPage() {
  const t = useTranslations('Common');

  return (
    <Suspense fallback={
      <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
        <div className="relative z-10 text-center animate-fade-in">
          <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-[var(--amber-glow)]/10 flex items-center justify-center">
            <div className="spinner border-[var(--amber-glow)] border-t-transparent" />
          </div>
          <p className="text-[var(--foreground-muted)] font-medium">{t('loading')}</p>
        </div>
      </main>
    }>
      <ResetPasswordContent />
    </Suspense>
  );
}
```

---

## 5. app/[locale]/confirm-email-change/page.tsx

Email change confirmation page. Reads `?token=` from URL. Auto-confirms on load via `getAuthClient().confirmEmailChange(token)`. On success, auto-redirects to home (`/`) after 2 seconds. Uses Suspense wrapper.

Status states: `loading`, `success`, `error`.

This page does NOT include a branded footer.

```tsx
'use client';

import { Suspense, useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { useRouter, Link } from '@/i18n/navigation';
import { useSearchParams } from 'next/navigation';
import { getAuthClient } from '@/lib/browserClient';

type ConfirmEmailStatus = 'loading' | 'success' | 'error';

function ConfirmEmailChangeContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const t = useTranslations('ConfirmEmailChange');

  const [status, setStatus] = useState<ConfirmEmailStatus>('loading');
  const [message, setMessage] = useState('');

  const token = searchParams.get('token');

  useEffect(() => {
    if (!token) {
      setStatus('error');
      setMessage(t('invalidToken'));
      return;
    }

    const confirmEmail = async () => {
      const client = getAuthClient();
      const result = await client.confirmEmailChange(token);

      if (result.success && result.data) {
        setStatus('success');
        setMessage(t('successMessage'));

        setTimeout(() => {
          router.push('/');
        }, 2000);
      } else if (!result.success) {
        setStatus('error');
        setMessage(result.error || t('confirmFailed'));
      }
    };

    confirmEmail();
  }, [token, t, router]);

  // Loading state
  if (status === 'loading') {
    return (
      <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
        <div className="relative z-10 w-full max-w-md">
          <div className="card p-8 animate-scale-in">
            <div className="text-center">
              <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-[var(--amber-glow)]/10 flex items-center justify-center">
                <div className="spinner border-[var(--amber-glow)] border-t-transparent w-8 h-8" />
              </div>

              <h2 className="font-display text-2xl font-bold mb-3">
                {t('title')}
              </h2>
              <p className="text-[var(--foreground-muted)]">{t('processing')}</p>
            </div>
          </div>
        </div>
      </main>
    );
  }

  // Error state
  if (status === 'error') {
    return (
      <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
        <div className="relative z-10 w-full max-w-md">
          <div className="card p-8 animate-scale-in">
            <div className="text-center">
              <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-[var(--error-red)]/10 flex items-center justify-center">
                <svg className="w-8 h-8 text-[var(--error-red)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>

              <h2 className="font-display text-2xl font-bold mb-3 text-[var(--error-red)]">
                {t('confirmFailed')}
              </h2>
              <p className="text-[var(--foreground-muted)] mb-6">{message}</p>

              <Link href="/" className="btn-secondary inline-flex">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                </svg>
                {t('backToHome')}
              </Link>
            </div>
          </div>
        </div>
      </main>
    );
  }

  // Success state
  return (
    <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
      <div className="relative z-10 w-full max-w-md">
        <div className="card p-8 animate-scale-in">
          <div className="text-center">
            <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-[var(--success-green)]/10 flex items-center justify-center">
              <svg className="w-8 h-8 text-[var(--success-green)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </div>

            <h2 className="font-display text-2xl font-bold mb-3 text-[var(--success-green)]">
              {t('successTitle')}
            </h2>
            <p className="text-[var(--foreground-muted)]">{t('redirectingHome')}</p>

            <div className="mt-4 flex justify-center">
              <div className="spinner border-[var(--amber-glow)] border-t-transparent" />
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}

export default function ConfirmEmailChangePage() {
  const t = useTranslations('Common');

  return (
    <Suspense fallback={
      <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6">
        <div className="relative z-10 text-center animate-fade-in">
          <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-[var(--amber-glow)]/10 flex items-center justify-center">
            <div className="spinner border-[var(--amber-glow)] border-t-transparent" />
          </div>
          <p className="text-[var(--foreground-muted)] font-medium">{t('loading')}</p>
        </div>
      </main>
    }>
      <ConfirmEmailChangeContent />
    </Suspense>
  );
}
```

---

## 6. app/[locale]/welcome/page.tsx

Welcome page displayed after successful account creation. Features a confetti animation and an animated checkmark. Links to the login page. Does NOT use Suspense (no async data loading). Includes `<style jsx>` block for confetti and checkmark keyframe animations.

This page does NOT need a Suspense wrapper since it has no search params or async operations on mount.

```tsx
'use client';

import { useTranslations } from 'next-intl';
import { Link } from '@/i18n/navigation';
import { useEffect, useState } from 'react';

function SuccessCheckmark() {
  return (
    <div className="relative">
      {/* Animated rings */}
      <div className="absolute inset-0 rounded-full border-2 border-[var(--success-green)] animate-[pulse-ring_2s_ease-out_infinite]" />
      <div className="absolute inset-0 rounded-full border-2 border-[var(--success-green)] animate-[pulse-ring_2s_ease-out_infinite_0.5s]" />

      {/* Main circle */}
      <div className="relative w-24 h-24 rounded-full bg-[var(--success-green)]/10 flex items-center justify-center">
        <svg
          className="w-12 h-12 text-[var(--success-green)]"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2.5}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M5 13l4 4L19 7"
            className="animate-[draw_0.5s_ease-out_0.3s_forwards]"
            style={{
              strokeDasharray: 24,
              strokeDashoffset: 24,
            }}
          />
        </svg>
      </div>
    </div>
  );
}

function Confetti() {
  const [particles, setParticles] = useState<Array<{ id: number; x: number; delay: number; color: string }>>([]);

  useEffect(() => {
    const colors = ['var(--amber-glow)', 'var(--amber-bright)', 'var(--success-green)', 'var(--foreground-muted)'];
    const newParticles = Array.from({ length: 20 }, (_, i) => ({
      id: i,
      x: Math.random() * 100,
      delay: Math.random() * 0.5,
      color: colors[Math.floor(Math.random() * colors.length)],
    }));
    setParticles(newParticles);
  }, []);

  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none">
      {particles.map((particle) => (
        <div
          key={particle.id}
          className="absolute w-2 h-2 rounded-full animate-[confetti-fall_3s_ease-out_forwards]"
          style={{
            left: `${particle.x}%`,
            top: '-10px',
            backgroundColor: particle.color,
            animationDelay: `${particle.delay}s`,
          }}
        />
      ))}
    </div>
  );
}

export default function WelcomePage() {
  const t = useTranslations('Welcome');
  const tLogin = useTranslations('Login');
  const tCommon = useTranslations('Common');

  return (
    <main className="min-h-screen mesh-gradient paper-texture flex items-center justify-center p-6 overflow-hidden">
      {/* Confetti animation */}
      <Confetti />

      <div className="relative z-10 w-full max-w-lg text-center">
        {/* Success checkmark */}
        <div className="flex justify-center mb-8 animate-scale-in">
          <SuccessCheckmark />
        </div>

        {/* Title */}
        <h1 className="font-display text-3xl md:text-4xl lg:text-5xl font-bold mb-4 animate-fade-in-up delay-200">
          {t('title')}
        </h1>

        {/* Decorative line */}
        <div className="flex justify-center mb-6 animate-fade-in-up delay-300">
          <div className="decorative-line" />
        </div>

        {/* Subtitle */}
        <p className="text-xl text-[var(--foreground)] mb-3 animate-fade-in-up delay-300">
          {t('subtitle')}
        </p>

        {/* Description */}
        <p className="text-[var(--foreground-muted)] text-lg mb-10 max-w-md mx-auto animate-fade-in-up delay-400">
          {t('description')}
        </p>

        {/* CTA Button */}
        <div className="animate-fade-in-up delay-500">
          <Link
            href="/login"
            className="btn-primary inline-flex w-auto px-10 py-4 text-lg"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1" />
            </svg>
            {tLogin('signInButton')}
          </Link>
        </div>

        {/* Footer brand */}
        <p className="mt-16 text-sm text-[var(--foreground-muted)] animate-fade-in delay-600">
          {ProjectBrandHtml}
          {' '}&middot; {tCommon('readyToCreate')}
        </p>
      </div>

      {/* Add confetti animation keyframes via style tag */}
      <style jsx>{`
        @keyframes confetti-fall {
          0% {
            transform: translateY(0) rotate(0deg) scale(1);
            opacity: 1;
          }
          100% {
            transform: translateY(100vh) rotate(720deg) scale(0);
            opacity: 0;
          }
        }
        @keyframes draw {
          to {
            stroke-dashoffset: 0;
          }
        }
      `}</style>
    </main>
  );
}
```

---

## Translation Keys Reference

These auth pages depend on the following translation key sections in `messages/en.json` (see `references/i18n-templates.md` for the full file):

- **Common** -- `loading`, `logout`, `error`, `success`, `brandName`, `back`, `backToHome`, `secureAuthentication`, `secureVerification`, `readyToCreate`
- **Login** -- `title`, `emailLabel`, `emailPlaceholder`, `passwordLabel`, `passwordPlaceholder`, `signInButton`, `signingIn`, `accessGranted`, `authenticationFailed`, `accessDenied`, `siteNotFound`, `initializingConnection`, `forgotPassword`
- **Verify** -- `title`, `titleSetPassword`, `subtitle`, `verifying`, `checkingToken`, `passwordLabel`, `passwordPlaceholder`, `confirmPasswordLabel`, `confirmPasswordPlaceholder`, `passwordsDoNotMatch`, `verifyButton`, `setPasswordButton`, `verificationSuccess`, `redirectingToLogin`, `invalidToken`, `verificationFailed`, `backToLogin`
- **ForgotPassword** -- `title`, `subtitle`, `emailLabel`, `emailPlaceholder`, `sendResetLink`, `sending`, `successTitle`, `successMessage`, `backToLogin`, `requestFailed`
- **ResetPassword** -- `title`, `subtitle`, `passwordLabel`, `passwordPlaceholder`, `confirmPasswordLabel`, `confirmPasswordPlaceholder`, `passwordsDoNotMatch`, `resetButton`, `resetting`, `successTitle`, `successMessage`, `redirectingToLogin`, `invalidToken`, `resetFailed`, `backToLogin`
- **ConfirmEmailChange** -- `title`, `processing`, `successTitle`, `successMessage`, `redirectingHome`, `invalidToken`, `confirmFailed`, `backToHome`
- **Welcome** -- `title`, `subtitle`, `description`

## CSS Classes Used

All auth pages use CSS classes defined in the design system (`globals.css`):

- **Layout**: `mesh-gradient`, `paper-texture`
- **Cards**: `card`
- **Forms**: `input-field`
- **Buttons**: `btn-primary`, `btn-secondary`
- **Status**: `status-success`, `status-error`
- **Animations**: `animate-fade-in`, `animate-fade-in-up`, `animate-scale-in`, `delay-100` through `delay-600`
- **Loading**: `spinner`
- **Decorative**: `decorative-line` (welcome page only)
- **Typography**: `font-display`

## Auth Client Methods Used

The browser hits two surfaces: the singleton `AuthClient` from `getAuthClient()` (for unprotected and Bearer-token-gated endpoints), and `browserAuthProxy.*` (for the six tenant-key-gated endpoints, which the local Next.js routes proxy to Aegis).

**Direct via `getAuthClient()` / singleton:**

- `getAuthClient()` -- Returns the singleton AuthClient, hydrated from localStorage
- `getSiteDomain()` -- Returns the configured site domain from env
- `client.getSiteByDomain(domain)` -- Looks up site info by domain (public, not gated)
- `client.confirmEmailChange(token)` -- Confirms an email change (Bearer-token gated)

**Via `browserAuthProxy` (proxies to `/api/frontend/auth/*`):**

- `browserAuthProxy.login(email, password)` -- Authenticates and returns tokens
- `browserAuthProxy.register(email, password?)` -- Registers a new user
- `browserAuthProxy.checkVerificationToken(token)` -- Checks if token is valid and if password is required
- `browserAuthProxy.verifyEmail(token, password?)` -- Verifies email, optionally setting password
- `browserAuthProxy.requestPasswordReset(email)` -- Requests a password reset email (server supplies `site_id` from env)
- `browserAuthProxy.resetPassword(token, password)` -- Resets password using token (server supplies `site_id` from env)
