"""Tests des contrats de donnees normalises (sim/contracts.py) — MISSION RESET Phase 2.

On epingle les DEUX invariants codes :
  - la formule de PnL net est UNIQUE (compute_net_pnl) a 7 termes (docs/STATE.md §6 == §7) ;
  - ABSTENTION jamais fallback silencieux (§7) : un cout manquant (dont hedge / provision de risque
    operationnel, sans defaut a zero) ou une jambe sans sortie => net NaN, confidence 0,
    missing_fields peuple — jamais un 0 invente.
"""
import math

from sim.contracts import (
    RawQuote, QuotePair, InventoryState, compute_net_pnl, build_quote_pair, content_hash,
)


def _leg(amount_out=1_000_000, **kw):
    base = dict(
        venue="aerodrome", venue_type="dex", chain="base",
        asset_in_address="0xweth", asset_in_decimals=18,
        asset_out_address="0xusdc", asset_out_decimals=6,
        amount_in=10**18, amount_out=amount_out, source="rpc://base",
        wall_clock_utc="2026-06-23T00:00:00Z", request_hash="rq", response_hash="rp",
    )
    base.update(kw)
    return RawQuote(**base)


# --- 1. Formule canonique unique (7 termes) -----------------------------------------------------

def test_compute_net_pnl_formule_canonique():
    # net = brut - frais - gas - rebalancing - capital - hedge - provision_risque_op  (STATE.md §6 / §7)
    assert compute_net_pnl(100.0, 10.0, 5.0, 3.0, 2.0,
                           hedge_usd=4.0, op_risk_provision_usd=1.0) == 75.0
    # atomique mono-chaine : rebalancing/capital par defaut 0, hedge/provision EXPLICITEMENT 0
    assert compute_net_pnl(50.0, 12.0, 8.0, hedge_usd=0.0, op_risk_provision_usd=0.0) == 30.0


def test_quote_pair_complete_net_et_confidence():
    qp = build_quote_pair(
        asset_economic_id="velvet", buy=_leg(), sell=_leg(amount_out=2 * 10**18),
        direction="bsc->base", size_usd=1000.0, same_time_tolerance=2.0,
        gross_pnl_usd=100.0, fees_usd=10.0, gas_usd=5.0, rebalancing_usd=3.0, capital_usd=2.0,
        hedge_usd=4.0, op_risk_provision_usd=1.0,
    )
    assert qp.net_pnl_usd == 75.0
    assert qp.confidence == 1.0
    assert qp.missing_fields == ()
    assert isinstance(qp.to_dict()["buy"], dict)   # asdict recurse sur les jambes


# --- 2. Garde d'abstention (jamais de 0 invente) ------------------------------------------------

def test_cout_manquant_declenche_abstention():
    qp = build_quote_pair(
        asset_economic_id="x", buy=_leg(), sell=_leg(),
        direction="a->b", size_usd=1000.0, same_time_tolerance=2.0,
        gross_pnl_usd=100.0, fees_usd=None, gas_usd=5.0,   # frais INCONNUS
        hedge_usd=0.0, op_risk_provision_usd=0.0,
    )
    assert math.isnan(qp.net_pnl_usd)        # pas de net invente
    assert qp.confidence == 0.0
    assert "fees_usd" in qp.missing_fields
    assert math.isnan(qp.fees_usd)


def test_hedge_inconnu_declenche_abstention():
    # hedge applicable mais INCONNU => None => abstention (jamais un 0 silencieux), §7
    qp = build_quote_pair(
        asset_economic_id="x", buy=_leg(), sell=_leg(),
        direction="a->b", size_usd=1000.0, same_time_tolerance=2.0,
        gross_pnl_usd=100.0, fees_usd=10.0, gas_usd=5.0,
        hedge_usd=None, op_risk_provision_usd=0.0,
    )
    assert math.isnan(qp.net_pnl_usd)
    assert qp.confidence == 0.0
    assert "hedge_usd" in qp.missing_fields
    assert math.isnan(qp.hedge_usd)


def test_jambe_sans_sortie_declenche_abstention():
    qp = build_quote_pair(
        asset_economic_id="x", buy=_leg(amount_out=0), sell=_leg(),   # buy revert (0 recu)
        direction="a->b", size_usd=1000.0, same_time_tolerance=2.0,
        gross_pnl_usd=100.0, fees_usd=10.0, gas_usd=5.0,
        hedge_usd=0.0, op_risk_provision_usd=0.0,
    )
    assert math.isnan(qp.net_pnl_usd)
    assert qp.confidence == 0.0
    assert "buy.amount_out" in qp.missing_fields


# --- 3. content_hash deterministe et insensible a l'ordre des cles ------------------------------

def test_content_hash_deterministe_et_ordre_independant():
    a = content_hash({"venue": "kyber", "amount_in": 100, "chain": "bsc"})
    b = content_hash({"chain": "bsc", "amount_in": 100, "venue": "kyber"})   # autre ordre
    assert a == b
    assert a != content_hash({"venue": "kyber", "amount_in": 101, "chain": "bsc"})
    assert len(a) == 64   # sha256 hex


def test_inventory_state_construct():
    inv = InventoryState(
        asset="velvet", chain="base", venue="aerodrome", stable_balance=1000.0, token_balance=0.0,
        available_capacity=500.0, rebalancing_path="LI.FI bsc->base", rebalancing_cost=0.3,
        rebalancing_delay="~minutes", inventory_imbalance=-1.0, maximum_adverse_exposure=50.0,
    )
    assert inv.to_dict()["asset"] == "velvet"
