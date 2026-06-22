"""Tests de l'evaluateur de route (Phase B) — math ENTIERE EVM + 7 portes + courbe + persistance.

Coeur PUR, sans reseau. Verifie : getAmountOut entier == valeur UniV2 connue ; gross(no-fee) > net ;
arb directionnel ; portes (v3 -> REJETE explicite, identite par adresse, decimals) ; decomposition
(gas une seule fois) ; courbe (opt/break-even/90%/min-viable) ; persistance figee ; FORWARD multi-blocs.
"""
import os

from sim.amm_v2_int import (
    get_amount_out_univ2, get_amount_out_solidly, two_pool_profit, optimal_size, pnl_curve,
)
from sim.route_eval import (
    load_universe, evaluate_route, persistence_stats, assign_forward, RouteDecision,
)

WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
FAKE = "0x000000000000000000000000000000000000dead"
UNIVERSE = {WETH: {"symbol": "WETH", "decimals": 18}, USDC: {"symbol": "USDC", "decimals": 6}}


def pool(venue, kind, r0, r1, *, t0=WETH, t1=USDC, dec0=18, dec1=6, fee_bps=30):
    d = {"venue": venue, "kind": kind, "pair": ("WETH", "USDC"), "t0_addr": t0, "t1_addr": t1,
         "dec0": dec0, "dec1": dec1, "r0": r0, "r1": r1}
    if kind == "solidly":
        d["fee_bps"] = fee_bps
    else:
        d["fee_num"], d["fee_den"] = 997, 1000
    return d


# --- 1. Math entiere EVM-exacte (contrat #2) ----------------------------------------------------

def test_univ2_getamountout_valeur_connue():
    # reserves 1e6 each, in 1000, fee 0.3% -> floor(997000*1e6 / (1e6*1000 + 997000)) = 996
    assert get_amount_out_univ2(1000, 1_000_000, 1_000_000, 997, 1000) == 996


def test_nofee_rend_plus_que_avec_frais():
    args = (10**18, 100 * 10**18, 300_000 * 10**6)
    assert get_amount_out_univ2(*args, 1000, 1000) > get_amount_out_univ2(*args, 997, 1000)


def test_solidly_retire_fee_puis_cpmm():
    # ai = 1000 - floor(1000*30/10000)=997 ; out = floor(997*1e6/(1e6+997)) = 996
    assert get_amount_out_solidly(1000, 1_000_000, 1_000_000, 30) == 996
    assert get_amount_out_solidly(1000, 1_000_000, 1_000_000, 0) >= get_amount_out_solidly(1000, 1_000_000, 1_000_000, 30)


def test_arbitrage_directionnel_entier():
    # WETH cher sur A (3030 USDC), moins cher sur B (3000) -> un seul sens profite.
    a = pool("A", "univ2", 100 * 10**18, 330_000 * 10**6)
    b = pool("B", "univ2", 100 * 10**18, 300_000 * 10**6)
    _, prof_ab = optimal_size(a, b)      # X->Y sur A (vend WETH cher), Y->X sur B (rachete bas)
    _, prof_ba = optimal_size(b, a)
    assert prof_ab > 0 and prof_ba <= 0  # exactement un sens (cf sim/amm_v2.arb_exists)


# --- 2. Courbe taille -> PnL (contrat #5) -------------------------------------------------------

def test_courbe_points_cles():
    a = pool("A", "univ2", 100 * 10**18, 330_000 * 10**6)
    b = pool("B", "univ2", 100 * 10**18, 300_000 * 10**6)
    c = pnl_curve(a, b, usd0=3000.0, gas_usd=1.0, decimals_x=18)
    assert c["max_net_usd"] > 0
    assert c["opt_size_x"] > 0
    assert c["breakeven_size_x"] >= c["opt_size_x"]          # capacite au-dela de l'optimum
    assert 0 < c["min_viable_x"] <= c["opt_size_x"]          # gas couvert avant l'optimum
    assert c["opt_size_x"] <= c["size_90_x"] <= c["breakeven_size_x"]


# --- 3. Les 7 portes de evaluate_route ----------------------------------------------------------

def test_porte_v3_rejet_explicite():
    a = pool("UniV3-5", "v3", 0, 0)
    b = pool("UniV2", "univ2", 100 * 10**18, 300_000 * 10**6)
    d = evaluate_route(a, b, 3000.0, 1.0, UNIVERSE, status_margin_usd=5.0)
    assert d.status == "REJETE" and d.reason == "v3_quoter_non_implemente"


def test_porte_identite_token_hors_univers():
    a = pool("A", "univ2", 100 * 10**18, 300_000 * 10**6, t0=FAKE)
    b = pool("B", "univ2", 100 * 10**18, 300_000 * 10**6, t0=FAKE)
    d = evaluate_route(a, b, 3000.0, 1.0, UNIVERSE, status_margin_usd=5.0)
    assert d.status == "REJETE" and "identite_non_certifiee" in d.reason


def test_porte_decimals_incoherents():
    a = pool("A", "univ2", 100 * 10**18, 300_000 * 10**6, dec0=8)   # WETH n'a pas 8 decimals
    b = pool("B", "univ2", 100 * 10**18, 300_000 * 10**6, dec0=8)
    d = evaluate_route(a, b, 3000.0, 1.0, UNIVERSE, status_margin_usd=5.0)
    assert d.status == "REJETE" and "decimals" in d.reason


def test_route_profitable_a_observer_decomposition():
    a = pool("UniV2", "univ2", 100 * 10**18, 330_000 * 10**6)
    b = pool("SushiV2", "univ2", 100 * 10**18, 300_000 * 10**6)
    d = evaluate_route(a, b, 3000.0, 1.0, UNIVERSE, status_margin_usd=5.0)
    assert d.status == "A_OBSERVER" and d.pnl_net_usd > 0
    assert d.pnl_gross_usd >= d.pnl_net_usd                        # frais+gas reduisent le brut
    # gas compte UNE seule fois : net == brut - frais - gas
    assert abs(d.pnl_net_usd - (d.pnl_gross_usd - d.pool_fees_usd - d.gas_usd)) < 1e-6


def test_route_rejetee_si_gas_ecrase_le_net():
    a = pool("UniV2", "univ2", 100 * 10**18, 330_000 * 10**6)
    b = pool("SushiV2", "univ2", 100 * 10**18, 300_000 * 10**6)
    d = evaluate_route(a, b, 3000.0, gas_usd=1e9, universe=UNIVERSE, status_margin_usd=5.0)
    assert d.status == "REJETE" and "pnl_net<=0" in d.reason


# --- 4. Persistance (contrat #4) + FORWARD multi-blocs ------------------------------------------

def test_persistence_stats():
    p = persistence_stats([1.0, 1.0, -1.0, 1.0, 1.0, 1.0], fixed_size_x=0.5, min_blocks=5)
    assert p.n_blocks == 6 and abs(p.frac_positive - 5 / 6) < 1e-9
    assert p.longest_streak == 3 and p.min_blocks_ok is True


def _obs():  # une decision A_OBSERVER avec capacite et marge OK
    a = pool("UniV2", "univ2", 100 * 10**18, 330_000 * 10**6)
    b = pool("SushiV2", "univ2", 100 * 10**18, 300_000 * 10**6)
    return evaluate_route(a, b, 3000.0, 1.0, UNIVERSE, status_margin_usd=5.0)


def test_forward_exige_la_persistance():
    d = _obs()
    bad = persistence_stats([1.0, -1.0, -1.0], fixed_size_x=d.opt_size_x, min_blocks=5)   # trop court + instable
    assert assign_forward(d, bad, p_min=0.7, streak_min=3, cap_min_usd=100.0).status == "A_OBSERVER"
    good = persistence_stats([1.0] * 10, fixed_size_x=d.opt_size_x, min_blocks=5)
    out = assign_forward(d, good, p_min=0.7, streak_min=3, cap_min_usd=100.0)
    assert out.status == "CANDIDAT_FORWARD"


def test_forward_jamais_sur_un_rejet():
    a = pool("UniV3-5", "v3", 0, 0)
    b = pool("UniV2", "univ2", 100 * 10**18, 300_000 * 10**6)
    d = evaluate_route(a, b, 3000.0, 1.0, UNIVERSE, status_margin_usd=5.0)
    good = persistence_stats([1.0] * 10, fixed_size_x=1.0, min_blocks=5)
    assert assign_forward(d, good, p_min=0.7, streak_min=3, cap_min_usd=100.0).status == "REJETE"


# --- 5. Univers certifie depuis la config versionnee --------------------------------------------

def test_load_universe_par_adresse():
    path = os.path.join(os.path.dirname(__file__), "..", "config", "universe_base.json")
    u = load_universe(path)
    assert WETH in u and u[WETH]["decimals"] == 18 and u[WETH]["symbol"] == "WETH"
    assert USDC in u and u[USDC]["decimals"] == 6
    assert all(k == k.lower() for k in u)                         # cle = adresse minuscule, jamais ticker
