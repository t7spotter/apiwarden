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
