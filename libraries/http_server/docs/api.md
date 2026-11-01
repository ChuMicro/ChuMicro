# API Reference

`HttpServer`, under `chumicro_http_server.server`, is the class to start with: `@server.route(path)` registers a handler that takes a `Request` and returns a `Response` from `build_response`.  `from chumicro_http_server import HttpServer` loads the same class.  `chumicro_http_server` holds the request parser, the error types, and the default size limits.  `chumicro_http_server.streaming` sends a response body piece by piece.

## `chumicro_http_server`

::: chumicro_http_server

## `chumicro_http_server.server`

::: chumicro_http_server.server

## `chumicro_http_server.streaming`

::: chumicro_http_server.streaming
    options:
      members:
        - StreamingResponse
        - build_streaming_response
        - encode_streaming_headers

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server) · \
[PyPI](https://pypi.org/project/chumicro-http-server/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
