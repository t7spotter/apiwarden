"""Where apiwarden lives and how to support it.

Shown on the About page, and linked from the footer, the sidebar and the
command palette. All of it can be switched off with the `support` setting, for
a portal mounted in someone else's documentation.

Wallets are grouped by network, not by coin: the same address receives every
coin on that network, and the network is the thing a sender must get right —
funds sent on the wrong one cannot be recovered. tests/test_support.py checks
each address's checksum, so a slip when editing this file fails the build.
"""

from __future__ import annotations

from dataclasses import dataclass

REPO_URL = "https://github.com/t7spotter/apiwarden"
ISSUES_URL = f"{REPO_URL}/issues"


@dataclass(frozen=True)
class Wallet:
    network: str  # what the sender must choose in their wallet
    coins: tuple[str, ...]
    address: str


WALLETS = (
    Wallet(
        network="BNB Smart Chain (BEP-20)",
        coins=("BNB", "USDT"),
        address="0xF437913564BF4Bd692D13Ef82d743ca34A39ddEB",
    ),
    Wallet(
        network="Tron (TRC-20)",
        coins=("TRX", "USDT"),
        address="TK9ikErpWaWCtgBKnLoWw4uNvrn5ZKUTkK",
    ),
    Wallet(
        network="Bitcoin",
        coins=("BTC",),
        address="bc1q8qw8048uqt5z39xy2u98epwl2yhc5tz9nmkeqy",
    ),
)


# Brand colours for the coin chips and each card's accent edge. Presentation
# only: nothing about an address depends on them.
COIN_COLORS = {
    "BNB": "#F0B90B",
    "USDT": "#26A17B",
    "TRX": "#EB0029",
    "BTC": "#F7931A",
}


# Minimal logo marks for the coin chips: the coin's colour as a disc with a plain
# glyph on it, drawn here (24x24) rather than shipped as brand artwork. A coin
# without one falls back to a plain disc.
_GLYPHS = {
    "BTC": (
        '<path d="M9.4 7.4h3.3a2.05 2.05 0 0 1 0 4.1H9.4m0 0h3.9a2.3 2.3 0 0 1 0 4.6H9.4M9.4 7.4v8.7'
        'M11.2 5.9v1.5M13.4 5.9v1.5M11.2 16.1v1.5M13.4 16.1v1.5" fill="none" stroke="#fff" '
        'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    "USDT": (
        '<path d="M7 7.6h10M12 7.6v9.2" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/>'
        '<ellipse cx="12" cy="11.4" rx="5.4" ry="1.6" fill="none" stroke="#fff" stroke-width="1.3"/>'
    ),
    "TRX": (
        '<path d="M7 7.8 17 9.4l-5 8.8zM7 7.8l5.4 4.6M17 9.4l-4.6 3" fill="none" stroke="#fff" '
        'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
    ),
    "BNB": (
        '<path d="M12 5.4l1.5 1.5L12 8.4 10.5 6.9zM12 15.6l1.5 1.5-1.5 1.5-1.5-1.5zM5.4 12l1.5-1.5L8.4 12 '
        '6.9 13.5zM15.6 12l1.5-1.5 1.5 1.5-1.5 1.5zM12 9.9l2.1 2.1-2.1 2.1L9.9 12z" fill="#1d1d1f"/>'
    ),
}


def coin_icon(coin: str, size: int = 18) -> str:
    """An inline SVG mark for a coin. Static markup: nothing in it is user input."""
    colour = COIN_COLORS.get(coin, "#8a8f98")
    return (
        f'<svg class="coin-icon" viewBox="0 0 24 24" width="{size}" height="{size}" aria-hidden="true" focusable="false">'
        f'<circle cx="12" cy="12" r="12" fill="{colour}"/>{_GLYPHS.get(coin, "")}</svg>'
    )
