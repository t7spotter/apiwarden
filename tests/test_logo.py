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
