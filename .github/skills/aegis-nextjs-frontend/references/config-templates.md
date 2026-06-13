# Configuration File Templates for Aegis Next.js Frontend

These templates provide the baseline configuration files needed when scaffolding a new Next.js frontend project integrated with ByteForge Aegis authentication.

---

## CRITICAL: Placeholder Replacement Guide

Before using these templates, you MUST replace all `{placeholder}` values with project-specific values. Failure to replace any placeholder will result in a broken project.

| Placeholder | Description | Example |
|---|---|---|
| `{project-name}` | Hyphenated project name for package.json `name` field | `my-saas-app` |
| `{project_description}` | Short description of the project | `Frontend for My SaaS Application` |
| `{author_name}` | Author's full name | `Jason Byteforge` |
| `{author_email}` | Author's email address | `jason@example.com` |
| `{aegis_api_url}` | Full URL to the Aegis authentication API (must be browser-accessible) | `https://aegis.example.com` |
| `{site_domain}` | Domain of the site as registered in the Aegis site configuration | `myapp.example.com` |

CRITICAL: The `{project-name}` placeholder uses hyphens (for npm naming conventions), while other placeholders use underscores. Pay attention to this distinction.

CRITICAL: The `NEXT_PUBLIC_` prefix on environment variables is required by Next.js to expose them to the browser. Do not remove this prefix.

---

## 1. package.json

```json
{
  "name": "{project-name}-frontend",
  "version": "1.0.0",
  "description": "{project_description}",
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint"
  },
  "author": "{author_name} <{author_email}>",
  "license": "Proprietary",
  "dependencies": {
    "@tailwindcss/postcss": "^4.1.17",
    "byteforge-aegis-client-js": "git+https://github.com/jmazzahacks/byteforge-aegis-client-js.git",
    "byteforge-loki-logging-ts": "github:jmazzahacks/byteforge-loki-logging-ts",
    "next": "^16.0.1",
    "next-intl": "^4.6.1",
    "react": "^19.2.3",
    "react-dom": "^19.2.3"
  },
  "devDependencies": {
    "@types/node": "^24.10.0",
    "@types/react": "^19.2.3",
    "autoprefixer": "^10.4.22",
    "eslint": "^9.39.1",
    "eslint-config-next": "^16.0.1",
    "postcss": "^8.5.6",
    "tailwindcss": "^4.1.17",
    "typescript": "^5.9.3"
  }
}
```

---

## 2. next.config.ts

```typescript
import type { NextConfig } from 'next';
import createNextIntlPlugin from 'next-intl/plugin';

const withNextIntl = createNextIntlPlugin('./i18n/request.ts');

const nextConfig: NextConfig = {
  transpilePackages: ['byteforge-aegis-client-js', 'byteforge-loki-logging-ts'],
  output: 'standalone',
};

export default withNextIntl(nextConfig);
```

CRITICAL: The `transpilePackages` entries for `byteforge-aegis-client-js` and `byteforge-loki-logging-ts` are required because both packages are installed from GitHub repositories and must be transpiled by Next.js. Removing either will cause build failures.

CRITICAL: The `output: 'standalone'` setting is required for Docker deployments. It produces a self-contained build that does not depend on `node_modules` at runtime.

CRITICAL: The `next-intl` plugin path `'./i18n/request.ts'` must match the actual location of the i18n request configuration file in the project.

---

## 3. tsconfig.json

```json
{
  "compilerOptions": {
    "target": "ES2017",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "react-jsx",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": { "@/*": ["./*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts", ".next/dev/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

CRITICAL: The `"moduleResolution": "bundler"` setting is required for Next.js 16+ compatibility. Do not change this to `"node"` or `"node16"`.

CRITICAL: The path alias `"@/*": ["./*"]` enables imports like `import { Foo } from '@/components/Foo'`. This convention must be used consistently throughout the project.

---

## 4. tailwind.config.ts

```typescript
import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};

export default config;
```

CRITICAL: The `content` array must include all directories that contain Tailwind CSS classes. If you add new directories with components (e.g., `./lib/`, `./layouts/`), you must add them to this array or their Tailwind classes will be purged from the production build.

---

## 5. postcss.config.mjs

```javascript
const config = {
  plugins: {
    '@tailwindcss/postcss': {},
  },
};

export default config;
```

CRITICAL: This uses the `@tailwindcss/postcss` plugin (Tailwind CSS v4 approach) rather than the legacy `tailwindcss` PostCSS plugin. This must match the dependency in `package.json`.

---

## 6. global.d.ts

```typescript
import en from './messages/en.json';

type Messages = typeof en;

declare global {
  interface IntlMessages extends Messages {}
}
```

CRITICAL: This file provides TypeScript type safety for `next-intl` message keys. The import path `'./messages/en.json'` must point to the English (default) messages file. If the messages directory is located elsewhere, update this path accordingly.

CRITICAL: This file must be placed in the project root directory so the relative import to `./messages/en.json` resolves correctly.

---

## 7. .env.example

```
# Aegis Authentication API URL (browser-accessible — used only for the
# unprotected getSiteByDomain bootstrap)
NEXT_PUBLIC_AEGIS_API_URL={aegis_api_url}

# Site domain for authentication (must match aegis site configuration)
NEXT_PUBLIC_SITE_DOMAIN={site_domain}

# Server-side Aegis URL (used by /api/frontend/auth/* proxy routes)
AEGIS_API_URL={aegis_api_url}

# Per-tenant secret for X-Tenant-Api-Key header. Get from the Aegis admin
# dashboard. SERVER-SIDE ONLY — never expose in browser code.
# See references/tenant-api-key-templates.md for the full pattern.
AEGIS_TENANT_API_KEY={paste_from_aegis_admin_dashboard}

# Site ID from Aegis (server-side, used by proxy routes for verify-email/etc.)
AEGIS_SITE_ID={your_site_id}

# Logging: set DEBUG_LOCAL=true for console output, omit or set to false for Loki
DEBUG_LOCAL=true
# LOKI_URL=https://loki.example.com
# LOKI_USER=
# LOKI_PASS=
# LOKI_CA_PATH=
```

CRITICAL: Copy this file to `.env.local` for local development. Never commit `.env.local` to version control.

CRITICAL: The `NEXT_PUBLIC_AEGIS_API_URL` must be accessible from the user's browser, not just from the server. This means it cannot be an internal Docker network address in production -- it must be a publicly routable URL or a URL accessible from the client's network.

CRITICAL: The `NEXT_PUBLIC_SITE_DOMAIN` must exactly match the site domain configured in the Aegis backend. A mismatch will cause authentication failures.
