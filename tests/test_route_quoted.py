"""Tests de l'evaluateur par QUOTES (Phase v3) — PUR (quote_leg + gas_model mockes, zero reseau).

Verifie : round-trip ; decomposition gas SEPAREE (exec+L1+marge=total, gel #2) ; net = pnl_quote - gas ;
statut POSITIF/REJETE ; et la CLASSIFICATION calibration (gel #3) qui ne produit JAMAIS CANDIDAT_FORWARD (gel #1).
"""
from sim.route_quoted import (
    round_trip, evaluate_route_quoted, classify_calibration, QuotedDecision,
)

SIZES = [1000, 5000, 25000, 100000, 250000]
FIXED = 25000
USD0 = 3000.0          # ancre INDEPENDANTE (prix de token0=WETH), passee a l'evaluateur
DEC = 18


def gas_model(units):
    """(exec, L1, marge, total) — total = somme ; jamais 'exact' (gel #2)."""
    exec_usd = units * 1e-7
    l1, marge = 0.05, 0.02
    return exec_usd, l1, marge, exec_usd + l1 + marge


def leg(edge, gas_units=150_000):
    """Mock : round-trip multiplie dx par (1+edge). edge>0 -> profit. pool 'abstain' -> None."""
    def ql(pool, x_to_y, amount_in):
        if pool == "abstain":
            return None
        return (amount_in, gas_units) if x_to_y else (int(amount_in * (1 + edge)), gas_units)
    return ql


def test_round_trip():
    ql = leg(0.01)
    assert round_trip(ql, "a", "b", 10**18)[0] == int(10**18 * 1.01)     # profit
    assert round_trip(ql, "a", "b", 0) is None                           # dx<=0
    assert round_trip(leg(0.0, gas_units=1), "abstain", "b", 10**18) is None  # 1re jambe abstient


def test_route_positif_et_decomposition_gas():
    d = evaluate_route_quoted("WETH/USDC", "UniV3-5", "UniV3-30", "a", "b",
                              SIZES, FIXED, USD0, DEC, gas_model, leg(0.01))
    assert d.status == "POSITIF" and d.pnl_net_usd > 0
    # gas SEPARE en 3 et somme exacte (gel #2)
    assert abs(d.gas_total_usd - (d.gas_exec_usd + d.gas_l1_usd + d.gas_marge_usd)) < 1e-9
    assert d.gas_exec_usd > 0 and d.gas_l1_usd > 0 and d.gas_marge_usd > 0
    # net = pnl_quote (apres frais de pool, dans la quote) - gas_total
    assert abs(d.pnl_net_usd - (d.pnl_quote_usd - d.gas_total_usd)) < 1e-6
    assert d.breakeven_size_usd >= d.opt_size_usd                        # capacite >= taille optimale


def test_route_rejete_si_gas_ecrase():
    big_gas = lambda u: (1e9, 1e9, 1e9, 3e9)
    d = evaluate_route_quoted("WETH/USDC", "A", "B", "a", "b",
                              SIZES, FIXED, USD0, DEC, big_gas, leg(0.01))
    assert d.status == "REJETE" and "pnl_net<=0" in d.reason


def test_route_rejete_si_tout_abstient():
    d = evaluate_route_quoted("WETH/USDC", "A", "B", "abstain", "abstain",
                              SIZES, FIXED, USD0, DEC, gas_model, leg(0.01))
    assert d.status == "REJETE" and "abstenues" in d.reason
    assert d.n_abstain_sizes == len(SIZES)


def test_classification_jamais_forward_en_calibration():
    # les 4 statuts possibles en calibration ; CANDIDAT_FORWARD ne doit JAMAIS sortir (gel #1)
    assert classify_calibration(0.0, 0, True, 0.7, 3) == "REJETE"
    assert classify_calibration(0.3, 1, True, 0.7, 3) == "MEV_RACE"          # isole -> course
    assert classify_calibration(0.5, 2, True, 0.7, 3) == "A_OBSERVER_COURT"  # PnL>0 mais sous seuil
    assert classify_calibration(0.9, 5, True, 0.7, 3) == "A_OBSERVER"        # persistance suffisante
    for args in [(0.0, 0), (0.3, 1), (0.5, 2), (0.9, 5), (1.0, 48)]:
        assert classify_calibration(*args, True, 0.7, 3) != "CANDIDAT_FORWARD"
