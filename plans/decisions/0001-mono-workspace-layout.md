# Decision 0001: Mono-workspace layout

Status: `accepted`
Date: `2026-03-28`

## Context

ChuMicro needs shared tooling and support code, but libraries must still be published independently.

## Decision

Use a mono-workspace with shared root tooling and per-package directories for publishable libraries and support packages.

## Consequences

- shared tooling lives at the repo root
- each library can keep its own packaging metadata
- workspace conventions matter because many packages will coexist here
