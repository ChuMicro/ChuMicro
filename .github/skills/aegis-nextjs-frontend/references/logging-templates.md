# Logging Templates Reference

This file contains the server-side logging template for Aegis-powered Next.js frontends, using `byteforge-loki-logging-ts` for structured Grafana Loki logging in production and formatted console output during local development.

---

## CRITICAL: Placeholder Replacement Guide

| Placeholder | Description | Example |
|---|---|---|
| `{project-name}` | Kebab-case project name used as the Loki `app` tag | `devnotes` |

---

## lib/logger.ts

This module provides a unified logging interface that automatically switches between console output (local dev) and Loki shipping (production). It is **server-side only** — do not import it in React components or client-side code.

```typescript
import { LokiLogger } from 'byteforge-loki-logging-ts';

const DEBUG_LOCAL = process.env.DEBUG_LOCAL === 'true';
const LOKI_URL = process.env.LOKI_URL;
const LOKI_USER = process.env.LOKI_USER;
const LOKI_PASS = process.env.LOKI_PASS;
const LOKI_CA_PATH = process.env.LOKI_CA_PATH;

const useLoki = !DEBUG_LOCAL && !!LOKI_URL;

interface LogExtra {
  [key: string]: string;
}

interface Logger {
  debug(message: string, extra?: LogExtra): void;
  info(message: string, extra?: LogExtra): void;
  warning(message: string, extra?: LogExtra): void;
  error(message: string, extra?: LogExtra): void;
  critical(message: string, extra?: LogExtra): void;
}

function formatPrefix(level: string, name: string): string {
  const timestamp = new Date().toISOString();
  return `[${timestamp}] [${level.toUpperCase()}] [${name}]`;
}

function formatExtra(extra?: LogExtra): string {
  if (!extra || Object.keys(extra).length === 0) {
    return '';
  }
  return ' ' + JSON.stringify(extra);
}

function createConsoleLogger(name: string): Logger {
  return {
    debug(message: string, extra?: LogExtra): void {
      console.debug(`${formatPrefix('DEBUG', name)} ${message}${formatExtra(extra)}`);
    },
    info(message: string, extra?: LogExtra): void {
      console.info(`${formatPrefix('INFO', name)} ${message}${formatExtra(extra)}`);
    },
    warning(message: string, extra?: LogExtra): void {
      console.warn(`${formatPrefix('WARNING', name)} ${message}${formatExtra(extra)}`);
    },
    error(message: string, extra?: LogExtra): void {
      console.error(`${formatPrefix('ERROR', name)} ${message}${formatExtra(extra)}`);
    },
    critical(message: string, extra?: LogExtra): void {
      console.error(`${formatPrefix('CRITICAL', name)} ${message}${formatExtra(extra)}`);
    },
  };
}

function createLokiLogger(name: string): Logger {
  const transportConfig: { url: string; auth?: { username: string; password: string }; verify?: string | boolean } = {
    url: LOKI_URL!,
  };

  if (LOKI_USER && LOKI_PASS) {
    transportConfig.auth = { username: LOKI_USER, password: LOKI_PASS };
  }

  if (LOKI_CA_PATH) {
    transportConfig.verify = LOKI_CA_PATH;
  }

  return new LokiLogger(
    {
      transport: transportConfig,
      emitter: {
        tags: { application: '{project-name}', env: 'production' },
        asJson: true,
      },
      batch: {
        capacity: 20,
        flushIntervalMs: 3000,
      },
    },
    name,
  );
}

export function createLogger(name: string): Logger {
  if (useLoki) {
    return createLokiLogger(name);
  }
  return createConsoleLogger(name);
}

export const logger = createLogger('{project-name}');

const mode = useLoki ? `loki (${LOKI_URL})` : 'console (DEBUG_LOCAL)';
logger.info(`Logger initialized in ${mode} mode`);
```

CRITICAL: Replace `{project-name}` in two places: the `emitter.tags.application` value inside `createLokiLogger`, and the `createLogger` call for the default singleton.

CRITICAL: The Loki label **must** be `application`, not `app`. All services across the stack (Python and TypeScript) use `application` as the standard label for filtering in Grafana. Using `app` will create inconsistent labels that fragment your Loki queries.

---

## Usage in API Route Handlers

Import the singleton `logger` in every API route handler. Use `logger.info()` for success paths and `logger.error()` in catch blocks, always including the `route` in extra fields for Loki filtering.

```typescript
// app/api/example/route.ts
import { NextResponse } from 'next/server';
import { logger } from '@/lib/logger';

export async function GET(): Promise<NextResponse> {
  try {
    // ... business logic ...
    logger.info('Example request processed', { route: '/api/example' });
    return NextResponse.json({ ok: true });
  } catch (error) {
    logger.error('Example request failed', { route: '/api/example', error: String(error) });
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
```

For named child loggers (useful in larger API surfaces):

```typescript
import { createLogger } from '@/lib/logger';

const log = createLogger('api.users');
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DEBUG_LOCAL` | No | `undefined` | Set to `true` for console logging (local dev) |
| `LOKI_URL` | Production | — | Loki push API base URL (e.g., `https://loki.example.com`) |
| `LOKI_USER` | No | — | Basic auth username (omit if Loki has no auth) |
| `LOKI_PASS` | No | — | Basic auth password |
| `LOKI_CA_PATH` | No | — | Path to CA PEM bundle for self-signed TLS certs |

**Mode selection logic:**
- `DEBUG_LOCAL=true` → console logger (ignores all `LOKI_*` vars)
- `DEBUG_LOCAL` unset/false AND `LOKI_URL` set → Loki logger
- `DEBUG_LOCAL` unset/false AND `LOKI_URL` unset → console logger (fallback)

---

## Critical Notes

### Server-Side Only

`byteforge-loki-logging-ts` uses Node.js built-in modules (`node:https`, `node:http`, `node:fs`). It **cannot** run in the browser or in Next.js Edge Runtime. Only import it in:
- `app/api/**/route.ts` (API Route Handlers)
- Server Components (if needed)
- `instrumentation.ts` (if applicable)

Never import it in files marked `'use client'`.

### transpilePackages Required

Since the package is installed from GitHub (raw source), Next.js must transpile it. Ensure `next.config.ts` includes `'byteforge-loki-logging-ts'` in `transpilePackages`. Without this, you will get module resolution errors at build time.

### Batching Behavior

The logger uses batched sending (capacity: 20, flush every 3s) which is optimized for long-running Node.js processes. This works well with Next.js `standalone` output mode where the server stays alive between requests. The batch timer uses `unref()` so it won't prevent Node.js from exiting.
