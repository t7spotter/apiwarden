"""The mock API, the example generator behind it, and the curl builder."""

import json
import threading
import urllib.error
import urllib.request

import pytest

from apiwarden.cli import main
from apiwarden.curl import build_curl
from apiwarden.examples import example_for, media_example
from apiwarden.loader import load_registry
from apiwarden.mock import build_routes, make_server, respond


def call(registry, method, path, query=None, headers=None):
    return respond(registry, method, path, query or {}, headers or {})


def payload(response):
    return json.loads(response.body.decode())


# ---------------------------------------------------------------- examples


def test_example_prefers_what_the_spec_says():
    assert example_for({}, {"type": "string", "example": "hi"}) == "hi"
    assert example_for({}, {"type": "string", "enum": ["a", "b"]}) == "a"
    assert example_for({}, {"type": "integer", "default": 7}) == 7


def test_example_is_built_from_the_schema_and_is_stable():
    schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "count": {"type": "integer", "minimum": 5},
            "tags": {"type": "array", "items": {"type": "string"}},
            "when": {"type": "string", "format": "date-time"},
        },
    }
    value = example_for({}, schema)
    assert value == example_for({}, schema)
    assert value["count"] == 5
    assert value["tags"] == ["string"]
    assert value["when"].endswith("Z")


def test_example_resolves_refs_merges_allof_and_survives_cycles():
    spec = {
        "components": {
            "schemas": {
                "Base": {"type": "object", "properties": {"id": {"type": "integer"}}},
                "Node": {
                    "allOf": [
                        {"$ref": "#/components/schemas/Base"},
                        {"type": "object", "properties": {"next": {"$ref": "#/components/schemas/Node"}}},
                    ]
                },
            }
        }
    }
    value = example_for(spec, {"$ref": "#/components/schemas/Node"})
    assert value["id"] == 1  # merged from Base; the cyclic `next` is simply left out
    assert "next" not in value


def test_media_example_uses_examples_before_the_schema():
    media = {"examples": {"one": {"value": {"a": 1}}}, "schema": {"type": "string"}}
    assert media_example({}, media) == {"a": 1}


# ---------------------------------------------------------------- mock


def test_mock_answers_with_the_documented_success_example(registry):
    reply = call(registry, "GET", "/tasks/")
    assert reply.status == 200
    assert reply.headers["X-Mock-Operation"] == "listTasks"
    assert isinstance(payload(reply), list)


def test_mock_uses_the_lowest_2xx_and_empty_bodies_for_204(registry):
    assert call(registry, "POST", "/tasks/").status == 201
    deleted = call(registry, "DELETE", "/tasks/1/")
    assert deleted.status == 204 and deleted.body == b""


def test_mock_picks_another_documented_response_on_request(registry):
    assert call(registry, "GET", "/tasks/", query={"__code": "401"}).status == 401
    assert call(registry, "GET", "/tasks/", headers={"prefer": "code=401"}).status == 401


def test_mock_says_so_for_an_undocumented_response(registry):
    reply = call(registry, "GET", "/tasks/", query={"__code": "500"})
    assert reply.status == 501
    assert "200" in payload(reply)["documented"]


def test_mock_matches_path_parameters_and_tolerates_the_trailing_slash(registry):
    assert call(registry, "GET", "/tasks/abc/").status == 200
    assert call(registry, "GET", "/tasks/abc").status == 200
    assert call(registry, "GET", "/tasks").status == 200


def test_mock_404_lists_what_exists_and_405_lists_what_is_allowed(registry):
    missing = call(registry, "GET", "/nowhere")
    assert missing.status == 404
    assert "GET /tasks/" in payload(missing)["available"]

    wrong = call(registry, "PUT", "/tasks/")
    assert wrong.status == 405
    assert wrong.headers["Allow"] == "GET, POST"


def test_mock_preflight_echoes_the_requested_headers(registry):
    # `Access-Control-Allow-Headers: *` does not cover Authorization.
    reply = call(registry, "OPTIONS", "/tasks/", headers={"access-control-request-headers": "authorization,x-client-version"})
    assert reply.status == 204
    assert reply.headers["Access-Control-Allow-Headers"] == "authorization,x-client-version"
    assert reply.headers["Access-Control-Allow-Origin"] == "*"


def test_mock_routes_put_literal_paths_before_parameterised_ones(spec_copy):
    import yaml

    path = next(spec_copy.glob("apps/tasks/openapi.y*ml"))
    data = yaml.safe_load(path.read_text())
    data["paths"]["/tasks/mine/"] = {"get": {"operationId": "myTasks", "responses": {"200": {"description": "ok"}}}}
    path.write_text(yaml.safe_dump(data, sort_keys=False))

    registry = load_registry(spec_copy)
    assert call(registry, "GET", "/tasks/mine/").headers["X-Mock-Operation"] == "myTasks"
    assert build_routes(registry)[0].template != "/tasks/{task_id}/"


def test_mock_honours_a_servers_base_path(spec_copy):
    import yaml

    path = next(spec_copy.glob("apps/tasks/openapi.y*ml"))
    data = yaml.safe_load(path.read_text())
    data["servers"] = [{"url": "https://api.example.com/v2"}]
    path.write_text(yaml.safe_dump(data, sort_keys=False))

    registry = load_registry(spec_copy)
    assert call(registry, "GET", "/v2/tasks/").status == 200
    assert call(registry, "GET", "/tasks/").status == 200  # the prefix is optional


def test_mock_serves_over_http_and_rereads_the_specs(spec_copy):
    registry = load_registry(spec_copy)
    server = make_server(registry, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with urllib.request.urlopen(f"{base}/tasks/") as response:
            assert response.status == 200
            assert response.headers["Access-Control-Allow-Origin"] == "*"
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{base}/nowhere")
        assert caught.value.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_mock_command_refuses_an_empty_directory(tmp_path, capsys):
    assert main(["mock", str(tmp_path), "8799"]) == 1
    assert "no operations" in capsys.readouterr().err


# ---------------------------------------------------------------- curl


def test_curl_for_a_bodyless_operation(registry):
    command = build_curl(registry, "listTasks", "http://localhost:9000/")
    assert command.startswith("curl 'http://localhost:9000/tasks/'")  # no -X for GET, no double slash
    assert "-H 'X-Client-Version: 1.4.0'" in command  # the spec's own example
    # The token is a variable the shell expands, never a literal.
    assert '-H "Authorization: Bearer $TOKEN"' in command


def test_curl_for_a_write_has_method_headers_and_json_body(registry):
    command = build_curl(registry, "createTask")
    assert command.startswith("curl -X POST 'http://localhost:8000/tasks/'")
    assert "-H 'Content-Type: application/json'" in command
    body = command.split("-d '", 1)[1].rsplit("'", 1)[0]
    assert "title" in json.loads(body)


def test_curl_fills_path_parameters_and_skips_auth_when_public(registry):
    command = build_curl(registry, "getUser")
    assert "/users/ada/" in command and "{" not in command
    assert "Authorization" not in command


def test_curl_falls_back_to_a_variable_without_any_server(spec_copy):
    import yaml

    path = next(spec_copy.glob("apps/users/openapi.y*ml"))
    data = yaml.safe_load(path.read_text())
    data.pop("servers", None)
    path.write_text(yaml.safe_dump(data, sort_keys=False))

    command = build_curl(load_registry(spec_copy), "getUser")
    assert command.startswith('curl "$BASE_URL/users/ada/"')


def test_curl_quotes_the_server_it_is_given(registry):
    command = build_curl(registry, "getUser", "http://x.test/it's")
    assert "'\\''" in command


def test_curl_unknown_operation_is_none(registry):
    assert build_curl(registry, "doesNotExist") is None


def test_curl_is_served_as_text(portal, registry):
    from apiwarden.http import Request
    from apiwarden.router import handle

    response = handle(Request("GET", "/curl/listTasks.txt", query={"server": "http://localhost:9000"}), portal)
    assert response.status == 200
    assert response.headers["Content-Type"].startswith("text/plain")
    assert b"http://localhost:9000/tasks/" in response.body
    assert handle(Request("GET", "/curl/nope.txt"), portal).status == 404
