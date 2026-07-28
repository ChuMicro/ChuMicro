# API Reference

## `chumicro_requests`

The error types every call can raise, the case-insensitive header dict, and the wire helpers (`encode_request`, `parse_url`, `parse_charset`, `resolve_redirect_url`, `ResponseParser`) for code that frames its own HTTP.

::: chumicro_requests

## `chumicro_requests.client`

`HttpClient` itself, the `RequestHandle` each call returns, the `Response` it resolves to, and the `WhenOversized` policy for bodies past `max_body_bytes`.  `from chumicro_requests import HttpClient` gives you the same class.

::: chumicro_requests.client

## `chumicro_requests.generators`

Opt-in submodule for `yield from` flows driven by `Runner.add_generator`.  `fetch` runs a whole request top to bottom and returns the `Response`; `get` / `post` / `put` / `patch` / `delete` are the per-verb forms.  For a body too big for RAM, `stream` returns a `BodyReader` you pull one chunk per `yield from`.  Import it explicitly; a program that never uses a generator never loads it.

::: chumicro_requests.generators

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests) · \
[PyPI](https://pypi.org/project/chumicro-requests/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
