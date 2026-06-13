---
name: mcp-docker-deployment
description: Set up Docker deployment for Python MCP servers (FastMCP or low-level mcp.server.Server SDK) with SSE/streamable-http transport, automated versioning, and container registry publishing. Use when dockerizing an MCP server, containerizing for remote access, deploying an MCP server behind nginx, or setting up a production MCP server with Docker. Covers Dockerfile, build scripts, docker-compose, and nginx reverse proxy for SSE streaming.
---

# MCP Docker Deployment

Containerize Python MCP servers (FastMCP or low-level SDK) for remote deployment with SSE or streamable-http transport, nginx reverse proxy with HTTPS, and GHCR publishing.

## Step 1: Gather Project Information

Ask the user:

1. **"What is your MCP server entry point file?"** (e.g., `my_mcp_server.py`)
2. **"Does your server use FastMCP (`mcp.server.fastmcp.FastMCP`) or the low-level SDK (`mcp.server.Server`)?"**
3. **"Which transport? `sse` or `streamable-http`?"** (They are NOT interchangeable — different endpoints, different SDK classes)
4. **"What Python files/directories need to be copied into the container?"** (e.g., `tools/`, `models/`, `formatting.py`)
5. **"What container registry URL?"** (e.g., `ghcr.io/{org}/{project}`)
6. **"Does the MCP server need any environment variables?"** (list them for docker-compose and example.env)
7. **"Will this be behind an nginx reverse proxy with HTTPS?"** (yes/no - if yes, include nginx config)
8. **"Does it have private pip dependencies?"** (yes/no - if yes, needs CR_PAT build arg)

## Step 2: Create Dockerfile

```dockerfile
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code - adjust to match project structure
COPY {entry_point} .
# COPY additional files/directories as needed

# Non-root user
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Transport for Docker, bind to all interfaces
ENV MCP_TRANSPORT=sse
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8000

CMD ["python", "{entry_point}"]
```

> **FastMCP note**: If the server uses FastMCP, also set `FASTMCP_HOST` and `FASTMCP_PORT` in the Dockerfile since FastMCP reads those specific env vars:
> ```dockerfile
> ENV FASTMCP_HOST=0.0.0.0
> ENV FASTMCP_PORT=8000
> ```

If private pip dependencies, add before `pip install`:
```dockerfile
ARG CR_PAT
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/* \
    && git config --global url."https://${CR_PAT}@github.com/".insteadOf "https://github.com/" \
    && pip install --no-cache-dir -r requirements.txt \
    && git config --global --unset url."https://${CR_PAT}@github.com/".insteadOf
```

## Step 3: Configure Transport in MCP Server

### Path A: FastMCP (`mcp.server.fastmcp.FastMCP`)

FastMCP's constructor defaults override env vars, so host/port **must** be passed explicitly:

```python
import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "my_mcp_server",
    host=os.getenv("FASTMCP_HOST", "127.0.0.1"),
    port=int(os.getenv("FASTMCP_PORT", "8000")),
    stateless_http=True,
)

# ... register tools ...

if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)
```

**CRITICAL**: Without explicit `host`/`port` args, the container binds to `127.0.0.1` and is unreachable despite `FASTMCP_HOST=0.0.0.0` being set. This is because FastMCP's pydantic-settings defaults take precedence over env vars when constructor args are provided.

**CRITICAL**: `stateless_http=True` is required when running behind a reverse proxy (nginx). Without it, the server tracks sessions via `Mcp-Session-Id` headers. If the proxy drops that header or the SSE connection breaks, clients get `"Session not found"` errors. Stateless mode makes each request independent, which is the correct mode for containerized deployments behind a proxy.

Supported transports:
- `stdio` - Local development (Claude Code local MCP servers)
- `sse` - Server-Sent Events, works behind nginx reverse proxy
- `streamable-http` - Newer HTTP transport

### Path B: Low-level SDK (`mcp.server.Server`)

The low-level SDK requires manual transport wiring with Starlette and uvicorn. Each transport type uses different SDK classes and different endpoints.

#### Required imports

```python
import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from typing import Any

import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Mount, Route
```

#### Server instance

```python
app = Server("my_mcp_server")

# ... register tools with @app.list_tools(), @app.call_tool(), etc. ...
```

#### stdio transport (local development)

```python
async def main_stdio() -> None:
    """Run the MCP server over stdio transport (local development)."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )
```

#### SSE transport

```python
def main_sse() -> None:
    """Run the MCP server over SSE transport (Docker/remote deployment)."""
    host: str = os.environ.get("MCP_HOST", "0.0.0.0")
    port: int = int(os.environ.get("MCP_PORT", "8000"))

    sse_transport = SseServerTransport("/messages/")

    async def handle_sse(request: Any) -> Response:
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await app.run(
                streams[0],
                streams[1],
                app.create_initialization_options(),
            )
        return Response()

    starlette_app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse_transport.handle_post_message),
        ],
    )

    uvicorn.run(starlette_app, host=host, port=port)
```

#### streamable-http transport

```python
def main_streamable_http() -> None:
    """Run the MCP server over streamable-http transport."""
    host: str = os.environ.get("MCP_HOST", "0.0.0.0")
    port: int = int(os.environ.get("MCP_PORT", "8000"))

    session_manager = StreamableHTTPSessionManager(
        app=app,
        json_response=False,
        stateless=True,
    )

    @contextlib.asynccontextmanager
    async def lifespan(starlette_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    starlette_app = Starlette(
        routes=[
            Mount("/mcp", app=session_manager.handle_request),
        ],
        lifespan=lifespan,
    )

    uvicorn.run(starlette_app, host=host, port=port)
```

#### Transport selection

```python
if __name__ == "__main__":
    transport: str = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "stdio":
        asyncio.run(main_stdio())
    elif transport == "sse":
        main_sse()
    elif transport == "streamable-http":
        main_streamable_http()
    else:
        raise SystemExit(f"Unknown MCP_TRANSPORT: {transport} (expected: stdio, sse, streamable-http)")
```

## Step 4: Create build-publish.sh

```bash
#!/bin/sh
# Build and publish MCP Docker image
# Usage: ./build-publish.sh [--no-cache]

REGISTRY="{registry_url}"

NO_CACHE=""
if [ "$1" = "--no-cache" ]; then
    NO_CACHE="--no-cache"
fi

if [ ! -f VERSION ]; then
    echo "1" > VERSION
fi

CURRENT_VERSION=$(cat VERSION)

case "$CURRENT_VERSION" in
    ''|*[!0-9]*)
        echo "ERROR: VERSION file contains non-numeric value: $CURRENT_VERSION"
        exit 1
        ;;
esac

NEXT_VERSION=$((CURRENT_VERSION + 1))

echo "Building ${REGISTRY}:${NEXT_VERSION}..."

docker build \
    --platform linux/amd64 \
    $NO_CACHE \
    -t "${REGISTRY}:${NEXT_VERSION}" \
    .

if [ $? -ne 0 ]; then
    echo "ERROR: Docker build failed"
    exit 1
fi

docker tag "${REGISTRY}:${NEXT_VERSION}" "${REGISTRY}:latest"

echo "Pushing ${REGISTRY}:${NEXT_VERSION}..."
docker push "${REGISTRY}:${NEXT_VERSION}"
if [ $? -ne 0 ]; then
    echo "ERROR: Push failed"
    exit 1
fi

echo "Pushing ${REGISTRY}:latest..."
docker push "${REGISTRY}:latest"
if [ $? -ne 0 ]; then
    echo "ERROR: Push failed"
    exit 1
fi

echo "$NEXT_VERSION" > VERSION
echo "Published ${REGISTRY}:${NEXT_VERSION} and :latest"
```

If private dependencies, add `--build-arg CR_PAT=$CR_PAT` to `docker build`.

Make executable: `chmod +x build-publish.sh`

## Step 5: Create .dockerignore

```
bin/
lib/
lib64/
include/
pyvenv.cfg
.Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
tests/
.pytest_cache/
.coverage
htmlcov/
.git/
.gitignore
.env
VERSION
*.md
.vscode/
.idea/
*.swp
*.swo
*~
.DS_Store
```

## Step 6: Create docker-compose.yaml

```yaml
services:
  {service_name}:
    image: {registry_url}:latest
    container_name: {container_name}
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      MCP_TRANSPORT: sse
      MCP_HOST: 0.0.0.0
      MCP_PORT: 8000
      # Add all app-specific env vars from example.env
    # volumes:
    #   - /path/to/cert.pem:/app/ca.pem:ro
```

> **FastMCP note**: If using FastMCP, also add `FASTMCP_HOST: 0.0.0.0` and `FASTMCP_PORT: 8000` to the environment section.

Include **all** environment variables from the project's example.env.

## Step 7: Create example.env

```bash
# MCP transport: "stdio" for local dev, "sse" or "streamable-http" for Docker/remote
MCP_TRANSPORT=sse

# MCP network settings (used with SSE/streamable-http transport)
# MCP_HOST=0.0.0.0
# MCP_PORT=8000

# FastMCP only: FastMCP reads these specific env vars for host/port binding.
# Not needed for low-level SDK servers.
# FASTMCP_HOST=0.0.0.0
# FASTMCP_PORT=8000

# App-specific variables below
```

## Step 8: Update .gitignore

Add `VERSION` and `.env` entries.

## Step 9: Nginx Reverse Proxy (if applicable)

If the MCP server will be behind nginx with HTTPS, see [references/nginx-sse.md](references/nginx-sse.md) for the config snippet. SSE requires specific proxy settings to work correctly.

## MCP Endpoints

SSE transport exposes:
- `/sse` - SSE connection endpoint
- `/messages/` - Message posting endpoint

Streamable-http transport exposes:
- `/mcp` - Single endpoint

## Claude Code Client Configuration

Connect to a remote MCP server in `.mcp.json`:

```json
{
  "mcpServers": {
    "my-mcp": {
      "type": "http",
      "url": "https://server.example.com/my-mcp/sse",
      "headers": {
        "Authorization": "Bearer <token>"
      }
    }
  }
}
```

Auth is handled at the nginx layer via Bearer token headers. The MCP server does not need to know about authentication.

## Troubleshooting

**Container binds to 127.0.0.1 instead of 0.0.0.0 (FastMCP)** - FastMCP constructor defaults override env vars. Pass host/port explicitly in the FastMCP constructor (see Step 3, Path A).

**SSE connection stale after container restart** - Claude Code caches SSE connections. Reload Claude Code to establish a fresh connection.

**PyPI package version stale in Docker image** - Publish the new version to PyPI before running build-publish.sh. Verify with `docker exec {container} pip show {package}`.

**Missing uvicorn or starlette (low-level SDK)** - Low-level SDK servers need `uvicorn` and `starlette` in `requirements.txt`. FastMCP bundles these, but the low-level SDK does not.

**Wrong transport route (low-level SDK)** - SSE uses `/sse` and `/messages/`, streamable-http uses `/mcp`. These are NOT interchangeable. Make sure the client URL matches the transport configured on the server.

**"Session not found" errors behind nginx** - The MCP SDK's streamable-http transport is stateful by default. During initialization, the server assigns a session ID and expects the client to send it back via the `Mcp-Session-Id` header on every request. Behind a reverse proxy, this header can be dropped or the SSE connection that maintains the session can be interrupted, causing `"Session not found"` errors. Fix: set `stateless_http=True` (FastMCP) or `stateless=True` (low-level SDK `StreamableHTTPSessionManager`). This disables session tracking so each request is handled independently.
