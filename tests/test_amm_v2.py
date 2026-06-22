"""Tests de la math AMM v2 : la forme fermee doit coller a la simulation brute.

- get_amount_out preserve l'invariant constant-product (avec frais).
- two_pool_x_out (forme fermee) == 2 swaps get_amount_out enchaines.
- optimal_dx (Δx*) == argmax brute-force du profit, et bat tout point de la grille.
- arb_exists / direction : exactement un sens est rentable quand les prix divergent.
- pools identiques -> aucun arbitrage.
"""
import math

from sim.amm_v2 import (
    get_amount_out, two_pool_x_out, optimal_dx, arb_exists, evaluate_cycle, evaluate_pair,
)


def test_get_amount_out_preserves_invariant():
    rin, rout, fee = 100.0, 300_000.0, 0.003
    g = 1.0 - fee
    for amount_in in (0.1, 1.0, 5.0, 25.0):
        out = get_amount_out(amount_in, rin, rout, fee)
        # apres swap : (rin + g*amount_in) * (rout - out) == rin * rout
        assert math.isclose((rin + g * amount_in) * (rout - out), rin * rout, rel_tol=1e-12)
        assert 0 < out < rout


def test_closed_form_equals_two_sequential_swaps():
    a, b, c, d = 120.0, 360_000.0, 90.0, 280_000.0
    f1, f2 = 0.003, 0.003
    g1, g2 = 1 - f1, 1 - f2
    for dx in (0.05, 0.5, 2.0, 10.0, 40.0):
        dy = get_amount_out(dx, a, b, f1)        # X->Y sur A (in X=a, out Y=b)
        x_back = get_amount_out(dy, d, c, f2)    # Y->X sur B (in Y=d, out X=c)
        closed = two_pool_x_out(dx, a, b, c, d, g1, g2)
        assert math.isclose(closed, x_back, rel_tol=1e-12)


def _brute_best_dx(a, b, c, d, g1, g2, hi, n=400_000):
    best_p, best_x = -1e30, 0.0
    for i in range(1, n + 1):
        dx = hi * i / n
        p = two_pool_x_out(dx, a, b, c, d, g1, g2) - dx
        if p > best_p:
            best_p, best_x = p, dx
    return best_x, best_p


def test_optimal_dx_matches_brute_force_and_dominates_grid():
    # Pool A a 3000 USDC/WETH, Pool B a 3030 -> arbitrage dans le sens B->A.
    a, b = 100.0, 300_000.0       # WETH, USDC
    c, d = 100.0, 303_000.0
    g1, g2 = 0.997, 0.997
    # Sens rentable = B->A : X->Y sur B=(c,d), Y->X sur A=(a,b)
    assert arb_exists(c, d, a, b, g2, g1)
    assert not arb_exists(a, b, c, d, g1, g2)
    dxs = optimal_dx(c, d, a, b, g2, g1)
    assert dxs > 0
    hi = dxs * 3.0
    bx, bp = _brute_best_dx(c, d, a, b, g2, g1, hi)
    # la forme fermee bat (ou egale) le meilleur point de la grille
    p_closed = two_pool_x_out(dxs, c, d, a, b, g2, g1) - dxs
    assert p_closed >= bp - 1e-9
    # et l'argmax brute tombe sur Δx* (a la resolution de grille pres)
    assert math.isclose(dxs, bx, rel_tol=2e-3)
    assert p_closed > 0


def test_identical_pools_no_arbitrage():
    a, b = 100.0, 300_000.0
    g = 0.997
    assert not arb_exists(a, b, a, b, g, g)
    assert optimal_dx(a, b, a, b, g, g) <= 0
    evs = evaluate_pair({"reserve_x": a, "reserve_y": b, "fee": 0.003},
                        {"reserve_x": a, "reserve_y": b, "fee": 0.003}, gas_token0=0.0)
    assert all(e.status == "REJECTED" for e in evs)


def test_evaluate_cycle_reasons():
    # gas enorme -> rejet pour profit_net<=0 meme si brut>0
    a, b = 100.0, 300_000.0
    c, d = 100.0, 303_000.0
    g = 0.997
    ev = evaluate_cycle("B->A", c, d, a, b, g, g, gas_token0=0.0)
    assert ev.status == "ACCEPTED" and ev.gross_profit > 0
    ev_gas = evaluate_cycle("B->A", c, d, a, b, g, g, gas_token0=ev.gross_profit + 1.0)
    assert ev_gas.status == "REJECTED" and "net" in ev_gas.reason
    # sens non rentable -> dx*<=0
    ev_bad = evaluate_cycle("A->B", a, b, c, d, g, g, gas_token0=0.0)
    assert ev_bad.status == "REJECTED" and "dx*" in ev_bad.reason


def test_exactly_one_direction_profitable_when_prices_diverge():
    a, b = 100.0, 300_000.0
    c, d = 100.0, 305_000.0
    evs = evaluate_pair({"reserve_x": a, "reserve_y": b, "fee": 0.003},
                        {"reserve_x": c, "reserve_y": d, "fee": 0.003}, gas_token0=0.0)
    accepted = [e for e in evs if e.status == "ACCEPTED"]
    assert len(accepted) == 1
    assert accepted[0].direction == "B->A"   # WETH plus cher sur B -> vendre WETH sur B, racheter sur A
