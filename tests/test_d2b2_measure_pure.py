"""Tests OFFLINE des fonctions pures du runner D2B-2-mesure — AUCUN reseau.

Verifie l'encodage des 4 regles : fenetre inclusive [B1-299, B1] ; formule upper_bound en USDC avec
conversion gas via ancre ETH/USD ; ancre Chainlink ON-CHAIN INDEPENDANTE + garde-fous (positif, updatedAt
<= ts, staleness <= seuil) ; categories SEPAREES (WINDOW_UNAVAILABLE / CAPACITY / NON_CONCLUANT / ok).
"""
from d2b2_measure import (
    B1, window_blocks, gas_normal_usdc, upper_bound_usdc, classify_cycle, anchor_eth_usd,
    CHAINLINK_ETH_USD, CHAINLINK_DECIMALS, STALENESS_MAX_S,
)


def test_window_300_inclusif_b1():
    b_start, b_end, n = window_blocks(B1)
    assert B1 == 47762470
    assert b_end == 47762470 and b_start == 47762470 - 299 == 47762171
    assert n == 300 and (b_end - b_start + 1) == 300


def test_gas_normal_usdc_conversion_ancre():
    assert abs(gas_normal_usdc(10 ** 15, 3000.0) - 3.0) < 1e-9        # 0.001 ETH -> $3


def test_upper_bound_usdc_formule():
    ub = upper_bound_usdc(out_usdc_6dec=999_500000, in_usdc_6dec=1000_000000, gas_norm_usdc=0.30)
    assert abs(ub - (-0.80)) < 1e-9
    assert upper_bound_usdc(1001_000000, 1000_000000, 0.10) > 0


def test_classify_categories_separees():
    assert classify_cycle(False, "revert", True, True) == "WINDOW_UNAVAILABLE"   # pool absent
    assert classify_cycle(True, "revert", True, True) == "CAPACITY"              # revert sur route presente
    assert classify_cycle(True, "rpcerror", True, True) == "NON_CONCLUANT"       # infra
    assert classify_cycle(True, "ok", anchor_ok=False, gas_ok=True) == "NON_CONCLUANT"   # ancre manquante
    assert classify_cycle(True, "ok", anchor_ok=True, gas_ok=False) == "NON_CONCLUANT"   # gas manquant
    assert classify_cycle(True, "ok", True, True) == "ok"


def test_anchor_eth_usd_garde_fous():
    ANS = 163741000000   # 1637.41 * 1e8
    assert abs(anchor_eth_usd(ANS, updated_at=1000, block_ts=1020) - 1637.41) < 1e-6   # frais, valide
    assert anchor_eth_usd(0, 1000, 1020) is None                 # answer non strictement positif
    assert anchor_eth_usd(-5, 1000, 1020) is None                # answer negatif (int256)
    assert anchor_eth_usd(ANS, updated_at=1100, block_ts=1020) is None              # updatedAt dans le futur
    assert anchor_eth_usd(ANS, updated_at=1020 - STALENESS_MAX_S - 1, block_ts=1020) is None  # trop perime
    assert anchor_eth_usd(None, 1000, 1020) is None and anchor_eth_usd(ANS, None, 1020) is None


def test_chainlink_constantes_figees():
    assert CHAINLINK_ETH_USD.lower() == "0x71041dddad3595f9ced3dccfbe3d1f4b0a16bb70"
    assert CHAINLINK_DECIMALS == 8 and STALENESS_MAX_S == 3600
