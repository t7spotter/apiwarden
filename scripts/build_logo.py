#!/usr/bin/env python3
"""Regenerate the APIwarden logo files.

    pip install fonttools
    python scripts/build_logo.py

The mark is a heart that is also a shield: split down the middle like a shield
(the warden), the left lobe lifted out as a warm orb carrying {} (the API, and
the gift). The wordmark is set in Quicksand (SIL Open Font License, so its
outlines may be used in a logo) and converted to paths, so the files look the
same on a machine without the font. Nothing here runs at serve time.

Writes assets/ (README and social images) and the two files the portal serves.
Needs Quicksand: pass --font-dir if it is not in the usual place.
"""

import sys
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen

FONT = "/usr/share/fonts/truetype/quicksand/Quicksand-{}.ttf"  # overridden by --font-dir


def mark_defs(prefix=""):
    p = prefix
    return f"""
    <linearGradient id="{p}giv" x1="216" y1="44" x2="132" y2="218" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#3B3FF0"/><stop offset="0.52" stop-color="#2E86FF"/><stop offset="1" stop-color="#27DDF5"/>
    </linearGradient>
    <linearGradient id="{p}orb" x1="58" y1="48" x2="114" y2="138" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#FFD166"/><stop offset="1" stop-color="#FF6B6B"/>
    </linearGradient>
    <linearGradient id="{p}low" x1="54" y1="118" x2="124" y2="218" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#4A5CF6"/><stop offset="1" stop-color="#2A3BD0"/>
    </linearGradient>
    <mask id="{p}gap"><rect width="256" height="256" fill="#fff"/><circle cx="88" cy="92" r="52" fill="#000"/></mask>"""


BRACES = (
    '<g fill="none" stroke="#fff" stroke-width="5.2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M80 72C72 72 72 76 72 82V86C72 90 69 92 66 92C69 92 72 94 72 98V102C72 108 72 112 80 112"/>'
    '<path d="M96 72C104 72 104 76 104 82V86C104 90 107 92 110 92C107 92 104 94 104 98V102C104 108 104 112 96 112"/>'
    '</g>'
)


def mark_body(prefix="", braces=True, sparkles=True):
    p = prefix
    out = f"""
  <g mask="url(#{p}gap)">
    <path d="M132 66.7A44 44 0 1 1 203.7 117.9Q178.3 161.2 144.9 198.7Q132 216.5 132 194.5Z" fill="url(#{p}giv)"/>
    <path d="M52.3 117.9Q77.7 161.2 111.1 198.7Q124 216.5 124 194.5L124 100L60 100Z" fill="url(#{p}low)"/>
  </g>
  <circle cx="88" cy="92" r="44" fill="url(#{p}orb)"/>"""
    if braces:
        out += "\n  " + BRACES
    else:
        out += '\n  <path d="M62 78A30 30 0 0 1 84 58" fill="none" stroke="#fff" stroke-opacity=".5" stroke-width="6" stroke-linecap="round"/>'
    if sparkles:
        out += """
  <path d="M226 38l3 9 9 3-9 3-3 9-3-9-9-3 9-3z" fill="#FFC857"/>
  <path d="M30 152l2 6 6 2-6 2-2 6-2-6-6-2 6-2z" fill="#FFC857" fill-opacity=".85"/>"""
    return out


def mark_svg(size=512, braces=True, sparkles=True):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="{size}" height="{size}" role="img" aria-label="APIwarden">'
            f"<defs>{mark_defs()}</defs>{mark_body(braces=braces, sparkles=sparkles)}\n</svg>\n")


def text_path(text, weight, size, tracking=0.0):
    """Outline `text` as one SVG path at `size` px per em; returns (d, width, bounds)."""
    font = TTFont(FONT.format(weight))
    gs, cmap = font.getGlyphSet(), font.getBestCmap()
    scale = size / font["head"].unitsPerEm
    x, d = 0.0, []
    bp = BoundsPen(gs)
    for ch in text:
        name = cmap[ord(ch)]
        pen = SVGPathPen(gs, ntos=lambda v: f"{v:.2f}".rstrip("0").rstrip("."))
        tp = TransformPen(pen, (scale, 0, 0, -scale, x, 0))
        gs[name].draw(tp)
        gs[name].draw(TransformPen(bp, (scale, 0, 0, -scale, x, 0)))
        d.append(pen.getCommands())
        x += gs[name].width * scale + tracking
    return " ".join(d), x - tracking, bp.bounds


def lockup_svg(dark=False):
    # Mark on the left, the wordmark on the right, vertically centred on the heart.
    api_d, api_w, api_b = text_path("API", "Bold", 118, tracking=2)
    war_d, war_w, war_b = text_path("warden", "Medium", 118, tracking=1)
    gap = 11
    cap = -api_b[1]                       # cap height in px (bounds are y-down negative above baseline)
    x0 = 252                              # where the wordmark starts
    base = 138 + cap / 2                  # baseline so the caps centre on y=138
    word_w = api_w + gap + war_w
    W = x0 + word_w + 28
    ink = "#E9EDFF" if dark else "#1B2347"
    api_fill = ("url(#a-api)")
    gradient = ('<linearGradient id="a-api" x1="0" y1="0" x2="1" y2="1">'
                + ('<stop offset="0" stop-color="#8E9BFF"/><stop offset="1" stop-color="#4FD1FF"/>' if dark
                   else '<stop offset="0" stop-color="#3B3FF0"/><stop offset="1" stop-color="#2E86FF"/>')
                + "</linearGradient>")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} 256" width="{W:.0f}" height="256" role="img" aria-label="APIwarden">
<defs>{mark_defs('m-')}{gradient}</defs>
{mark_body('m-')}
<g transform="translate({x0} {base:.1f})">
  <path d="{api_d}" fill="{api_fill}"/>
  <g transform="translate({api_w + gap:.1f} 0)"><path d="{war_d}" fill="{ink}"/></g>
</g>
</svg>
"""


def favicon_svg():
    """The mark for tiny sizes: no braces or sparkles, cropped to the heart."""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="36 36 188 196" width="64" height="64">'
            f"<defs>{mark_defs()}</defs>{mark_body(braces=False, sparkles=False)}\n</svg>\n")


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Regenerate the APIwarden logo files.")
    parser.add_argument("--font-dir", default="/usr/share/fonts/truetype/quicksand")
    args = parser.parse_args()
    FONT = args.font_dir.rstrip("/") + "/Quicksand-{}.ttf"

    root = Path(__file__).resolve().parent.parent
    assets, static = root / "assets", root / "src" / "apiwarden" / "static"
    assets.mkdir(exist_ok=True)

    (assets / "logo.svg").write_text(mark_svg())
    (assets / "logo-lockup.svg").write_text(lockup_svg(False))
    (assets / "logo-lockup-dark.svg").write_text(lockup_svg(True))
    (static / "logo.svg").write_text(mark_svg())
    (static / "favicon.svg").write_text(favicon_svg())
    print("wrote", assets, "and", static)
