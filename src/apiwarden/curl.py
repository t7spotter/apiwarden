"""A ready-to-run curl command for one operation, for "Copy as curl".

Built from the spec, not from the page, so a person and an agent get the same
command. Secrets are never filled in here: the server does not know the
reader's token (it lives in their browser), so credentials come out as shell
variables — `$TOKEN`, `$API_KEY` — which the browser may swap for the real
value when the reader asks for it.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urlencode

from .examples import example_for, json_media, media_example
from .index import find_operation, operation_auth
from .loader import Registry, resolve_deep


def _quote(value: str) -> str:
    """Single-quote for a POSIX shell."""
    return "'" + value.replace("'", "'\\''") + "'"


def _explicit(param: dict[str, Any]) -> Any:
    """What the spec itself offers as a value for a parameter, if anything."""
    schema = param.get("schema") if isinstance(param.get("schema"), dict) else {}
    for source in (param, schema):
        for key in ("example", "default"):
            if key in source:
                return source[key]
    examples = param.get("examples")
    if isinstance(examples, dict) and examples:
        first = next(iter(examples.values()))
        if isinstance(first, dict) and "value" in first:
            return first["value"]
    if schema.get("enum"):
        return schema["enum"][0]
    return None


def _value(spec_data: dict[str, Any], param: dict[str, Any]) -> str:
    """A value for the parameter: the spec's own, a <placeholder>, or a typed example."""
    found = _explicit(param)
    if found is not None:
        return _text(found)
    schema = param.get("schema") if isinstance(param.get("schema"), dict) else {}
    if schema.get("type") in (None, "string") and not schema.get("format"):
        return f"<{param.get('name', 'value')}>"
    return _text(example_for(spec_data, schema))


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(_text(v) for v in value)
    return str(value)


def build_curl(registry: Registry, operation_id: str, server: str | None = None) -> str | None:
    found = find_operation(registry, operation_id)
    if not found:
        return None
    spec, url, method, operation = found
    data = spec.data

    base = (server or "").strip()
    if not base:
        servers = [s.get("url") for s in data.get("servers", []) if isinstance(s, dict) and s.get("url")]
        base = servers[0] if servers else "$BASE_URL"
    base = base.rstrip("/")

    params = [p for p in resolve_deep(data, operation.get("parameters", [])) if isinstance(p, dict)]

    path = url
    for param in params:
        if param.get("in") == "path":
            path = path.replace("{" + str(param.get("name")) + "}", quote(_value(data, param), safe="<>"))

    query = [(p["name"], _value(data, p)) for p in params if p.get("in") == "query" and p.get("required")]
    headers = [(p["name"], _value(data, p)) for p in params if p.get("in") == "header" and p.get("required")]

    flags: list[str] = []  # everything after the URL, one per line
    auth = _auth(registry, spec, operation, query)
    flags.extend(auth)

    target = base + path
    if query:
        target += "?" + urlencode(query, safe="<>,")

    for name, value in headers:
        flags.append(f"-H {_quote(f'{name}: {value}')}")

    body = _body(data, operation)
    if body:
        flags.extend(body)

    lines = [f"curl{'' if method.upper() == 'GET' else ' -X ' + method.upper()} {_quote(target)}"]
    # A $VAR in the URL has to stay outside the single quotes to expand.
    if target.startswith("$BASE_URL"):
        lines[0] = lines[0].replace(_quote(target), '"' + target + '"')
    lines.extend(flags)
    return " \\\n  ".join(lines)


def _auth(registry: Registry, spec, operation: dict[str, Any], query: list[tuple[str, str]]) -> list[str]:
    if operation_auth(spec, operation) == "public":
        return []

    security = operation.get("security", spec.data.get("security")) or []
    schemes = spec.data.get("components", {}).get("securitySchemes", {})
    name = next((n for entry in security if isinstance(entry, dict) for n in entry), None)
    scheme = schemes.get(name, {}) if name else {}

    if scheme.get("type") == "http" and str(scheme.get("scheme", "")).lower() == "basic":
        return ['-u "$USERNAME:$PASSWORD"']
    if scheme.get("type") == "http":
        return ['-H "Authorization: Bearer $TOKEN"']
    if scheme.get("type") == "apiKey":
        key = scheme.get("name", "X-API-Key")
        where = scheme.get("in", "header")
        if where == "query":
            query.append((key, "$API_KEY"))
            return []
        if where == "cookie":
            return [f'-b "{key}=$API_KEY"']
        return [f'-H "{key}: $API_KEY"']
    # OAuth2, OpenID Connect and anything unfamiliar all travel as a bearer token.
    return ['-H "Authorization: Bearer $TOKEN"']


def _body(data: dict[str, Any], operation: dict[str, Any]) -> list[str]:
    request = resolve_deep(data, operation.get("requestBody") or {})
    chosen = json_media(request.get("content") if isinstance(request, dict) else None)
    if chosen is None:
        return []

    mime, media = chosen
    kind = mime.split(";")[0].strip().lower()
    value = media_example(data, media)
    if value is None:
        return []

    if kind == "application/json" or kind.endswith("+json"):
        return [f"-H {_quote('Content-Type: ' + kind)}", f"-d {_quote(json.dumps(value, indent=2, ensure_ascii=False))}"]
    if kind == "application/x-www-form-urlencoded" and isinstance(value, dict):
        return [f"--data-urlencode {_quote(f'{k}={_text(v)}')}" for k, v in value.items()]
    if kind == "multipart/form-data" and isinstance(value, dict):
        return [f"-F {_quote(f'{k}={_text(v)}')}" for k, v in value.items()]
    return [f"-H {_quote('Content-Type: ' + kind)}", f"-d {_quote(value if isinstance(value, str) else json.dumps(value))}"]
