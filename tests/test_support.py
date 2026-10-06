"""The About page, the support links, and the wallet addresses behind them."""

import hashlib
import re

import pytest

from apiwarden.build import build_static
from apiwarden.cli import main
from apiwarden.config import Config, from_dict
from apiwarden.http import Request
from apiwarden.router import Portal, handle
from apiwarden.support import ISSUES_URL, REPO_URL, WALLETS

_BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _tron_ok(address: str) -> bool:
    """base58check: version 0x41, twenty bytes, and a double-SHA256 checksum."""
    if len(address) != 34 or any(c not in _BASE58 for c in address):
        return False
    number = 0
    for char in address:
        number = number * 58 + _BASE58.index(char)
    raw = number.to_bytes(25, "big")
    return raw[0] == 0x41 and hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()[:4] == raw[-4:]


def _btc_ok(address: str) -> bool:
    """A native-segwit (bech32) mainnet address with a valid checksum."""
    if not address.startswith("bc1q") or len(address) != 42:
        return False
    if any(c not in _BECH32 for c in address[3:]):
        return False

    def polymod(values):
        generator = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
        check = 1
        for value in values:
            top = check >> 25
            check = (check & 0x1FFFFFF) << 5 ^ value
            for i in range(5):
                check ^= generator[i] if (top >> i) & 1 else 0
        return check

    expanded = [ord(c) >> 5 for c in "bc"] + [0] + [ord(c) & 31 for c in "bc"]
    return polymod(expanded + [_BECH32.index(c) for c in address[3:]]) == 1


def _evm_ok(address: str) -> bool:
    return bool(re.fullmatch(r"0x[0-9a-fA-F]{40}", address))


CHECKS = {"BNB Smart Chain (BEP-20)": _evm_ok, "Tron (TRC-20)": _tron_ok, "Bitcoin": _btc_ok}


@pytest.mark.parametrize("wallet", WALLETS, ids=lambda w: w.network)
def test_every_wallet_address_is_well_formed(wallet):
    # A typo here would send donations nowhere, so the checksum is the test.
    assert CHECKS[wallet.network](wallet.address), f"{wallet.network}: {wallet.address} fails its checksum"


def test_no_two_networks_share_an_address_by_accident():
    addresses = [w.address for w in WALLETS]
    assert len(addresses) == len(set(addresses))


def test_the_checks_themselves_reject_a_corrupted_address():
    tron = next(w for w in WALLETS if w.network.startswith("Tron")).address
    assert not _tron_ok(tron[:-1] + ("a" if tron[-1] != "a" else "b"))
    btc = next(w for w in WALLETS if w.network == "Bitcoin").address
    assert not _btc_ok(btc[:-1] + ("q" if btc[-1] != "q" else "p"))


# ---------------------------------------------------------------- pages


def test_about_page_has_the_repo_and_every_wallet(portal):
    response = handle(Request("GET", "/about"), portal)
    assert response.status == 200
    markup = response.body.decode()
    assert REPO_URL in markup and ISSUES_URL in markup
    for wallet in WALLETS:
        assert wallet.address in markup
        assert wallet.network in markup
        assert f'data-copy="{wallet.address}"' in markup
    assert "Check the network before you send" in markup
    assert handle(Request("GET", "/about/"), portal).status == 200


def test_pages_link_to_the_repo_and_support(portal, registry):
    for path in ("/", "/changes"):
        markup = handle(Request("GET", path), portal).body.decode()
        assert 'class="site-footer"' in markup, path
        assert REPO_URL in markup and "/about/#support" in markup, path

    api = handle(Request("GET", f"/{registry.names()[0]}/"), portal).body.decode()
    assert REPO_URL in api and "/about/#support" in api  # the sidebar links


def test_the_support_flag_reaches_the_script(portal):
    assert f'"repo": "{REPO_URL}"' in handle(Request("GET", "/"), portal).body.decode()


def test_support_can_be_switched_off(registry, sample_root):
    quiet = Portal(Config(root=sample_root, support=False), registry)
    assert handle(Request("GET", "/about"), quiet).status == 404
    for path in ("/", "/changes", f"/{registry.names()[0]}/"):
        markup = handle(Request("GET", path), quiet).body.decode()
        assert REPO_URL not in markup and "site-footer" not in markup and "/about/" not in markup, path
        assert '"support": false' in markup


def test_support_setting_and_flag(sample_root):
    assert from_dict({"support": False}).support is False
    assert Config().support is True

    from apiwarden.cli import _config

    class Args:
        no_support = True

    assert _config(sample_root, Args()).support is False


def test_static_build_includes_the_about_page_unless_off(config, tmp_path):
    build_static(config, tmp_path / "on")
    assert (tmp_path / "on" / "about" / "index.html").exists()

    quiet = Config(root=config.root, support=False)
    build_static(quiet, tmp_path / "off")
    assert not (tmp_path / "off" / "about").exists()
