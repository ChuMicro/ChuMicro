# Nginx Reverse Proxy for MCP SSE Transport

## Location Block

Drop this into your nginx server block. Replace `{mcp_path}` with the desired URL prefix (e.g., `mcp-loki`, `my-mcp`).

```nginx
location /{mcp_path}/ {
    proxy_pass http://localhost:8000/;

    # Required for SSE streaming
    proxy_buffering off;
    proxy_cache off;
    chunked_transfer_encoding off;

    # HTTP/1.1 with persistent connection
    proxy_http_version 1.1;
    proxy_set_header Connection '';

    # Standard proxy headers
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # SSE connections are long-lived
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
```

## Why These Settings Matter

- **proxy_buffering off** - SSE events must stream immediately; buffering delays delivery
- **proxy_cache off** - Caching SSE streams breaks real-time communication
- **chunked_transfer_encoding off** - Prevents nginx from re-chunking the SSE stream
- **proxy_http_version 1.1** + **Connection ''** - Keeps the connection alive for persistent SSE
- **proxy_read_timeout 3600s** - SSE connections are long-lived; default 60s timeout kills them

## Authentication

Add Bearer token authentication at the nginx layer:

```nginx
location /{mcp_path}/ {
    # Validate Bearer token
    if ($http_authorization != "Bearer YOUR_TOKEN_HERE") {
        return 401;
    }

    proxy_pass http://localhost:8000/;
    # ... rest of config ...
}
```

Or use a more robust auth module. The MCP server itself does not handle authentication.

## HTTPS

Standard nginx HTTPS config works. SSE and streamable-http both work over HTTPS with no special SSL settings needed.

## Client URL

With this nginx config, the Claude Code `.mcp.json` URL would be:
- SSE: `https://server.example.com/{mcp_path}/sse`
- Streamable-http: `https://server.example.com/{mcp_path}/mcp`
