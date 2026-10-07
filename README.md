<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-lockup-dark.svg">
    <img src="assets/logo-lockup.svg" alt="APIwarden" height="110">
  </picture>
</p>

# apiwarden

Point it at a directory of OpenAPI specs and it serves them as live
documentation — a browsable site for people, and an MCP server plus plain JSON
for AI agents. Nothing to export, nothing to re-share: the specs are read from
disk on every request, so whatever is on the branch is what the docs say.

Runs standalone, or mounts into an existing Django project in two lines.

```
pip install apiwarden
apiwarden serve ./api-docs
```

## Why

API documentation that lives in files has to be sent to whoever needs it, again
after every change. A frontend team ends up working from whichever copy they
were last given, and no one can tell what moved. Serving the specs instead of
sending them makes that whole problem go away: one URL, always current, for
people and for the agents they work with.

## The two audiences

**People** get a portal built on [RapiDoc](https://github.com/rapi-doc/RapiDoc):
a nav of colour-coded methods and URL paths, the read layout, server selection
and try-it. On top of that it adds an API switcher and search across every
spec, and it rescues the two things OpenAPI renderers normally drop — the
`info.description` narrative, which becomes navigable headings, and the
top-level `x-*` blocks where teams record rate limits, TTLs and everything else
that does not fit the schema, which become tables in the overview.

Press **Ctrl+K** (⌘K on a Mac, or `/`) anywhere for the command palette: type to
search operations across every API, jump to an API, or run an action — switch
theme, set the token, open the changes log, open the raw spec or types. Start
with `>` to see actions only. **Enter** opens the selected row; **Ctrl+Enter**
on an operation copies its curl command.

Each reader can switch the portal between **Auto** (follows the system),
**Light** and **Dark** with the toggle in the sidebar or top bar. The choice is
kept in the browser and wins over the `theme` setting, which then only decides
what a first-time reader sees.

Every operation has **Copy link** (straight to that operation), **Copy as
curl** and **History** under its method and path. History opens the changes log
narrowed to that one operation, with a count of how many entries mention it.

The curl command is built from the spec, uses the server currently selected in
the sidebar, and writes credentials as shell variables (`$TOKEN`, `$API_KEY`) so
nothing secret lands in a chat or a bug report by accident. Shift-click to fill
in the token you set in the sidebar.

The sidebar also holds one Bearer token field, not one per spec. Set it once
and it applies to try-it on every API — it lives in the browser's
`localStorage`, never on the server, so it survives switching between APIs
without being re-entered.

Try it can also be pointed somewhere else without touching the specs: type an
address like `localhost:8000` into the sidebar's server field and press Add. It
joins the server dropdown, is selected straight away, and is remembered in the
browser the same way the token is. (`servers` in the config sets what everyone
sees; this is each reader's own.)

An edit to a spec reaches an open page in about a second, swapped in through
the renderer rather than by reloading, so nobody loses their place.

**Agents** get the same content as data:

| Endpoint | What it is |
|---|---|
| `POST /mcp` | MCP server — `list_apis`, `search_operations`, `get_operation`, `get_schema`, `get_conventions`, `list_changes`, `get_spec` |
| `GET /index.json` | Every operation across every spec, one compact document |
| `GET /llms.txt`, `/llms-full.txt` | The doc set as plain text |
| `GET /openapi/<name>.json`, `.yaml` | The raw specs, byte-faithful |
| `GET /display/<name>.json` | The renderer's copy: `x-*` folded into the overview |
| `GET /operation/<id>.json` | One operation, `$ref`s inlined |
| `GET /types/<name>.ts` | TypeScript types for one spec: every schema, plus `<Operation>Params`, `Request` and `Response` |
| `GET /curl/<id>.txt` | A ready-to-run curl command for one operation (`?server=` picks the base URL) |
| `GET /revision.json` | Content hashes — poll to tell whether anything changed |
| `GET /changes.json` | The changelog, newest first; `?since=…` compares against one baseline |

Point an agent at the MCP endpoint once and it never reads a stale spec again:

```json
{
  "mcpServers": {
    "apiwarden": { "type": "http", "url": "https://your-host/api-docs/mcp" }
  }
}
```

Locally, over stdio instead:

```
apiwarden mcp ./api-docs
```

## Standalone

```
apiwarden serve ./api-docs              # http://127.0.0.1:8080, reloads as you edit
apiwarden types ./api-docs -o src/api   # TypeScript types, one <api>.ts per spec
apiwarden mock ./api-docs               # http://127.0.0.1:8000, answers from the specs' examples
apiwarden check ./api-docs              # lint: operationIds, summaries, unresolved $refs
apiwarden build ./api-docs -o dist/     # self-contained static copy, for CI publishing
apiwarden changes ./api-docs --since v1.4.0
apiwarden snapshot ./api-docs -o baseline.json
```

`serve` takes a directory, a port, or both, in either order — a bare number is
read as a port, so the common case of "same specs, different port" is short:

```
apiwarden serve 8081                    # default directory, port 8081
apiwarden serve ./api-docs 8081         # both
apiwarden serve ./api-docs --port 8081  # the explicit form, still fine
```

It watches the spec files and pushes a reload to open browsers, so editing a
spec updates the page without a restart.

### A mock API

`apiwarden mock` serves every documented operation from the specs themselves, so
a frontend can be built against an endpoint before the backend exists — and the
mock cannot drift from the docs. Each operation answers with the example its spec
gives, or one built from its schema, and the specs are re-read on every request.
Add `localhost:8000` in the portal's server field and Try it talks to it.

```
curl http://localhost:8000/tasks/                    # the lowest documented 2xx
curl 'http://localhost:8000/tasks/?__code=401'       # another documented response
curl -H 'Prefer: code=401' http://localhost:8000/tasks/   # the same, as a header
```

It answers CORS preflights, honours the server's base path (`/v1`) but does not
require it, and says what it does and does not document in its 404, 405 and 501
replies. It does not validate requests or keep state.

### TypeScript types

The types a frontend writes by hand go stale the moment a schema changes. Fetch
them instead, in the build, and a change reaches the compiler:

```
curl https://your-host/api-docs/types/tasks.ts -o src/api/tasks.ts
apiwarden types ./api-docs -o src/api     # or, from a checkout of the specs
```

```ts
export interface TaskCreate {
  title: string;
  priority?: "low" | "medium" | "high";
}

/** POST /tasks/ — request body */
export type CreateTaskRequest = TaskCreate;
/** POST /tasks/ — 201 response */
export type CreateTaskResponse = Task;
```

Every component schema becomes a type (`required` decides what is optional;
`allOf`, `oneOf`, `nullable`, enums and recursive schemas are handled), and each
operation gets `<OperationId>Params` for its path and query parameters,
`<OperationId>Request` for the JSON body and `<OperationId>Response` for the
lowest documented success. The file carries no timestamp or hash, so it changes
only when a type or a description does, and committing it makes a diff of the
file show exactly what moved. A static `build` includes them too.

## What changed

Being always current is only half the problem — the other half is knowing what
moved. apiwarden keeps a changelog by itself: whenever a spec changes — an edit
while it is serving, or a new deploy noticed at startup — it compares the API
contract against the last one it saw and records the difference with a
timestamp. Open `/changes` and the history is there, newest first, each change
sorted by what it does to a caller. There is nothing to tag or configure.

```
$ apiwarden changes ./api-docs
2026-10-05 14:32  (2 breaking, 0 additive, 1 informational)
  breaking  accounts POST /v1/accounts/otp/     field-added: request.device_id (required)
  breaking  accounts POST /v1/accounts/otp/     response-removed: 429 no longer documented
  info      accounts POST /v1/accounts/otp/     summary-changed: Send a one-time login code.
```

**Breaking** is an operation or field disappearing, a new required field or
parameter, a type change, an enum value being removed, or authentication being
added. **Additive** is anything a current caller can ignore. Only the contract
counts: rewording a description is not logged. Saves less than 15 minutes apart
fold into one entry, and an edit undone within that window leaves no trace.

The log lives in your cache directory (`~/.cache/apiwarden/`), so the spec
directory is never written to. Set `history` to a path on persistent storage to
keep it across container rebuilds. On the very first run, if the specs are in a
git checkout, the recent commits that touched them are read once to seed it.

A reader also sees what is new *to them*: each page compares the changelog with
the last point that browser has seen (kept in `localStorage`, like the token) and
badges the Changes link, the API switcher, the landing cards, and the changed
operations in the nav. Opening Changes, or "Mark as seen", clears them. The first
visit shows nothing as new.

To compare against one specific version instead — a release tag, a commit, or a
file written earlier with `apiwarden snapshot` — pass `--since` (or `?since=` on
the page). `--fail-on-breaking` exits non-zero, so CI can gate on it:

```
$ apiwarden changes ./api-docs --since v1.4.0 --fail-on-breaking
```

Comparing against a revision needs `git` on the machine running apiwarden and the
specs inside a repository. In a slim container that has neither, the page says so
and offers only snapshot files: write one with `apiwarden snapshot` where git is
available, put it where the server can read it, and give its path as the baseline.

The same history is in `/changes.json` and the `list_changes` MCP tool, so an
agent can answer "will this break my client?" directly.

## In a Django project

```python
# settings.py
INSTALLED_APPS += ["apiwarden"]

APIWARDEN = {
    "root": BASE_DIR / "api-docs",
    "title": "Platform API",
    "servers": ["https://api.example.com"],   # what try-it should call
    "watch": DEBUG,
    "token": os.environ.get("APIWARDEN_TOKEN"), # omit for a public portal
}

# urls.py
urlpatterns += [path("api-docs/", include("apiwarden.urls"))]
```

That is the whole integration. The portal serves its own assets, so there is no
`collectstatic` step, and it adds no dependency beyond PyYAML. It coexists with
whatever documentation the project already has — it reads spec files and does
not touch your URLs, views, or schema generation.

Two production notes:

- `watch` defaults to `DEBUG`. Live reload holds an SSE connection open, which
  pins a sync worker; in production, agents poll `revision.json` instead.
- "Try it" calls the API host from the browser, so that host needs to allow the
  docs origin in its CORS configuration.

## Configuration

Settings are the same for both, via `APIWARDEN`, an `apiwarden.toml` beside the
specs, or CLI flags.

| Key | Default | Meaning |
|---|---|---|
| `root` | `api-docs` | Directory holding the specs |
| `title` | derived | Portal title |
| `servers` | spec's own | Base URLs offered for try-it |
| `theme` | `auto` | `auto` follows the reader's OS setting; `light`/`dark` pin it |
| `watch` | `False` | Reload when the spec files change |
| `token` | `None` | Require a shared token on every request (also `APIWARDEN_TOKEN`) |
| `sources` | discovered | Explicit `{name: path}` map |
| `history` | cache dir | File the changelog is kept in |

## How specs are discovered

1. An explicit `sources` map, if you set one.
2. Otherwise a `redocly.yaml` next to the specs — its `apis:` entries are used
   as-is, keeping the names and ordering an existing doc set already has.
3. Otherwise every `openapi.yaml` / `.yml` / `.json` below `root`, each named
   after its parent directory.

Specs are expected to be self-contained, using local `#/components/...` `$ref`s.

## About and support

`/about` has the repository link and the addresses for anyone who wants to
support the project, one per network (BNB Smart Chain, Tron, Bitcoin) with a
copy button. The footer, the sidebar and the Ctrl+K palette link to it, and the
APIwarden mark sits beside the portal's title. It is optional to read and costs
nothing to ignore.

## Development

```
python scripts/vendor_assets.py   # download the renderer bundle
pip install -e ".[dev]"
pytest

# See the portal on the sample specs, with live reload and a mock API for Try it.
# Press Enter in the terminal to edit a spec and watch the page and /changes react.
python scripts/demo.py

# The browser tests are opt-in; they catch things a server-side test cannot,
# such as the renderer silently failing to load.
pip install -e ".[dev,browser]" && playwright install chromium
pytest tests/test_browser.py
```

`tests/fixtures/sample-api/` is a small generic doc set this repo ships as its
own test fixture and demo — try `apiwarden serve tests/fixtures/sample-api` to
see it running without needing specs of your own yet. Every `./api-docs`
above is illustrative: point it at whatever directory holds your specs.

## License

MIT
