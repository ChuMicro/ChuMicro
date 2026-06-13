# i18n Templates for Next.js + ByteForge Aegis Auth

These templates provide internationalization support using `next-intl` for Next.js frontends scaffolded with ByteForge Aegis authentication.

## i18n/routing.ts

Defines the supported locales and routing strategy.

```typescript
import { defineRouting } from 'next-intl/routing';

export const routing = defineRouting({
  locales: ['en'],
  defaultLocale: 'en',
  localePrefix: 'always'
});

export type Locale = (typeof routing.locales)[number];
```

## i18n/request.ts

Server-side request configuration that loads the correct locale messages.

```typescript
import { getRequestConfig } from 'next-intl/server';
import { routing, Locale } from './routing';

export default getRequestConfig(async ({ requestLocale }) => {
  let locale = await requestLocale;

  if (!locale || !routing.locales.includes(locale as Locale)) {
    locale = routing.defaultLocale;
  }

  return {
    locale,
    messages: (await import(`../messages/${locale}.json`)).default
  };
});
```

## i18n/navigation.ts

Locale-aware navigation utilities that replace standard Next.js navigation.

```typescript
import { createNavigation } from 'next-intl/navigation';
import { routing } from './routing';

export const { Link, redirect, usePathname, useRouter, getPathname } =
  createNavigation(routing);
```

## proxy.ts (middleware - project root)

Middleware that handles locale detection and routing. This file goes in the project root (e.g., `src/proxy.ts` or `proxy.ts` depending on project structure).

The wrapper around `createMiddleware(routing)` defends against an upstream-proxy footgun: when a reverse proxy forwards `Host` and `X-Forwarded-Proto` but **not** `X-Forwarded-Host` / `X-Forwarded-Port`, Next.js infers the port from the local TCP listener (3000) and emits broken absolute redirects like `https://your-host:3000/en`. The wrapper checks the redirect's host against the inbound `Host` header and, if they differ, rewrites the host to match. No-op when the proxy is configured correctly. See `docker-templates.md` for the proxy header contract you should still satisfy upstream — this fallback is a safety net, not a substitute.

```typescript
import createMiddleware from 'next-intl/middleware';
import { NextRequest, NextResponse } from 'next/server';
import { routing } from './i18n/routing';

const intlMiddleware = createMiddleware(routing);

export default function middleware(request: NextRequest): NextResponse {
  const response = intlMiddleware(request);
  const location = response.headers.get('location');
  if (!location) {
    return response;
  }

  const hostHeader = request.headers.get('host');
  if (!hostHeader) {
    return response;
  }

  try {
    const url = new URL(location);
    if (url.host !== hostHeader) {
      url.host = hostHeader;
      response.headers.set('location', url.toString());
    }
  } catch {
    // Relative Location — nothing to rewrite.
  }

  return response;
}

export const config = {
  matcher: ['/((?!api|_next|.*\\..*).*)']
};
```

## messages/en.json

Full English translation file with all keys organized by page/section. Use `{ProjectName}` and `{project_description}` as placeholders that get replaced during project scaffolding.

```json
{
  "Common": {
    "loading": "Loading...",
    "logout": "Logout",
    "error": "Error",
    "success": "Success",
    "brandName": "{ProjectName}",
    "back": "Back",
    "backToHome": "Back to Home",
    "secureAuthentication": "Secure authentication",
    "secureVerification": "Secure verification",
    "readyToCreate": "Welcome aboard"
  },
  "Home": {
    "title": "{ProjectName}",
    "subtitle": "{project_description}",
    "description": "{project_description}",
    "feature1Title": "Feature One",
    "feature1Description": "Description of the first key feature of your project.",
    "feature2Title": "Feature Two",
    "feature2Description": "Description of the second key feature of your project.",
    "feature3Title": "Feature Three",
    "feature3Description": "Description of the third key feature of your project.",
    "footerTagline": "Built with care."
  },
  "Welcome": {
    "title": "Welcome to {ProjectName}",
    "subtitle": "Your account has been created successfully.",
    "description": "You can now sign in to access the platform."
  },
  "Login": {
    "title": "Sign In",
    "emailLabel": "Email Address",
    "emailPlaceholder": "you@example.com",
    "passwordLabel": "Password",
    "passwordPlaceholder": "Enter your password",
    "signInButton": "Sign In",
    "signingIn": "Signing in...",
    "accessGranted": "Access granted. Redirecting...",
    "authenticationFailed": "Authentication failed",
    "accessDenied": "Access Denied",
    "noSiteSpecified": "No site specified. Please use ?site=your-domain",
    "siteNotFound": "Site not found",
    "initializingConnection": "Initializing connection...",
    "forgotPassword": "Forgot password?"
  },
  "Verify": {
    "title": "Verify Your Email",
    "titleSetPassword": "Set Your Password",
    "subtitle": "Complete your account setup",
    "verifying": "Verifying...",
    "checkingToken": "Checking verification link...",
    "passwordLabel": "Password",
    "passwordPlaceholder": "Create a password",
    "confirmPasswordLabel": "Confirm Password",
    "confirmPasswordPlaceholder": "Confirm your password",
    "passwordsDoNotMatch": "Passwords do not match",
    "verifyButton": "Verify Email",
    "setPasswordButton": "Set Password & Verify",
    "verificationSuccess": "Email verified successfully",
    "redirectingToLogin": "Redirecting to login...",
    "invalidToken": "Invalid or expired verification link",
    "verificationFailed": "Verification failed",
    "backToLogin": "Back to Login"
  },
  "ForgotPassword": {
    "title": "Reset Password",
    "subtitle": "Enter your email to receive a reset link",
    "emailLabel": "Email Address",
    "emailPlaceholder": "you@example.com",
    "sendResetLink": "Send Reset Link",
    "sending": "Sending...",
    "successTitle": "Check Your Email",
    "successMessage": "If an account exists with that email, you will receive a password reset link.",
    "backToLogin": "Back to Login",
    "requestFailed": "Unable to process request"
  },
  "ResetPassword": {
    "title": "Set New Password",
    "subtitle": "Create a new password for your account",
    "passwordLabel": "New Password",
    "passwordPlaceholder": "Enter new password",
    "confirmPasswordLabel": "Confirm Password",
    "confirmPasswordPlaceholder": "Confirm new password",
    "passwordsDoNotMatch": "Passwords do not match",
    "resetButton": "Reset Password",
    "resetting": "Resetting...",
    "successTitle": "Password Reset",
    "successMessage": "Your password has been reset successfully.",
    "redirectingToLogin": "Redirecting to login...",
    "invalidToken": "Invalid or expired reset link",
    "resetFailed": "Password reset failed",
    "backToLogin": "Back to Login"
  },
  "ConfirmEmailChange": {
    "title": "Confirming Email Change",
    "processing": "Processing your request...",
    "successTitle": "Email Updated",
    "successMessage": "Your email address has been changed successfully.",
    "redirectingHome": "Redirecting to home...",
    "invalidToken": "Invalid or expired confirmation link",
    "confirmFailed": "Email change confirmation failed",
    "backToHome": "Back to Home"
  },
  "Dashboard": {
    "title": "Dashboard",
    "subtitle": "Welcome to your dashboard",
    "goToDashboard": "Go to Dashboard",
    "emptyStateTitle": "Coming Soon",
    "emptyStateMessage": "Your dashboard is being built. Check back soon for new features."
  }
}
```

## Adding More Languages

To add support for a new language (e.g., Spanish `es`):

1. **Update `i18n/routing.ts`** -- Add the new locale to the `locales` array:
   ```typescript
   export const routing = defineRouting({
     locales: ['en', 'es'],
     defaultLocale: 'en',
     localePrefix: 'always'
   });
   ```

2. **Create `messages/{locale}.json`** -- Copy `messages/en.json` to `messages/es.json` and translate all values. Keep the keys identical; only translate the string values.

3. **Add language name to LanguageSwitcher component** -- Update the LanguageSwitcher component's locale-to-label mapping so the new language appears in the UI (e.g., `{ en: 'English', es: 'Espanol' }`).
