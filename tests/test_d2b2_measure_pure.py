"""Tests OFFLINE des fonctions pures du runner D2B-2-mesure — AUCUN reseau.

Verifie l'encodage des 4 regles : fenetre inclusive [B1-299, B1] ; formule upper_bound en USDC avec
conversion gas via ancre ETH/USD ; categories SEPAREES (WINDOW_UNAVAILABLE / CAPACITY / NON_CONCLUANT / ok).
"""
from d2b2_measure import (
    B1, window_blocks, gas_normal_usdc, upper_bound_usdc, classify_cycle, ANCHOR_SIZE_WETH, ANCHOR_FEE,
)


def test_window_300_inclusif_b1():
    b_start, b_end, n = window_blocks(B1)
    assert B1 == 47762470
    assert b_end == 47762470 and b_start == 47762470 - 299 == 47762171
    assert n == 300 and (b_end - b_start + 1) == 300


def test_gas_normal_usdc_conversion_ancre():
    # gas en wei -> USD via ancre ETH/USD lue au bloc b
    assert abs(gas_normal_usdc(10 ** 15, 3000.0) - (10 ** 15 / 1e18 * 3000.0)) < 1e-12   # 0.001 ETH -> $3
    assert abs(gas_normal_usdc(10 ** 15, 3000.0) - 3.0) < 1e-9


def test_upper_bound_usdc_formule():
    # entree $1000 (1e9 en USDC-6dec), sortie 999.5 USDC, gas $0.30 -> -0.80
    ub = upper_bound_usdc(out_usdc_6dec=999_500000, in_usdc_6dec=1000_000000, gas_norm_usdc=0.30)
    assert abs(ub - (-0.80)) < 1e-9
    # sortie > entree et gas faible -> positif
    assert upper_bound_usdc(1001_000000, 1000_000000, 0.10) > 0


def test_classify_categories_separees():
    # pool absent -> WINDOW_UNAVAILABLE (pas un revert de capacite)
    assert classify_cycle(pool_present=False, exec_status="revert", anchor_ok=True, gas_ok=True) == "WINDOW_UNAVAILABLE"
    # route presente + revert d'execution -> CAPACITY
    assert classify_cycle(True, "revert", True, True) == "CAPACITY"
    # erreur RPC -> NON_CONCLUANT
    assert classify_cycle(True, "rpcerror", True, True) == "NON_CONCLUANT"
    # ok mais ancre OU gas manquant -> NON_CONCLUANT (jamais gas=0)
    assert classify_cycle(True, "ok", anchor_ok=False, gas_ok=True) == "NON_CONCLUANT"
    assert classify_cycle(True, "ok", anchor_ok=True, gas_ok=False) == "NON_CONCLUANT"
    # tout ok
    assert classify_cycle(True, "ok", True, True) == "ok"


def test_ancre_parametres_figes():
    assert ANCHOR_SIZE_WETH == 10 ** 18 and ANCHOR_FEE == 500
