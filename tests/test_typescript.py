"""TypeScript types generated from the specs."""

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from apiwarden.build import build_static
from apiwarden.cli import main
from apiwarden.config import Config
from apiwarden.http import Request
from apiwarden.loader import load_registry
from apiwarden.router import handle
from apiwarden.typescript import type_name, typescript_for


def generate(registry, name):
    return typescript_for(registry.specs[name])


ODD_SPEC = """
openapi: 3.0.3
info: {title: Odd API, version: '1'}
paths:
  /things/{id}/:
    parameters:
      - {name: id, in: path, required: true, schema: {type: integer}}
    get:
      operationId: get-thing
      parameters:
        - {name: limit, in: query, schema: {type: integer}, description: "At most */ this many."}
        - {name: tags, in: query, schema: {type: array, items: {type: string}}}
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema: {$ref: '#/components/schemas/Thing'}
    post:
      operationId: 2ndThing
      requestBody:
        $ref: '#/components/requestBodies/ThingBody'
      responses:
        200: {$ref: '#/components/responses/Plain'}
components:
  requestBodies:
    ThingBody:
      content:
        application/json:
          schema: {oneOf: [{$ref: '#/components/schemas/Thing'}, {type: string}]}
  responses:
    Plain:
      description: ok
      content:
        application/json:
          schema: {type: array, items: {oneOf: [{type: string}, {type: integer}]}}
  schemas:
    Node:
      type: object
      description: "A tree node. Ends with */ on purpose."
      required: [value]
      properties:
        value: {type: string, nullable: true}
        child: {$ref: '#/components/schemas/Node'}
        "x-weird key": {type: integer, enum: [1, 2, 3]}
        1st: {type: boolean}
    Thing:
      allOf:
        - $ref: '#/components/schemas/Node'
        - type: object
          properties:
            blob: {type: string, format: binary}
            meta: {type: object, additionalProperties: true}
            either: {anyOf: [{type: string}, {type: integer}]}
            list: {type: array, items: {oneOf: [{type: string}, {type: integer}]}}
            modern: {type: [string, "null"]}
            fixed: {const: hello}
            old: {type: string, deprecated: true}
    Free: {}
    Alias: {$ref: '#/components/schemas/Node'}
"""


@pytest.fixture
def odd(tmp_path):
    spec = tmp_path / "apps" / "odd" / "openapi.yaml"
    spec.parent.mkdir(parents=True)
    spec.write_text(ODD_SPEC)
    return load_registry(tmp_path)


def test_every_component_schema_becomes_a_type(registry):
    out = generate(registry, "tasks")
    assert "export interface Task {" in out
    assert 'priority?: "low" | "medium" | "high";' in out
    # `required` decides which properties are optional.
    assert "export interface TaskCreate {\n  title: string;" in out
    # additionalProperties becomes an index signature.
    assert "[key: string]: string[];" in out


def test_operations_get_params_request_and_response_types(registry):
    out = generate(registry, "tasks")
    assert "export type ListTasksResponse = Task[];" in out
    assert "export type CreateTaskRequest = TaskCreate;" in out
    assert "export type CreateTaskResponse = Task;" in out  # the lowest 2xx, not the 400
    assert "export interface GetTaskParams {\n  task_id: string;" in out
    # No body and no params: nothing to say, so nothing is emitted.
    assert "DeleteTaskResponse" not in out and "ListTasksParams" not in out


def test_output_is_deterministic_and_carries_no_hash_or_timestamp(registry):
    first = generate(registry, "tasks")
    assert first == generate(registry, "tasks")
    assert "rev " not in first.splitlines()[0]


def test_descriptions_become_jsdoc_and_cannot_close_the_comment(odd):
    out = generate(odd, "odd")
    assert "A tree node. Ends with *\\/ on purpose." in out
    assert "/** @deprecated */" in out


def test_shapes_unions_intersections_nullable_and_cycles(odd):
    out = generate(odd, "odd")
    assert "child?: Node;" in out  # a cycle is a reference, not an expansion
    assert "value: string | null;" in out
    assert '"x-weird key"?: 1 | 2 | 3;' in out and '"1st"?: boolean;' in out
    assert "export type Thing = Node & {" in out
    assert "list?: (string | number)[];" in out
    assert "modern?: string | null;" in out  # OpenAPI 3.1 type lists
    assert 'fixed?: "hello";' in out
    assert "blob?: Blob;" in out
    assert "export type Free = unknown;" in out
    assert "export type Alias = Node;" in out


def test_operation_ids_and_response_refs_are_handled(odd):
    out = generate(odd, "odd")
    assert "export interface GetThingParams {" in out
    assert "limit?: number;" in out and "id: number;" in out
    assert "export type _2ndThingRequest = Thing | string;" in out  # a $ref'd request body, and a leading digit
    assert "export type _2ndThingResponse = (string | number)[];" in out  # an unquoted `200:` key and a $ref'd response


def test_type_names():
    assert type_name("listTasks") == "ListTasks"
    assert type_name("get-thing") == "GetThing"
    assert type_name("2nd") == "_2nd"
    assert type_name("a.b/c") == "ABC"


@pytest.mark.skipif(
    not (os.environ.get("APIWARDEN_TSC") or shutil.which("tsc")),
    reason="no TypeScript compiler; set APIWARDEN_TSC or install tsc",
)
def test_generated_types_compile_under_strict(odd, registry, tmp_path):
    for registry_, name in ((odd, "odd"), (registry, "tasks"), (registry, "users")):
        (tmp_path / f"{name}.ts").write_text(generate(registry_, name))
    command = shlex.split(os.environ.get("APIWARDEN_TSC") or "tsc")
    result = subprocess.run(
        [*command, "--noEmit", "--strict", "--target", "es2020", *sorted(str(p) for p in tmp_path.glob("*.ts"))],
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------- serving


def test_types_are_served_as_text(portal, registry):
    response = handle(Request("GET", "/types/tasks.ts"), portal)
    assert response.status == 200
    assert response.headers["Content-Type"].startswith("text/plain")
    assert b"export interface Task " in response.body
    assert handle(Request("GET", "/types/nope.ts"), portal).status == 404


def test_api_page_links_to_its_types(portal, registry):
    markup = handle(Request("GET", "/tasks/"), portal).body.decode()
    assert 'href="/types/tasks.ts"' in markup


def test_llms_txt_mentions_the_types_endpoint(portal):
    assert "/types/<api>.ts" in handle(Request("GET", "/llms.txt"), portal).body.decode()


def test_types_command_writes_one_file_per_spec(sample_root, tmp_path, capsys):
    assert main(["types", str(sample_root), "-o", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "tasks.ts").read_text().startswith("// Generated by apiwarden")
    assert (tmp_path / "out" / "users.ts").exists()
    capsys.readouterr()


def test_types_command_refuses_an_empty_directory(tmp_path, capsys):
    assert main(["types", str(tmp_path), "-o", str(tmp_path / "out")]) == 1
    assert "no usable specs" in capsys.readouterr().err


def test_static_build_includes_the_types(config, tmp_path):
    build_static(config, tmp_path / "dist")
    assert (tmp_path / "dist" / "types" / "tasks.ts").read_text().count("export interface") >= 3
