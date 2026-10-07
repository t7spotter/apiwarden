"""End-to-end checks in a real browser.

The renderer is a web component that fetches its own spec, so the things most
likely to break — does it actually render, does a live edit reach the open
page, does the portal navigation work — are invisible to a server-side test.
One of these caught a name collision between two `load` functions that made
the renderer silently never load.

Skipped unless playwright and its browser are installed:

    pip install -e ".[browser]" && playwright install chromium
"""

from __future__ import annotations

import shutil
import socket
import threading
import time
from pathlib import Path

import pytest

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

from apiwarden.config import Config
from apiwarden.router import build_portal
from apiwarden.server import serve

LAUNCH = ["--no-sandbox", "--disable-dev-shm-usage"]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        try:
            launched = playwright.chromium.launch(args=LAUNCH)
        except Exception as exc:  # the browser binary is not installed
            pytest.skip(f"chromium unavailable: {exc}")
        yield launched
        launched.close()


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    """A server over a writable copy, so a test may edit the specs."""
    root = tmp_path_factory.mktemp("live") / "sample-api"
    shutil.copytree(Path(__file__).resolve().parent / "fixtures" / "sample-api", root)

    port = _free_port()
    portal = build_portal(
        Config(root=root, title="Browser test", watch=True, history=str(root.parent / "changes.json"))
    )
    threading.Thread(target=serve, args=(portal, "127.0.0.1", port), daemon=True).start()
    time.sleep(0.5)

    yield f"http://127.0.0.1:{port}", root, portal
    if portal.watcher:
        portal.watcher.stop()


@pytest.fixture
def page(browser, live):
    created = browser.new_page(viewport={"width": 1400, "height": 900})
    problems: list[str] = []
    created.on("pageerror", lambda error: problems.append(str(error)))
    yield created
    created.close()
    assert not problems, f"javascript errors on the page: {problems}"


def _shadow_text(page) -> str:
    return page.evaluate("document.getElementById('docs').shadowRoot.textContent") or ""


def _first_app(portal) -> str:
    return portal.registry.names()[0]


def test_the_renderer_actually_renders(page, live):
    base, _, portal = live
    page.goto(f"{base}/{_first_app(portal)}/", wait_until="load")
    page.wait_for_timeout(2500)

    state = page.evaluate("""() => {
      const el = document.getElementById('docs');
      return {
        upgraded: typeof el.loadSpec === 'function',
        failed: el.loadFailed,
        tags: el.resolvedSpec && el.resolvedSpec.tags ? el.resolvedSpec.tags.length : 0,
        rendered: el.shadowRoot.innerHTML.length,
      };
    }""")
    assert state["upgraded"]
    assert state["failed"] is False
    assert state["tags"] > 0
    assert state["rendered"] > 5000


def test_portal_navigation_is_present_and_styled(page, live):
    base, _, portal = live
    page.goto(f"{base}/{_first_app(portal)}/", wait_until="load")
    page.wait_for_timeout(2000)

    assert page.is_visible("#api-switch")
    assert page.is_visible("#search-input")
    # Slotted content is styled by the page's own stylesheet, not the shadow
    # root; an unstyled control means shell.css did not reach this page.
    padding = page.evaluate("getComputedStyle(document.querySelector('.portal-nav')).gap")
    assert padding not in ("", "normal")


def test_cross_spec_search_finds_other_apis(page, live):
    base, _, portal = live
    names = portal.registry.names()
    if len(names) < 2:
        pytest.skip("the sample doc set has only one API")

    page.goto(f"{base}/{names[0]}/", wait_until="load")
    page.wait_for_timeout(2000)

    from apiwarden.index import build_index

    target = next(e for e in build_index(portal.registry) if e["app"] != names[0])
    page.fill("#search-input", target["id"])
    page.wait_for_timeout(700)

    rows = page.eval_on_selector_all("#search-results li a", "els => els.map(e => e.textContent)")
    assert rows, "no search results"
    assert target["path"] in rows[0]


def test_deep_link_scrolls_to_an_operation(page, live):
    base, _, portal = live
    from apiwarden.index import build_index

    app = _first_app(portal)
    entry = next(e for e in build_index(portal.registry) if e["app"] == app)

    page.goto(f"{base}/{app}/?op={entry['method']}%20{entry['path']}", wait_until="load")
    page.wait_for_timeout(3000)

    element_id = f"{entry['method'].lower()}-{entry['path']}"
    found = page.evaluate(
        "id => !!document.getElementById('docs').shadowRoot.getElementById(id)", element_id
    )
    assert found, f"no element {element_id!r}; RapiDoc's id format may have changed"


def test_an_edit_reaches_the_open_page_without_navigating(page, live):
    base, root, portal = live
    app = _first_app(portal)
    spec = portal.registry.specs[app].path
    original = spec.read_text(encoding="utf-8")
    marker = "EDITED-WHILE-OPEN"

    page.goto(f"{base}/{app}/", wait_until="load")
    page.wait_for_timeout(2500)
    assert marker not in _shadow_text(page)

    navigations: list[str] = []
    page.on("framenavigated", lambda frame: navigations.append(frame.url))

    try:
        title = portal.registry.specs[app].title
        spec.write_text(original.replace(f"title: {title}", f"title: {marker}", 1), encoding="utf-8")

        deadline = time.time() + 15
        while marker not in _shadow_text(page) and time.time() < deadline:
            page.wait_for_timeout(400)

        assert marker in _shadow_text(page), "the live edit never reached the page"
        assert not navigations, "the page reloaded instead of swapping the spec in place"
    finally:
        spec.write_text(original, encoding="utf-8")


def test_bearer_token_applies_across_api_pages(page, live):
    base, _, portal = live
    # Needs an app whose spec actually declares a security scheme.
    app = next(
        (name for name, spec in portal.registry.specs.items() if spec.data.get("components", {}).get("securitySchemes")),
        None,
    )
    if app is None:
        pytest.skip("the sample doc set declares no security schemes")

    page.goto(f"{base}/{app}/", wait_until="load")
    page.wait_for_timeout(2000)

    page.fill("#auth-token", "secret-abc-123")
    page.wait_for_timeout(400)  # the debounce before it's saved and applied

    applied = page.evaluate("""() => {
      const schemes = document.getElementById('docs').resolvedSpec.securitySchemes || [];
      return schemes.map(s => s.finalKeyValue);
    }""")
    assert any("secret-abc-123" in (value or "") for value in applied), applied

    # A real navigation to a different API — the field should carry over
    # without retyping, since it lives in localStorage, not the page.
    other = next(name for name in portal.registry.names() if name != app)
    page.goto(f"{base}/{other}/", wait_until="load")
    page.wait_for_timeout(1000)
    assert page.input_value("#auth-token") == "secret-abc-123"

    page.click("#auth-token-clear")
    page.wait_for_timeout(200)
    assert page.evaluate("localStorage.getItem('apiwarden:token:')") is None


def test_right_to_left_text_lays_itself_out(page, live):
    base, _, portal = live
    page.goto(f"{base}/{_first_app(portal)}/", wait_until="load")
    page.wait_for_timeout(2500)

    counts = page.evaluate("""() => {
      const root = document.getElementById('docs').shadowRoot;
      const els = Array.from(root.querySelectorAll('.m-markdown p, .m-markdown li'));
      return {
        total: els.length,
        plaintext: els.filter(e => getComputedStyle(e).unicodeBidi === 'plaintext').length,
      };
    }""")
    assert counts["total"] > 0
    # rapidoc-extra.css is injected into the shadow root via the css-file
    # attribute; if that stopped working, none of these would be plaintext.
    assert counts["plaintext"] == counts["total"]


def test_added_server_reaches_the_try_it_dropdown(page, live):
    base, _, portal = live
    app = portal.registry.names()[0]

    page.goto(f"{base}/{app}/", wait_until="load")
    page.wait_for_timeout(2000)

    # A bare localhost address gets http://, and becomes the selected server.
    page.fill("#server-input", "localhost:9000")
    page.press("#server-input", "Enter")
    page.wait_for_timeout(1500)
    servers = page.evaluate("document.getElementById('docs').resolvedSpec.servers.map(s => s.url)")
    assert servers[0] == "http://localhost:9000", servers
    selected = page.evaluate("document.getElementById('docs').selectedServer.url")
    assert selected == "http://localhost:9000"

    # It persists across a real navigation, and can be removed again.
    page.goto(f"{base}/{app}/", wait_until="load")
    page.wait_for_timeout(2000)
    assert page.inner_text("#server-list") .strip().startswith("http://localhost:9000")
    page.click("#server-list button")
    page.wait_for_timeout(1500)
    servers = page.evaluate("document.getElementById('docs').resolvedSpec.servers.map(s => s.url)")
    assert "http://localhost:9000" not in servers

    # Garbage is refused rather than stored.
    page.fill("#server-input", "ftp://nope")
    page.press("#server-input", "Enter")
    assert page.is_visible("#server-error")


def test_nav_splitter_resizes_and_remembers(page, live):
    base, _, portal = live
    app = _first_app(portal)
    nav_width = "document.getElementById('docs').shadowRoot.querySelector('.nav-bar').getBoundingClientRect().width"

    page.goto(f"{base}/{app}/", wait_until="load")
    page.wait_for_timeout(2000)
    start = page.evaluate(nav_width)

    x = page.evaluate("document.querySelector('.nav-splitter').getBoundingClientRect().x + 4")
    page.mouse.move(x, 300)
    page.mouse.down()
    page.mouse.move(x + 100, 300, steps=5)
    page.mouse.up()
    page.wait_for_timeout(200)
    assert page.evaluate(nav_width) == pytest.approx(start + 100, abs=2)

    # Remembered across a real navigation, then reset by a double-click.
    page.goto(f"{base}/{app}/", wait_until="load")
    page.wait_for_timeout(2000)
    assert page.evaluate(nav_width) == pytest.approx(start + 100, abs=2)
    page.dblclick(".nav-splitter")
    page.wait_for_timeout(200)
    assert page.evaluate(nav_width) == pytest.approx(start, abs=2)


def test_sidebar_controls_line_up(page, live):
    base, _, portal = live
    page.goto(f"{base}/{_first_app(portal)}/", wait_until="load")
    page.wait_for_timeout(2000)
    page.fill("#auth-token", "abc")
    page.fill("#server-input", "localhost:9001")
    page.press("#server-input", "Enter")
    page.wait_for_timeout(1000)

    def box(selector):
        return page.evaluate(
            "s => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.right, r.top, r.bottom]; }",
            selector,
        )

    token, clear = box("#auth-token"), box("#auth-token-clear")
    # The clear button sits inside the token field, not floating below it.
    assert token[2] <= clear[2] and clear[3] <= token[3]
    # Add matches the input's height and stays on one line.
    field, add = box("#server-input"), box(".portal-server-btn")
    assert add[3] - add[2] == pytest.approx(field[3] - field[2], abs=1)
    # Both × buttons share a right edge.
    assert box("#server-list button")[1] == pytest.approx(clear[1], abs=2)
    page.evaluate("localStorage.clear()")


def _add_operation(root: Path, app: str, path: str) -> None:
    import yaml

    spec = next(root.glob(f"apps/{app}/openapi.y*ml"))
    data = yaml.safe_load(spec.read_text(encoding="utf-8"))
    data["paths"][path] = {
        "get": {"summary": "Added by a test.", "operationId": "addedByTest", "responses": {"200": {"description": "ok"}}}
    }
    spec.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_changes_since_the_last_visit_are_marked(page, live):
    base, root, portal = live
    app = _first_app(portal)

    # First visit: whatever is in the log is background, not news.
    page.goto(f"{base}/{app}/", wait_until="load")
    page.wait_for_timeout(2500)
    assert page.is_hidden(".portal-nav .news-count")
    assert page.is_hidden("#portal-news")

    _add_operation(root, app, "/added-by-test/")
    page.wait_for_timeout(2500)  # the watcher notices and the changelog records it

    page.goto(f"{base}/{app}/", wait_until="load")
    page.wait_for_timeout(2500)
    assert page.inner_text(".portal-nav .news-count") == "1"
    assert "since your last visit" in page.inner_text("#news-text")
    assert "1 new" in page.inner_text("#api-switch option:checked")

    # The changed operation gets a marker in RapiDoc's own nav.
    marked = page.evaluate("""() => {
      const root = document.getElementById('docs').shadowRoot;
      return root.adoptedStyleSheets.some(sheet => [...sheet.cssRules].some(
        rule => rule.cssText.includes('data-content-id="get-/added-by-test/"')));
    }""")
    assert marked

    # "Mark as seen" clears it, and stays cleared on the next page.
    page.click("#news-seen")
    assert page.is_hidden("#portal-news")
    page.goto(f"{base}/{app}/", wait_until="load")
    page.wait_for_timeout(2000)
    assert page.is_hidden(".portal-nav .news-count")

    # Opening the Changes page highlights what is new there, then clears it.
    _add_operation(root, app, "/added-by-test-too/")
    page.wait_for_timeout(2500)
    page.goto(f"{base}/changes", wait_until="load")
    page.wait_for_timeout(1000)
    assert page.locator(".entry-new").count() >= 1
    page.goto(f"{base}/{app}/", wait_until="load")
    page.wait_for_timeout(2000)
    assert page.is_hidden(".portal-nav .news-count")


def test_since_examples_fill_the_baseline_field(page, live):
    base, _, _ = live
    page.goto(f"{base}/changes", wait_until="load")
    page.click(".since-details > summary")
    # The live fixture's specs are in a temp directory, not a git repository, so
    # only the snapshot example is offered (the git ones are covered in test_diff).
    assert page.locator(".since-example[data-example='HEAD~5']").count() == 0
    page.click(".since-example[data-example='baseline.json']")
    assert page.input_value("#since") == "baseline.json"


def test_operation_tools_copy_a_link_and_a_curl_command(page, live):
    base, _, portal = live
    app = _first_app(portal)
    page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
    page.goto(f"{base}/{app}/", wait_until="load")
    page.wait_for_timeout(2500)

    def clipboard():
        return page.evaluate("navigator.clipboard.readText()")

    def tools(action):
        # The buttons live in RapiDoc's shadow root; Playwright pierces it.
        return page.locator(f"rapi-doc .apiwarden-op-btn[data-action='{action}']").first

    assert page.locator("rapi-doc .apiwarden-op-tools").count() >= 1

    tools("link").click()
    page.wait_for_timeout(300)
    assert f"/{app}/?op=" in clipboard()

    tools("curl").click()
    page.wait_for_timeout(800)
    assert clipboard().startswith("curl ")
    assert "Bearer $TOKEN" in clipboard()  # the sample's first operation needs a token

    # Shift-click puts the reader's own token in; a plain click never does.
    page.fill("#auth-token", "tok-123")
    page.wait_for_timeout(400)
    tools("curl").click()
    page.wait_for_timeout(800)
    assert "tok-123" not in clipboard()
    tools("curl").click(modifiers=["Shift"])
    page.wait_for_timeout(800)
    command = clipboard()
    assert 'Bearer tok-123"' in command and "$TOKEN" not in command

    # The command follows the selected server — one added in the sidebar.
    page.fill("#server-input", "localhost:9777")
    page.press("#server-input", "Enter")
    page.wait_for_timeout(1500)
    tools("curl").click()
    page.wait_for_timeout(800)
    assert "http://localhost:9777" in clipboard()


def test_history_link_on_an_operation_shows_only_that_operations_changes(page, live):
    import yaml

    base, root, portal = live
    app = _first_app(portal)
    url, method, _operation, _shared = next(portal.registry.specs[app].operations())
    key = f"{method.upper()} {url}"

    page.goto(f"{base}/{app}/", wait_until="load")  # first visit: nothing is new yet
    page.wait_for_timeout(2000)

    spec = next(root.glob(f"apps/{app}/openapi.y*ml"))
    data = yaml.safe_load(spec.read_text(encoding="utf-8"))
    data["paths"][url][method]["parameters"] = [
        {"name": "history_probe", "in": "query", "required": True, "schema": {"type": "integer"}}
    ]
    spec.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    page.wait_for_timeout(2500)

    page.goto(f"{base}/{app}/", wait_until="load")
    page.wait_for_timeout(2500)
    link = page.locator(f"rapi-doc .apiwarden-op-btn[data-action='history'][data-op='{key}']")
    assert link.inner_text().startswith("History (")  # the changelog has entries for it

    link.click()
    page.wait_for_url("**/changes?**")
    page.wait_for_timeout(800)
    assert page.locator(".changelog[data-filtered] .entry").count() >= 1
    assert "history_probe" in page.inner_text(".changelog")
    assert "History of" in page.inner_text("h1")

    # Looking at one operation's history must not clear the "new" markers.
    assert page.is_visible(".topbar .news-count")


def test_theme_toggle_cycles_remembers_and_reaches_the_renderer(page, live):
    base, _, portal = live
    page.goto(f"{base}/changes", wait_until="load")
    page.wait_for_timeout(600)

    def theme():
        return page.evaluate("document.documentElement.getAttribute('data-theme')")

    def background():
        return page.evaluate("getComputedStyle(document.body).backgroundColor")

    assert theme() is None  # Auto: the page follows the system
    assert "Auto" in page.inner_text("#theme-toggle")

    page.click("#theme-toggle")
    assert theme() == "light" and background() == "rgb(255, 255, 255)"
    page.click("#theme-toggle")
    assert theme() == "dark" and background() == "rgb(30, 30, 30)"

    # Remembered across a real navigation, and applied to RapiDoc too.
    page.goto(f"{base}/{_first_app(portal)}/", wait_until="load")
    page.wait_for_timeout(2000)
    assert theme() == "dark"
    assert page.evaluate("document.getElementById('docs').getAttribute('theme')") == "dark"
    assert "Dark" in page.inner_text("#theme-toggle")

    page.click("#theme-toggle")  # back to Auto
    assert theme() is None
    assert page.evaluate("document.getElementById('docs').getAttribute('theme')") == "light"  # this browser's system is light


def test_command_palette_searches_runs_actions_and_copies_curl(page, live):
    base, _, portal = live
    page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
    app = _first_app(portal)
    page.goto(f"{base}/{app}/", wait_until="load")
    page.wait_for_timeout(2500)

    assert page.is_hidden(".palette")  # built on first use
    page.keyboard.press("Control+k")
    page.wait_for_selector(".palette:not([hidden])")
    assert page.locator(".palette-item").count() > 3  # the APIs and the actions, before typing

    # Operations across every API, ranked like the sidebar search.
    page.keyboard.type("task")
    page.wait_for_timeout(600)
    texts = page.locator(".palette-item").all_inner_texts()
    assert any("GET" in t and "/tasks/" in t for t in texts), texts

    # Ctrl+Enter copies the curl command and leaves the palette to say so.
    page.keyboard.press("Control+Enter")
    page.wait_for_timeout(900)
    assert page.evaluate("navigator.clipboard.readText()").startswith("curl ")

    # ">" shows actions only; Enter runs one — and closes first, handing focus back.
    page.keyboard.press("/")
    page.wait_for_selector(".palette:not([hidden])")
    page.keyboard.type(">dark")
    page.wait_for_timeout(500)
    assert page.locator(".palette-item").all_inner_texts() == ["Use the dark theme"]
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    assert page.is_hidden(".palette")
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "dark"

    # An action that moves focus is not undone by the palette closing.
    page.keyboard.press("Control+k")
    page.keyboard.type(">bearer")
    page.wait_for_timeout(500)
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    assert page.evaluate("document.activeElement && document.activeElement.id") == "auth-token"

    # Escape closes; typing "/" in a field does not open it.
    page.keyboard.press("Control+k")
    page.keyboard.press("Escape")
    assert page.is_hidden(".palette")
    page.keyboard.type("a/b")
    assert page.is_hidden(".palette")
    page.evaluate("localStorage.clear()")


def test_command_palette_jumps_to_another_api(page, live):
    base, _, portal = live
    names = portal.registry.names()
    page.goto(f"{base}/changes", wait_until="load")  # a page with no RapiDoc at all
    page.keyboard.press("Control+k")
    page.keyboard.type(names[-1])
    page.wait_for_timeout(600)
    page.locator(".palette-item").first.click()
    page.wait_for_url(f"**/{names[-1]}/**")


def test_about_page_copies_a_wallet_address(page, live):
    from apiwarden.support import WALLETS

    base, _, _ = live
    page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
    page.goto(f"{base}/about/", wait_until="load")

    buttons = page.locator("button.wallet-copy")
    assert buttons.count() == len(WALLETS)
    for index, wallet in enumerate(WALLETS):
        buttons.nth(index).click()
        page.wait_for_timeout(200)
        assert page.evaluate("navigator.clipboard.readText()") == wallet.address
        assert "Copied" in buttons.nth(index).inner_text()

    # And the palette can get there from anywhere.
    page.goto(f"{base}/changes", wait_until="load")
    page.keyboard.press("Control+k")
    page.keyboard.type("donate")
    page.wait_for_timeout(500)
    page.keyboard.press("Enter")
    page.wait_for_url("**/about/#support")
