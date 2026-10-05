"""Turn an OpenAPI schema into a realistic example value.

Used by the mock server and by "Copy as curl", so both agree on what a request
or a response looks like when the spec gives no example of its own. The output
is deterministic — the same schema always gives the same example — so a mock
answer does not change between refreshes and a copied command is diffable.
"""

from __future__ import annotations

from typing import Any

from .loader import resolve_ref

# How deep to expand nested objects before giving up. Real schemas are shallow;
# this is what stops a self-referential one.
MAX_DEPTH = 6

_STRING_FORMATS = {
    "date-time": "2026-01-01T00:00:00Z",
    "date": "2026-01-01",
    "time": "00:00:00",
    "uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "email": "user@example.com",
    "uri": "https://example.com",
    "url": "https://example.com",
    "hostname": "example.com",
    "ipv4": "192.0.2.1",
    "ipv6": "2001:db8::1",
    "byte": "c3RyaW5n",
    "password": "********",
}


def example_for(spec_data: dict[str, Any], schema: Any, _seen: frozenset[str] = frozenset(), _depth: int = 0) -> Any:
    """An example value for `schema`, preferring whatever the spec itself says."""
    if not isinstance(schema, dict) or _depth > MAX_DEPTH:
        return None

    ref = schema.get("$ref")
    if isinstance(ref, str):
        if ref in _seen:
            return None  # a cycle: leave the branch out rather than recurse forever
        try:
            target = resolve_ref(spec_data, ref)
        except (KeyError, IndexError, ValueError):
            return None
        return example_for(spec_data, target, _seen | {ref}, _depth)

    for key in ("example", "const", "default"):
        if key in schema:
            return schema[key]
    if schema.get("enum"):
        return schema["enum"][0]

    if schema.get("allOf"):
        merged: dict[str, Any] = {}
        for part in schema["allOf"]:
            value = example_for(spec_data, part, _seen, _depth)
            if isinstance(value, dict):
                merged.update(value)
            elif value is not None and not merged:
                return value
        return merged
    for key in ("oneOf", "anyOf"):
        if schema.get(key):
            return example_for(spec_data, schema[key][0], _seen, _depth)

    kind = schema.get("type")
    if isinstance(kind, list):  # OpenAPI 3.1: ["string", "null"]
        kind = next((k for k in kind if k != "null"), "null")
    if kind is None:
        kind = "object" if "properties" in schema else "array" if "items" in schema else None

    if kind == "object":
        out: dict[str, Any] = {}
        for name, sub in (schema.get("properties") or {}).items():
            value = example_for(spec_data, sub, _seen, _depth + 1)
            if value is not None or _nullable(sub):
                out[name] = value
        extra = schema.get("additionalProperties")
        if not out and isinstance(extra, dict):
            value = example_for(spec_data, extra, _seen, _depth + 1)
            if value is not None:
                out["key"] = value
        return out

    if kind == "array":
        item = example_for(spec_data, schema.get("items"), _seen, _depth + 1)
        return [] if item is None else [item]

    if kind == "string":
        return _string(schema)
    if kind == "integer":
        return _number(schema, 1)
    if kind == "number":
        return _number(schema, 1.5)
    if kind == "boolean":
        return True
    if kind == "null":
        return None
    return None


def _nullable(schema: Any) -> bool:
    return isinstance(schema, dict) and schema.get("nullable") is True


def _string(schema: dict[str, Any]) -> str:
    value = _STRING_FORMATS.get(schema.get("format", ""), "string")
    minimum, maximum = schema.get("minLength"), schema.get("maxLength")
    if isinstance(minimum, int) and len(value) < minimum:
        value = value + "x" * (minimum - len(value))
    if isinstance(maximum, int) and len(value) > maximum:
        value = value[:maximum]
    return value


def _number(schema: dict[str, Any], fallback: float) -> Any:
    value: Any = fallback
    low, high = schema.get("minimum"), schema.get("maximum")
    if isinstance(low, (int, float)) and value < low:
        value = low
    if isinstance(high, (int, float)) and value > high:
        value = high
    return value


def media_example(spec_data: dict[str, Any], media: Any) -> Any:
    """The example for one media-type object: its own, else one made from its schema."""
    if not isinstance(media, dict):
        return None
    if "example" in media:
        return media["example"]

    examples = media.get("examples")
    if isinstance(examples, dict) and examples:
        first = next(iter(examples.values()))
        if isinstance(first, dict) and isinstance(first.get("$ref"), str):
            try:
                first = resolve_ref(spec_data, first["$ref"])
            except (KeyError, IndexError, ValueError):
                first = None
        if isinstance(first, dict) and "value" in first:
            return first["value"]

    return example_for(spec_data, media.get("schema"))


def json_media(content: Any) -> tuple[str, Any] | None:
    """The JSON media type of a `content` map, else the first one, else nothing."""
    if not isinstance(content, dict) or not content:
        return None
    for mime, media in content.items():
        if mime.split(";")[0].strip().lower() == "application/json" or mime.endswith("+json"):
            return mime, media
    mime = next(iter(content))
    return mime, content[mime]
