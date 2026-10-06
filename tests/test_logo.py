"""The logo files, and the places the portal uses them."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from apiwarden.http import Request
from apiwarden.router import handle

ROOT = Path(__file__).resolve().parent.parent
SVGS = [
    ROOT / "assets" / "logo.svg",
    ROOT / "assets" / "logo-lockup.svg",
    ROOT / "assets" / "logo-lockup-dark.svg",
    ROOT / "src" / "apiwarden" / "static" / "logo.svg",
    ROOT / "src" / "apiwarden" / "static" / "favicon.svg",
]


@pytest.mark.parametrize("path", SVGS, ids=lambda p: p.name)
def test_every_logo_svg_is_well_formed(path):
    root = ET.parse(path).getroot()
    assert root.tag.endswith("svg") and root.get("viewBox")
    # Nothing that reaches out: a logo must render offline and cannot run code.
    text = path.read_text()
    assert "<script" not in text and "http://" not in text.replace("http://www.w3.org/2000/svg", "")


def test_the_lockup_has_its_wordmark_as_outlines_not_live_text():
    # Live text would depend on the viewer having the font.
    for name in ("logo-lockup.svg", "logo-lockup-dark.svg"):
        text = (ROOT / "assets" / name).read_text()
        assert "<text" not in text and "font-family" not in text
        assert 'aria-label="APIwarden"' in text


def test_the_portal_serves_the_logo_and_favicon(portal):
    for name in ("logo.svg", "favicon.svg"):
        response = handle(Request("GET", f"/_static/{name}"), portal)
        assert response.status == 200, name
        assert response.headers["Content-Type"].startswith("image/svg+xml"), name


def test_pages_use_the_svg_favicon(portal, registry):
    for path in ("/", "/changes", f"/{registry.names()[0]}/"):
        markup = handle(Request("GET", path), portal).body.decode()
        assert 'rel="icon" type="image/svg+xml" href="/_static/favicon.svg' in markup, path


def test_the_about_hero_carries_the_logo_and_the_name(portal):
    markup = handle(Request("GET", "/about"), portal).body.decode()
    assert 'class="hero-logo"' in markup and "/_static/logo.svg" in markup
    assert '<span class="brand-api">API</span>warden' in markup


def test_the_mark_sits_beside_the_title_on_every_page(portal, registry):
    for path in ("/", "/changes", "/about", f"/{registry.names()[0]}/"):
        markup = handle(Request("GET", path), portal).body.decode()
        assert 'class="portal-title"' in markup, path
        title = markup[markup.index('class="portal-title"') :].split("</a>", 1)[0]
        assert 'class="brand-mark"' in title and "/_static/favicon.svg" in title, path


def test_the_landing_header_and_footer_carry_the_brand(portal):
    markup = handle(Request("GET", "/"), portal).body.decode()
    assert 'class="page-head page-head-brand"' in markup
    assert "/_static/logo.svg" in markup  # the full mark beside the title
    assert "Powered by APIwarden" in markup


def test_an_unbranded_portal_has_no_mark_favicon_or_credit(registry, sample_root):
    from apiwarden.config import Config
    from apiwarden.router import Portal

    quiet = Portal(Config(root=sample_root, support=False), registry)
    for path in ("/", "/changes", f"/{registry.names()[0]}/"):
        markup = handle(Request("GET", path), quiet).body.decode()
        assert "brand-mark" not in markup, path
        assert 'rel="icon"' not in markup, path
        assert "Powered by" not in markup and "logo.svg" not in markup, path
