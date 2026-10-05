"""A mock API served straight from the specs, for `apiwarden mock`.

Every documented operation answers with the example its spec gives (or one made
from its schema), so a frontend can be built against an endpoint before the
backend exists — and the mock cannot drift from the docs, because it is read
from the same files. Point the portal's Try it at it, or point the app at it.

Choosing a response: the lowest documented 2xx by default. `Prefer: code=404`
(or `?__code=404`) picks another documented one, so error handling can be
exercised too.
"""

from __future__ import annotations

import errno
import json
import re
import sys
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit, urlparse

from .examples import json_media, media_example
from .loader import Registry, Spec, reload_if_changed, resolve_ref

_PARAM = re.compile(r"\{([^/{}]+)\}")


@dataclass
class Route:
    method: str
    template: str
    pattern: re.Pattern[str]
    spec: Spec
    operation: dict[str, Any]

    @property
    def operation_id(self) -> str:
        return str(self.operation.get("operationId") or f"{self.method} {self.template}")


@dataclass
class MockResponse:
    status: int
    headers: dict[str, str]
    body: bytes


def _server_prefix(spec: Spec) -> str:
    """The path part of the spec's first server: https://x.io/api/v1 -> /api/v1."""
    for server in spec.data.get("servers") or []:
        if isinstance(server, dict) and isinstance(server.get("url"), str):
            url = _PARAM.sub("x", server["url"])  # server variables, e.g. {version}
            return urlparse(url).path.rstrip("/")
    return ""


def _compile(prefix: str, template: str) -> re.Pattern[str]:
    parts, last = [], 0
    for found in _PARAM.finditer(template):
        parts.append(re.escape(template[last : found.start()]))
        parts.append("[^/]+")
        last = found.end()
    parts.append(re.escape(template[last:]))
    body = "".join(parts).rstrip("/")
    # The server's base path is optional, and so is a trailing slash: a mock
    # that 404s over either would be stricter than the real API usually is.
    head = f"(?:{re.escape(prefix)})?" if prefix else ""
    return re.compile(f"^{head}{body}/?$")


def build_routes(registry: Registry) -> list[Route]:
    routes: list[Route] = []
    for name in registry.names():
        spec = registry.specs[name]
        if spec.error:
            continue
        prefix = _server_prefix(spec)
        for template, method, operation, _shared in spec.operations():
            routes.append(Route(method.upper(), template, _compile(prefix, template), spec, operation))
    # `/users/me` has to beat `/users/{id}`.
    routes.sort(key=lambda r: (len(_PARAM.findall(r.template)), -len(r.template)))
    return routes


def _resolve(spec: Spec, node: Any) -> Any:
    if isinstance(node, dict) and isinstance(node.get("$ref"), str):
        try:
            return resolve_ref(spec.data, node["$ref"])
        except (KeyError, IndexError, ValueError):
            return {}
    return node


def documented_codes(route: Route) -> list[str]:
    return [str(code) for code in (route.operation.get("responses") or {})]


def default_code(route: Route) -> str | None:
    """Lowest documented 2xx; else `default`; else whatever comes first."""
    codes = documented_codes(route)
    successes = sorted(c for c in codes if c.isdigit() and c.startswith("2"))
    if successes:
        return successes[0]
    if "default" in codes:
        return "default"
    return codes[0] if codes else None


def _status_of(code: str) -> int:
    if code.isdigit():
        return int(code)
    return 200  # "default" and range wildcards such as "4XX" have no single status


def _wants_code(headers: dict[str, str], query: dict[str, str]) -> str | None:
    if query.get("__code"):
        return query["__code"].strip()
    found = re.search(r"\bcode=(\w+)", headers.get("prefer", ""))
    return found.group(1) if found else None


_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS",
    "Access-Control-Expose-Headers": "X-Mock-Operation, X-Mock-Status",
    "Access-Control-Max-Age": "600",
}


def _json(status: int, payload: Any, extra: dict[str, str] | None = None) -> MockResponse:
    headers = {"Content-Type": "application/json; charset=utf-8", **_CORS, **(extra or {})}
    return MockResponse(status, headers, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))


def respond(registry: Registry, method: str, raw_path: str, query: dict[str, str], headers: dict[str, str]) -> MockResponse:
    method = method.upper()

    if method == "OPTIONS":
        # `Access-Control-Allow-Headers: *` does not cover Authorization, so the
        # preflight is answered by echoing back exactly what the browser asked
        # for — the one form that always works.
        asked = headers.get("access-control-request-headers", "authorization, content-type")
        return MockResponse(204, {**_CORS, "Access-Control-Allow-Headers": asked}, b"")

    path = unquote(raw_path) or "/"
    routes = build_routes(registry)
    matching = [r for r in routes if r.pattern.match(path)]

    if not matching:
        return _json(404, {"error": f"no operation for {method} {path}", "available": [f"{r.method} {r.template}" for r in routes]})

    route = next((r for r in matching if r.method == method or (method == "HEAD" and r.method == "GET")), None)
    if route is None:
        allowed = sorted({r.method for r in matching})
        return _json(405, {"error": f"{method} is not documented for {path}", "allowed": allowed}, {"Allow": ", ".join(allowed)})

    wanted = _wants_code(headers, query)
    code = wanted or default_code(route)
    # YAML turns an unquoted `200:` into an int key; compare everything as text.
    by_code = {str(k): v for k, v in (route.operation.get("responses") or {}).items()}
    if code is None or code not in by_code:
        return _json(
            501,
            {"error": f"{route.operation_id} documents no {code or 'response'} response", "documented": documented_codes(route)},
            {"X-Mock-Operation": route.operation_id},
        )

    response = _resolve(route.spec, by_code[code])
    status = _status_of(str(code))
    meta = {"X-Mock-Operation": route.operation_id, "X-Mock-Status": str(code)}

    chosen = json_media((response or {}).get("content"))
    if chosen is None or status in (204, 304):
        return MockResponse(status, {**_CORS, **meta}, b"")

    mime, media = chosen
    value = media_example(route.spec.data, media)
    if mime.split(";")[0].strip().lower() == "application/json" or mime.endswith("+json"):
        return _json(status, value, meta)
    body = value if isinstance(value, str) else json.dumps(value)
    return MockResponse(status, {"Content-Type": mime, **_CORS, **meta}, body.encode("utf-8"))


# ---------------------------------------------------------------- server


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    registry: Registry
    sources: dict[str, str] | None = None

    def _serve(self) -> None:
        reload_if_changed(self.registry, self.sources)
        parts = urlsplit(self.path)
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        headers = {k.lower(): v for k, v in self.headers.items()}
        length = int(headers.get("content-length") or 0)
        if length:
            self.rfile.read(min(length, 4 * 1024 * 1024))  # drained, never inspected

        try:
            reply = respond(self.registry, self.command, parts.path, query, headers)
        except Exception as exc:  # keep the mock up
            self.log_error("mock failed: %s", exc)
            reply = _json(500, {"error": "mock failed", "detail": str(exc)})

        self.send_response(reply.status)
        for key, value in reply.headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(reply.body)))
        self.end_headers()
        if self.command != "HEAD" and reply.body:
            self.wfile.write(reply.body)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _serve

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write(f"  mock  {self.address_string()} {format % args}\n")


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(registry: Registry, host: str, port: int, sources: dict[str, str] | None = None) -> ThreadingHTTPServer:
    handler = type("Handler", (_Handler,), {"registry": registry, "sources": sources})
    try:
        return _Server((host, port), handler)
    except OSError as exc:
        hint = ""
        if getattr(exc, "errno", None) in (errno.EADDRINUSE, errno.EACCES):
            hint = f"\n  something else is on that port — try: apiwarden mock {port + 1}"
        raise SystemExit(f"cannot bind {host}:{port} — {exc}{hint}") from exc
