"""HTML pages.

The shell owns cross-spec navigation, the operation browser, and the two panels
every OpenAPI renderer throws away: the info.description narrative and the
top-level x-* blocks. Scalar renders the polished per-spec reference inside an
iframe, so its styles never collide with ours.
"""

from __future__ import annotations

import copy
import html
import json
from typing import Any
from urllib.parse import quote

from . import md
from .config import Config
from .index import api_summaries, build_index
from .loader import Registry, Spec

# The editor greys, so the portal reads like the panel it grew out of. RapiDoc
# takes its palette as attributes rather than CSS variables, so the same values
# live here and in shell.css.
THEMES = {
    "light": {
        "bg": "#ffffff",
        "text": "#1a1d21",
        "nav_bg": "#f3f3f3",
        "nav_text": "#3b4048",
        "nav_hover": "#e4e6e9",
        "accent": "#0066b8",
    },
    "dark": {
        "bg": "#1e1e1e",
        "text": "#d4d4d4",
        "nav_bg": "#252526",
        "nav_text": "#bbbbbb",
        "nav_hover": "#37373d",
        "accent": "#4daafc",
    },
}

# Tahoma and Noto Sans are here for their broad right-to-left coverage.
FONT_STACK = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Tahoma, '
    'Roboto, "Helvetica Neue", Arial, sans-serif'
)

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="{shell_css}">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><text y='13' font-size='14'>&#128737;</text></svg>">
</head>
<body>
<header class="topbar">{topbar}</header>
<main class="main">{main}</main>
<script>window.APIWARDEN = {config};</script>
<script src="{shell_js}"></script>
</body>
</html>
"""


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def page(config: Config, registry: Registry, title: str, main: str, active: str = "") -> str:
    """The frame for pages RapiDoc does not render: the landing and changes."""
    payload = {
        "base": config.base_path,
        "watch": config.watch,
        "revision": registry.revision,
        "theme": config.theme,
    }
    return _PAGE.format(
        title=_e(title),
        shell_css=_e(config.asset("shell.css")),
        shell_js=_e(config.asset("shell.js")),
        topbar=_topbar(config, registry, active),
        main=main,
        config=json.dumps(payload),
    )


def _topbar(config: Config, registry: Registry, active: str) -> str:
    options = "".join(
        f'<option value="{_e(config.url(api["app"] + "/"))}" data-app="{_e(api["app"])}"'
        f'{" selected" if api["app"] == active else ""}>{_e(api["title"])}</option>'
        for api in api_summaries(registry)
    )
    changes = "active" if active == "__changes__" else ""

    return f"""
<a class="portal-title" href="{_e(config.url("/"))}">{_e(config.title)}</a>
<select class="portal-switch" id="api-switch" aria-label="Choose an API">
  <option value="">Choose an API…</option>{options}
</select>
<div class="topbar-search">
  <input class="portal-search" id="search-input" type="search" placeholder="Search all APIs…"
         autocomplete="off" aria-label="Search every API">
  <ul class="portal-results" id="search-results"></ul>
</div>
{_token_control()}
<nav class="topbar-links">
  <a class="{changes}" href="{_e(config.url("changes"))}">Changes{_NEWS_BADGE}</a>
  <a href="{_e(config.url("index.json"))}">index.json</a>
  <a href="{_e(config.url("llms.txt"))}">llms.txt</a>
</nav>
<span class="topbar-rev">rev {_e(registry.revision)}</span>
"""


# Filled in by shell.js with how many contract changes the reader has not seen.
_NEWS_BADGE = ' <span class="news-count" hidden></span>'


def _token_control() -> str:
    """A Bearer token, set once and applied to every API's Try it panel.

    Held only in the reader's browser (localStorage) — the server never sees
    it. shell.js pushes it into RapiDoc's own auth state via its setApiKey()
    API whenever a spec loads, so switching APIs doesn't mean re-entering it.
    """
    return """
<div class="portal-auth">
  <input class="portal-token" id="auth-token" type="password" placeholder="Bearer token"
         autocomplete="off" spellcheck="false"
         aria-label="Bearer token, applied to every API&#8217;s Try it panel">
  <button type="button" class="portal-token-clear" id="auth-token-clear"
          title="Clear token" aria-label="Clear the bearer token">&times;</button>
</div>
"""


def _servers_control() -> str:
    """Extra Try it servers — localhost, a staging host — added in the browser.

    Kept in localStorage like the token. shell.js merges them in front of the
    spec's own servers before RapiDoc renders it, so they show up in its server
    dropdown and the first one added is the one Try it calls.
    """
    return """
<div class="portal-servers">
  <form class="portal-server-add" id="server-form" autocomplete="off">
    <input class="portal-token" id="server-input" type="text" inputmode="url"
           placeholder="Add server, e.g. localhost:8000" spellcheck="false"
           aria-label="Add a server for the Try it panel">
    <button type="submit" class="portal-server-btn">Add</button>
  </form>
  <ul class="portal-server-list" id="server-list" aria-label="Servers added in this browser"></ul>
  <p class="portal-server-error" id="server-error" role="alert" hidden></p>
</div>
"""


# ---------------------------------------------------------------- landing


def landing(config: Config, registry: Registry) -> str:
    apis = api_summaries(registry)
    total = sum(api["operations"] for api in apis)

    cards = []
    for api in apis:
        spec = registry.specs[api["app"]]
        blurb = _e(md.strip(spec.description, 150)) if not spec.error else _e(spec.error)
        cards.append(
            f'<a class="card" data-app="{_e(api["app"])}" href="{_e(config.url(api["app"] + "/"))}">'
            f'<h3>{_e(api["title"])}</h3><p>{blurb}</p>'
            f'<span class="pill">{api["operations"]} operations</span> '
            f'<span class="pill">v{_e(api["version"])}</span></a>'
        )

    errors = "".join(
        f'<div class="notice">{_e(message)}</div>' for message in registry.errors
    )
    broken = "".join(
        f'<div class="notice">{_e(api["app"])}: {_e(api["error"])}</div>'
        for api in apis
        if api["error"]
    )

    main = f"""
<div class="page-head">
  <h1>{_e(config.title)}</h1>
  <p>{len(apis)} APIs · {total} operations · always current, straight from the specs.</p>
</div>
{errors}{broken}
<div class="cards">{"".join(cards)}</div>
{_agent_box(config)}
"""
    return page(config, registry, config.title, main)


def _agent_box(config: Config) -> str:
    mcp_url = config.url("mcp")
    return f"""
<div class="agent-box">
  <h2>Connect an AI agent</h2>
  <p>Point an agent here once and it always reads current docs — nothing to re-share.</p>
  <pre><code>{{
  "mcpServers": {{
    "apiwarden": {{ "type": "http", "url": "&lt;origin&gt;{_e(mcp_url)}" }}
  }}
}}</code></pre>
  <p>Or fetch it as plain data:</p>
  <ul class="agent-links">
    <li><a href="{_e(config.url("index.json"))}">index.json</a></li>
    <li><a href="{_e(config.url("llms.txt"))}">llms.txt</a></li>
    <li><a href="{_e(config.url("llms-full.txt"))}">llms-full.txt</a></li>
    <li><a href="{_e(config.url("revision.json"))}">revision.json</a></li>
  </ul>
</div>
"""


# ---------------------------------------------------------------- one API


# RapiDoc, configured the way the VS Code OpenAPI viewer configures it: the
# read layout, a nav of colour-coded methods showing URL paths, server
# selection and try-it enabled. Everything below that is ours.
_RAPIDOC = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<!-- shell.css styles the nav-logo slot: slotted content stays in the light DOM
     and is styled by this document, not by the shadow root. -->
<link rel="stylesheet" href="{shell_css}">
<link rel="stylesheet" href="{extra_css}">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><text y='13' font-size='14'>&#128737;</text></svg>">
<style>
  html, body {{ margin: 0; height: 100%; background: {bg}; }}
  rapi-doc {{ width: 100%; height: 100%; }}
</style>
</head>
<body>
<rapi-doc
  id="docs"
  css-file="rapidoc-extra.css"
  theme="{theme}"
  bg-color="{bg}"
  text-color="{text}"
  nav-bg-color="{nav_bg}"
  nav-text-color="{nav_text}"
  nav-hover-bg-color="{nav_hover}"
  nav-accent-color="{accent}"
  primary-color="{accent}"
  render-style="read"
  show-header="false"
  show-info="true"
  show-components="true"
  allow-authentication="true"
  allow-try="true"
  allow-search="true"
  allow-advanced-search="true"
  allow-server-selection="true"
  allow-spec-url-load="false"
  allow-spec-file-load="false"
  allow-api-list-style-selection="true"
  show-method-in-nav-bar="as-colored-block"
  use-path-in-nav-bar="true"
  info-description-headings-in-navbar="true"
  nav-item-spacing="relaxed"
  schema-style="table"
  default-schema-tab="schema"
  regular-font="{font}"
  update-route="false"
>
  <div slot="nav-logo" class="portal-nav">{nav}</div>
</rapi-doc>
<script>window.APIWARDEN = {config};</script>
<script src="{script}"></script>
<script src="{shell_js}"></script>
</body>
</html>
"""


def api_page(config: Config, registry: Registry, spec: Spec) -> str:
    """One API, rendered by RapiDoc, with our portal navigation in its nav."""
    if spec.error:
        main = f'<div class="page-head"><h1>{_e(spec.name)}</h1></div><div class="notice">{_e(spec.error)}</div>'
        return page(config, registry, spec.name, main, active=spec.name)

    # "auto" renders light and lets shell.js repaint from prefers-color-scheme
    # on load, so there is no flash for a reader who pinned a theme.
    theme_name = "dark" if config.theme == "dark" else "light"
    palette = dict(THEMES[theme_name], theme=theme_name)

    payload = {
        "base": config.base_path,
        "watch": config.watch,
        "revision": registry.revision,
        "app": spec.name,
        "spec": config.url(f"display/{spec.name}.json"),
        "theme": config.theme,
    }

    return _RAPIDOC.format(
        title=_e(f"{spec.title} · {config.title}"),
        shell_css=_e(config.asset("shell.css")),
        shell_js=_e(config.asset("shell.js")),
        extra_css=_e(config.asset("rapidoc-extra.css")),
        script=_e(config.asset("vendor/rapidoc.js")),
        nav=_portal_nav(config, registry, spec.name),
        config=json.dumps(payload),
        font=_e(FONT_STACK),
        **{key: _e(value) for key, value in palette.items()},
    )


def _portal_nav(config: Config, registry: Registry, active: str) -> str:
    """What goes in RapiDoc's nav-logo slot: which API, and search across all."""
    options = "".join(
        f'<option value="{_e(config.url(api["app"] + "/"))}" data-app="{_e(api["app"])}"'
        f'{" selected" if api["app"] == active else ""}>{_e(api["title"])}</option>'
        for api in api_summaries(registry)
    )

    return f"""
<a class="portal-title" href="{_e(config.url("/"))}">{_e(config.title)}</a>
<select class="portal-switch" id="api-switch" aria-label="Choose an API">{options}</select>
<input class="portal-search" id="search-input" type="search" placeholder="Search all APIs…"
       autocomplete="off" aria-label="Search every API">
<ul class="portal-results" id="search-results"></ul>
{_token_control()}
{_servers_control()}
<div class="portal-links">
  <a href="{_e(config.url("changes"))}">Changes{_NEWS_BADGE}</a>
  <a href="{_e(config.url("index.json"))}">index.json</a>
  <a href="{_e(config.url("llms.txt"))}">llms.txt</a>
  <a href="{_e(config.url("types/" + active + ".ts"))}" title="TypeScript types for this API">types.ts</a>
</div>
<p class="portal-news" id="portal-news" hidden>
  <a href="{_e(config.url("changes"))}" id="news-text"></a>
  <button type="button" id="news-seen" title="Clear the markers until the next change">Mark as seen</button>
</p>
"""


# ---------------------------------------------------------------- display spec


def display_spec(config: Config, spec: Spec) -> dict[str, Any]:
    """The copy RapiDoc renders.

    Two departures from the file on disk, both presentational: the top-level
    x-* blocks are appended to info.description so they are visible (and, with
    info-description-headings-in-navbar, navigable) instead of being dropped,
    and the configured servers win over the ones in the file. The raw spec
    stays untouched at /openapi/<name>.json for downloads and agents.
    """
    document = copy.deepcopy(spec.data)

    extensions = spec.extensions
    if extensions:
        info = document.setdefault("info", {})
        info["description"] = (info.get("description") or "").rstrip() + _extensions_markdown(extensions)

    if config.servers:
        document["servers"] = [{"url": url} for url in config.servers]

    return document


def _extensions_markdown(extensions: dict[str, Any]) -> str:
    lines = ["", "", "## Limits & specifications", ""]
    for name, value in extensions.items():
        lines.append(f"### {name}")
        lines.append("")
        if isinstance(value, dict):
            lines += ["| | |", "|---|---|"]
            for key, item in value.items():
                lines.append(f"| `{key}` | {_md_cell(item)} |")
        elif isinstance(value, list):
            lines += [f"- {_md_cell(item)}" for item in value]
        else:
            lines.append(_md_cell(value))
        lines.append("")
    return "\n".join(lines)


def _md_cell(value: Any) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    # Table cells are one line, and a pipe would end the cell early.
    return text.replace("|", "\\|").replace("\n", " ").strip()


# ---------------------------------------------------------------- changes


_LEVEL_LABEL = {"breaking": "Breaking", "additive": "Additive", "info": "Note"}

# What each kind of change means, in words a reader of the log would use.
_KIND_LABEL = {
    "api-added": "New API",
    "api-removed": "API removed",
    "operation-added": "New endpoint",
    "operation-removed": "Endpoint removed",
    "operation-id-changed": "Operation ID renamed",
    "auth-required": "Now requires authentication",
    "auth-changed": "Authentication changed",
    "deprecated": "Deprecated",
    "summary-changed": "Summary reworded",
    "parameter-added": "Parameter added",
    "parameter-removed": "Parameter removed",
    "parameter-now-required": "Parameter now required",
    "parameter-type-changed": "Parameter type changed",
    "field-added": "Field added",
    "field-removed": "Field removed",
    "field-type-changed": "Field type changed",
    "field-now-required": "Field now required",
    "field-now-optional": "Field now optional",
    "enum-value-added": "Allowed value added",
    "enum-value-removed": "Allowed value removed",
    "response-added": "Response added",
    "response-removed": "Response removed",
}

# Kinds whose detail is a sentence rather than a field name or value.
_PROSE_KINDS = {
    "api-added", "api-removed", "operation-added", "operation-removed",
    "auth-required", "auth-changed", "deprecated", "summary-changed",
}

# Entries past this many start collapsed, so the page opens on what is recent.
_OPEN_ENTRIES = 3


def changelog_page(
    config: Config,
    registry: Registry,
    entries: list[dict],
    since: float | None,
    scope: tuple[str, str] | None = None,
) -> str:
    """Every recorded change to the contract, newest first.

    `scope` is (app, operation) for the history of one API or one operation;
    either may be empty.
    """
    app, operation = scope or ("", "")
    if entries:
        body = "".join(
            _entry(config, entry, open_=index < _OPEN_ENTRIES, history_links=not scope)
            for index, entry in enumerate(entries)
        )
    elif scope:
        body = (
            '<p class="empty">No recorded changes to this '
            f'{"operation" if operation else "API"} since tracking began.</p>'
        )
    else:
        body = (
            '<p class="empty">Nothing has changed yet. Edit a spec and the difference '
            "shows up here — no tags or snapshots needed.</p>"
        )

    tracking = f"Tracking since {_time(since, 'since-time')}." if since else ""
    if scope:
        what = f"<code>{_e(operation)}</code>" if operation else ""
        link = f'<a href="{_e(config.url(app + "/"))}">{_e(app)}</a>' if app else ""
        where = f" in {link}" if what and link else link
        head = f"""
  <h1>History of {what}{where}</h1>
  <p>Every recorded change to {"this operation" if operation else "this API"}, newest first. {tracking}
     <a href="{_e(config.url("changes"))}">Back to the full history</a></p>"""
        tail = ""
    else:
        head = f"""
  <h1>Changes</h1>
  <p>Every change to the API contract, newest first, recorded automatically whenever a spec changes. {tracking}</p>"""
        tail = _since_form("", open_=False)

    main = f"""
<div class="page-head">{head}
</div>
<div class="changelog"{" data-filtered" if scope else ""}>{body}</div>
{tail}
"""
    return page(config, registry, f"Changes · {config.title}", main, active="__changes__")


def _entry(config: Config, entry: dict, open_: bool, history_links: bool = True) -> str:
    from .diff import Change

    changes = [Change(**change) for change in entry["changes"]]
    commit = entry.get("commit")
    if commit:
        source = (
            f'<span class="entry-source"><code>{_e(commit["sha"][:7])}</code> '
            f'{_e(commit["subject"])} <span class="entry-author">· {_e(commit["author"])}</span></span>'
        )
    else:
        source = '<span class="entry-source">' + _e(", ".join(entry["apis"])) + "</span>"

    worst = next((level for level in ("breaking", "additive", "info") if entry["counts"].get(level)), "info")
    return (
        f'<details class="entry entry-{worst}" data-at="{entry["at"]}"{" open" if open_ else ""}>'
        f'<summary class="entry-head">{_time(entry["at"])}{source}{_pills(entry["counts"])}</summary>'
        f'<div class="entry-body">{_change_groups(config, changes, history_links)}</div>'
        "</details>"
    )


def _time(stamp: float, kind: str = "entry-time") -> str:
    """A UTC time the shell rewrites into the reader's own zone (and, on an entry, a "2 hours ago")."""
    from datetime import datetime, timezone

    moment = datetime.fromtimestamp(stamp, tz=timezone.utc)
    return (
        f'<time class="{kind}" datetime="{moment.isoformat()}">'
        f'{moment.strftime("%d %b %Y, %H:%M")} UTC</time>'
    )


def _pills(counts: dict[str, int]) -> str:
    return '<span class="entry-pills">' + "".join(
        f'<span class="pill pill-{level}">{count} {_LEVEL_LABEL[level].lower()}</span>'
        for level, count in counts.items()
        if count
    ) + "</span>"


# Shown under the Baseline field. Each is something `git show <rev>:<file>` or a
# snapshot file accepts, which is exactly what snapshot_at() resolves.
_SINCE_EXAMPLES = (
    ("v1.4.0", "a release tag"),
    ("HEAD~5", "five commits ago"),
    ("main", "a branch, as it is now"),
    ("3f9c2ab", "a commit, short or full"),
    ("baseline.json", "a file saved with apiwarden snapshot"),
)


def _since_form(since: str, open_: bool) -> str:
    chips = "".join(
        f'<li><button type="button" class="since-example" data-example="{_e(value)}">'
        f"<code>{_e(value)}</code></button> <span>{_e(note)}</span></li>"
        for value, note in _SINCE_EXAMPLES
    )
    return f"""
<details class="since-details"{" open" if open_ else ""}>
  <summary>Compare against a specific version</summary>
  <form class="since-form" method="get">
    <label for="since">Baseline</label>
    <input id="since" name="since" value="{_e(since)}" placeholder="e.g. v1.4.0 or HEAD~5"
           autocomplete="off" spellcheck="false">
    <button type="submit">Compare</button>
  </form>
  <div class="since-help">
    <p>Name the version you built against and see what has moved since. Anything
       git can show works — click an example to fill it in:</p>
    <ul>{chips}</ul>
    <p>The same thing from a terminal, e.g. to fail CI on a breaking change:
       <code>apiwarden changes ./api-docs --since v1.4.0 --fail-on-breaking</code></p>
  </div>
</details>
"""


def changes_page(config: Config, registry: Registry, since: str, changes, error: str | None) -> str:
    """One comparison against a baseline the reader named."""
    from .diff import summarize

    if error:
        body = f'<div class="notice">{_e(error)}</div>'
    elif not changes:
        body = '<p class="empty">Nothing changed against this baseline.</p>'
    else:
        body = _change_groups(config, changes)

    main = f"""
<div class="page-head">
  <h1>Changes since <code>{_e(since)}</code></h1>
  <p>What moved between that baseline and the specs as they are right now.
     <a href="{_e(config.url("changes"))}">Back to the full history</a></p>
  <div class="meta-row">{_pills(summarize(changes))}</div>
</div>
{_since_form(since, open_=True)}
{body}
"""
    return page(config, registry, f"Changes · {config.title}", main, active="__changes__")


def _detail(change) -> str:
    return _e(change.detail) if change.kind in _PROSE_KINDS else f"<code>{_e(change.detail)}</code>"


def _change_groups(config: Config, changes, history_links: bool = True) -> str:
    grouped: dict[tuple[str, str], list] = {}
    for change in changes:
        grouped.setdefault((change.app, change.operation), []).append(change)

    blocks = []
    for (app, operation), items in grouped.items():
        worst = min(items, key=lambda c: ("breaking", "additive", "info").index(c.level)).level
        # ?op= is what the API page scrolls to once the spec has loaded.
        target = app + "/" + (f"?op={quote(operation)}" if operation else "")
        heading = _e(operation) if operation else "whole API"
        link = f'<a href="{_e(config.url(target))}">{_e(app)}</a>'
        if operation and history_links:
            query = f"?app={quote(app)}&op={quote(operation)}"
            link += f' <a class="change-history" href="{_e(config.url("changes") + query)}">history</a>'

        rows = "".join(
            f'<tr><td><span class="tag tag-{item.level}">{_LEVEL_LABEL[item.level]}</span></td>'
            f'<td title="{_e(item.kind)}">{_e(_KIND_LABEL.get(item.kind, item.kind))}</td>'
            f"<td>{_detail(item)}</td></tr>"
            for item in items
        )
        blocks.append(
            f'<div class="ext-block change-{worst}">'
            f"<h3>{heading} <span class=\"change-app\">{link}</span></h3>"
            f'<table class="kv change-table">{rows}</table></div>'
        )
    return "".join(blocks)
