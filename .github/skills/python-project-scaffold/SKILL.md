---
name: python-project-scaffold
description: Scaffold a multi-repo Python workspace with models library, core library, Flask backend, and optional sub-projects. Creates directory structure and root CLAUDE.md describing each sub-project and which skills to use next. Use when starting a new Python project, setting up a multi-repo workspace, or scaffolding a project skeleton.
---

# Python Project Scaffold

This skill creates a multi-repo workspace skeleton for a new Python project. It sets up the directory structure and a root `CLAUDE.md` that describes each sub-project's purpose, how they connect, and which existing skills to run next. No application code is generated — actual code generation is deferred to existing skills.

## When to Use This Skill

Use this skill when:
- Starting a brand-new Python project from scratch
- You want the standard multi-repo workspace layout (models lib, core lib, Flask backend)
- You want a root CLAUDE.md that guides future development with existing skills

## What This Skill Creates

1. **Directory skeleton** — empty sub-project directories under `{project}/`
2. **`{project}/CLAUDE.md`** — root development guide describing each sub-project and which skills to use
3. **`{project}/.gitignore`** — workspace-level gitignore for Python projects
4. **Next-steps documentation** — tells the user which skills to run in each sub-project

## Step 1: Gather Project Information

**IMPORTANT**: Before creating anything, ask the user these questions using AskUserQuestion:

1. **"What is your project name?"** (e.g., "arcana", "trading-bot", "my-app")
   - Derive naming variants:
     - `{project}` — kebab-case (e.g., `arcana`, `trading-bot`)
     - `{project_name}` — snake_case (e.g., `arcana`, `trading_bot`)
     - `{ProjectName}` — PascalCase (e.g., `Arcana`, `TradingBot`)
     - `{PROJECT_NAME}` — UPPER_SNAKE (e.g., `ARCANA`, `TRADING_BOT`)

2. **"Brief project description?"** (one or two sentences for the CLAUDE.md header)

3. **"What is the GitHub org or owner?"** (e.g., `jmazzahacks`)

4. **"Which optional sub-projects do you need?"** (multi-select)
   - `python-scripts` — standalone utility scripts
   - `{project}-api-python` — Python API client library
   - `{project}-api-js` — TypeScript API client library
   - `{project}-frontend` — Next.js frontend

5. **"Does the backend need Celery + Redis for background tasks?"** (yes/no)

6. **"Which license?"**
   - Proprietary
   - MIT
   - O'Saasy (https://osaasy.dev/)

## Step 2: Create Directory Structure

Create empty directories under `{project}/`. Use `mkdir -p` to create each directory with a `.gitkeep` file so they are tracked by git.

**Always created:**
```
{project}/
├── {project}-models/
├── {project}-core/
└── {project}-backend/
```

**Conditionally created based on Step 1 answers:**
```
├── python-scripts/          # if "python-scripts" selected
├── {project}-api-python/    # if Python API client selected
├── {project}-api-js/        # if TypeScript API client selected
└── {project}-frontend/         # if Next.js frontend selected
```

## Step 3: Create Root CLAUDE.md

Create `{project}/CLAUDE.md` with the following structure. Replace all `{project}`, `{project_name}`, `{ProjectName}`, and `{PROJECT_NAME}` placeholders with actual values.

```markdown
# {ProjectName} — Development Guide

{description}

## Project Structure

This is a multi-repo workspace. Each sub-directory is an independent project with its own virtual environment, git history, and dependencies.

| Directory | Purpose | Type |
|-----------|---------|------|
| `{project}-models/` | Shared data models and schemas | pip package (library) |
| `{project}-core/` | Business logic and service layer | pip package (library) |
| `{project}-backend/` | Flask REST API server | Docker service |
{# Include rows for optional sub-projects only if selected: }
{# | `python-scripts/` | Standalone utility scripts | Scripts | }
{# | `{project}-api-python/` | Python API client library | pip package (library) | }
{# | `{project}-api-js/` | TypeScript API client library | npm package | }
{# | `{project}-frontend/` | Next.js frontend application | Docker service | }

## Dependency Chain

```
{project}-models  →  {project}-core  →  {project}-backend
```

- **{project}-models** has no internal dependencies. It defines shared data models.
- **{project}-core** depends on `{project}-models`. It contains business logic.
- **{project}-backend** depends on both `{project}-models` and `{project}-core`.

## Setting Up Each Sub-Project

### {project}-models (shared models library)

Use the `python-lib-setup` skill to initialize this as a pip package:
```
cd {project}-models
# Invoke python-lib-setup skill
```

### {project}-core (business logic library)

Use the `python-lib-setup` skill to initialize this as a pip package:
```
cd {project}-core
# Invoke python-lib-setup skill
```

Add `{project}-models` as a GitHub dependency in `pyproject.toml`:
```toml
dependencies = [
    # Public repo:
    "{project}-models @ git+https://github.com/{github_org}/{project}-models.git",
    # Private repo (requires CR_PAT environment variable):
    # "{project}-models @ git+https://{env:CR_PAT}@github.com/{github_org}/{project}-models.git",
]
```

### {project}-backend (Flask API server)

Set up in this order:
1. **`flask-smorest-api`** — Flask app factory, blueprints, Marshmallow schemas
2. **`postgres-setup`** — Database schema and setup script
3. **`flask-docker-deployment`** — Dockerfile, build script, versioning
4. **`byteforge-loki-logging`** — Structured logging to Grafana Loki

Add model and core libraries as GitHub dependencies in `requirements.txt`:
```
# Public repos:
{project}-models @ git+https://github.com/{github_org}/{project}-models.git
{project}-core @ git+https://github.com/{github_org}/{project}-core.git
# Private repos (requires CR_PAT environment variable):
# {project}-models @ git+https://${CR_PAT}@github.com/{github_org}/{project}-models.git
# {project}-core @ git+https://${CR_PAT}@github.com/{github_org}/{project}-core.git
```

{# Include this section only if Celery + Redis was selected: }
#### Celery + Redis

This backend uses Celery for background task processing with Redis as the broker. Environment variables:
- `{PROJECT_NAME}_REDIS_URL` — Redis connection URL (e.g., `redis://localhost:6379/0`)

{# Include this section only if {project}-frontend was selected: }
### {project}-frontend (Next.js frontend)

Use the `aegis-nextjs-frontend` skill to scaffold the frontend:
```
cd {project}-frontend
# Invoke aegis-nextjs-frontend skill
```

{# Include this section only if python-scripts was selected: }
### python-scripts (utility scripts)

Standalone scripts for development, data migration, or maintenance tasks. Each script should:
- Have its own `#!/usr/bin/env python` shebang
- Use `python-dotenv` to load `.env`
- Import from `{project}-models` and `{project}-core` as needed

{# Include this section only if {project}-api-python was selected: }
### {project}-api-python (Python API client)

Use the `python-lib-setup` skill to initialize this as a pip package:
```
cd {project}-api-python
# Invoke python-lib-setup skill
```

{# Include this section only if {project}-api-js was selected: }
### {project}-api-js (TypeScript API client)

Initialize as a TypeScript npm package. Publish to GitHub Packages or npm.

## Development Commands

Each sub-project with Python uses its own virtual environment:
```bash
cd {project}-models/
python -m venv bin
source bin/activate
pip install -r dev-requirements.txt
```

Run tests:
```bash
source bin/activate && pytest
```

Start the backend locally:
```bash
cd {project}-backend/
source bin/activate && python {project_name}.py
```

## Conventions

- **Unix timestamps only** — All date/time fields use `BIGINT` (epoch seconds), never `TIMESTAMP` or `DATETIME`
- **UUID primary keys** — Use `gen_random_uuid()` in PostgreSQL
- **RealDictCursor** — Always use `psycopg2.extras.RealDictCursor` for queries
- **Environment variables** — Project-specific prefix: `{PROJECT_NAME}_` (e.g., `{PROJECT_NAME}_DB_HOST`)
- **Type hints** — All function parameters and return types must have type annotations
- **No lambdas** — Use named functions or loops instead
- **Virtual environments** — Always `source bin/activate` before running Python
- **No local path dependencies** — NEVER use `pip install -e ../sibling-project` or `file:` references. Cross-repo dependencies MUST use GitHub URLs. Public repos: `git+https://github.com/{github_org}/pkg.git`. Private repos: add `CR_PAT` token — in `pyproject.toml`: `git+https://{env:CR_PAT}@github.com/...`, in `requirements.txt`: `git+https://${CR_PAT}@github.com/...`
```

**IMPORTANT**: When generating the actual CLAUDE.md file:
- Remove all `{# ... }` comment lines
- Only include sections for sub-projects that were selected in Step 1
- Replace all placeholders with actual values
- Do NOT wrap the entire file in a code fence — write it as a real markdown file

## Step 4: Create Root .gitignore

Create `{project}/.gitignore`:

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
*.egg-info/
*.egg
dist/
build/
*.whl

# Virtual environments
bin/
lib/
lib64/
pyvenv.cfg
include/
share/

# Environment
.env
*.env.local

# IDE
.idea/
.vscode/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db

# Docker
VERSION

# Node (if frontend selected)
node_modules/
.next/
out/
```

## Step 5: Document Next Steps

After creating all files, tell the user:

1. **Initialize git** in the root `{project}/` directory
2. **Run skills in order** for each sub-project:
   - `cd {project}-models/` → run `python-lib-setup`
   - `cd {project}-core/` → run `python-lib-setup`
   - `cd {project}-backend/` → run `flask-smorest-api`, then `postgres-setup`, then `flask-docker-deployment`, then `byteforge-loki-logging`
   - (If frontend selected) `cd {project}-frontend/` → run `aegis-nextjs-frontend`
   - (If Python API client selected) `cd {project}-api-python/` → run `python-lib-setup`
3. **Create GitHub repos** for each sub-project under `{github_org}/`
4. **Set up `.env`** files with required environment variables
