"""Tests OFFLINE des fonctions pures du runner D1.5 (d1_5_crossprotocol_envelope) — AUCUN réseau.

Vérifie la spécificité SlipStream : indexation par `tickSpacing` (int24), donc sélecteurs DISTINCTS de
Uniswap v3 (qui utilise `fee` uint24). Couvre encodage quote/getPool, certification mêmes tokens, extraction
d'adresse, et arithmétique round-trip brut.
"""
from d1_5_crossprotocol_envelope import (
    SEL_SLIP_QUOTE, SEL_GETPOOL_TS, WETH, USDC,
    slip_quote_calldata, getpool_calldata, same_tokens, gross_roundtrip_wei, wei_to_usd, addr_from_word,
)
from web3 import Web3


def test_slip_quote_calldata_tickspacing():
    cd = slip_quote_calldata(WETH, USDC, 10 ** 18, 100)
    assert cd[:4] == SEL_SLIP_QUOTE
    assert len(cd) == 4 + 32 * 5                     # tuple statique 5 mots
    # 4e mot (index 3) = tickSpacing int24 = 100
    assert int.from_bytes(cd[4 + 96:4 + 128], "big") == 100
    # SlipStream (int24 tickSpacing) != Uniswap v3 QuoterV2 (uint24 fee) = 0xc6a5026a
    assert SEL_SLIP_QUOTE != bytes.fromhex("c6a5026a")


def test_getpool_calldata_int24():
    cd = getpool_calldata(WETH, USDC, 200)
    assert cd[:4] == SEL_GETPOOL_TS
    assert len(cd) == 4 + 32 * 3
    assert int.from_bytes(cd[4 + 64:4 + 96], "big") == 200
    # getPool(address,address,int24) != Uni v3 getPool(address,address,uint24) = 0x1698ee82
    assert SEL_GETPOOL_TS != bytes.fromhex("1698ee82")


def test_same_tokens_order_independent():
    assert same_tokens(WETH, USDC, WETH, USDC) is True
    assert same_tokens(USDC, WETH, WETH, USDC) is True          # ordre inversé -> identique
    assert same_tokens(WETH, WETH, WETH, USDC) is False         # mauvais couple
    other = "0x0000000000000000000000000000000000000001"
    assert same_tokens(WETH, other, WETH, USDC) is False


def test_gross_roundtrip_wei():
    assert gross_roundtrip_wei(99 * 10 ** 16, 10 ** 18) == 99 * 10 ** 16 - 10 ** 18   # perdant
    assert gross_roundtrip_wei(101 * 10 ** 16, 10 ** 18) > 0


def test_wei_to_usd():
    assert abs(wei_to_usd(10 ** 18, 1663.86) - 1663.86) < 1e-6
    assert abs(wei_to_usd(-(10 ** 17), 2000.0) + 200.0) < 1e-9


def test_addr_from_word():
    word = (b"\x00" * 12) + bytes.fromhex(WETH[2:])
    assert addr_from_word(word) == WETH
    assert addr_from_word(b"\x00" * 32) is None                 # adresse zéro -> None
    assert addr_from_word(b"\x00" * 10) is None                 # trop court -> None
