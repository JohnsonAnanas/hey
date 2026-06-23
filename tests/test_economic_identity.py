"""Tests du registre d'identite economique (sim/economic_identity.py + config/economic_identity.json)
— MISSION RESET Phase 3.

On epingle la doctrine §5 : les niveaux ne sont JAMAIS equivalents, et un palier ECONOMIQUE exige un
recu archive+hashe (evidence_hash) — un evidence_url seul ne suffit pas. Reflete les reclassements
CTM (CONTRACT_SAME) et VELVET (IDENTITY_PRELIMINARY tant que le recu LI.FI n'est pas hashe).
"""
import json

import pytest

from sim.economic_identity import (
    IDENTITY_PRELIMINARY, CONTRACT_SAME, ECONOMIC_IDENTITY_CONFIRMED, REBALANCING_CONFIRMED,
    EconomicAsset, load_registry, contract_same,
    eligible_for_inventory_research, eligible_for_paper_trading, canonical_from_registry,
)


@pytest.fixture(scope="module")
def reg():
    return load_registry()   # config/economic_identity.json par defaut


# --- 1. Le registre seed se charge et se valide -------------------------------------------------

def test_registre_charge_les_trois_actifs(reg):
    assert set(reg) == {"ctm", "cbbtc", "velvet"}


def test_niveaux_non_interchangeables():
    assert ECONOMIC_IDENTITY_CONFIRMED != CONTRACT_SAME != REBALANCING_CONFIRMED
    # ordre strict des paliers prouves
    a = _mk(status=CONTRACT_SAME, addrs={"bsc": _SAME, "eth": _SAME})
    b = _mk(status=REBALANCING_CONFIRMED, addrs={"bsc": _SAME, "eth": _SAME})
    assert b.rank > a.rank
    assert b.at_least(ECONOMIC_IDENTITY_CONFIRMED) and not a.at_least(ECONOMIC_IDENTITY_CONFIRMED)
    # le plancher est SOUS CONTRACT_SAME et n'ouvre aucun gate
    pre = _mk(status=IDENTITY_PRELIMINARY, addrs={"base": _A1, "bsc": _A2})
    assert pre.rank < a.rank
    assert not pre.at_least(CONTRACT_SAME)


# --- 2. CTM : CONTRACT_SAME, mais PAS de rebalancing (lecon « OFT absent != pas de bridge ») -----

def test_ctm_contract_same_sans_rebalancing(reg):
    ctm = reg["ctm"]
    assert ctm.status == CONTRACT_SAME
    assert contract_same(ctm) is True                         # meme adresse bsc/eth
    assert not eligible_for_inventory_research(ctm)           # < ECONOMIC_IDENTITY_CONFIRMED
    assert not eligible_for_paper_trading(ctm)


# --- 3. VELVET : IDENTITY_PRELIMINARY (recu LI.FI non hashe) => HORS inventory -------------------

def test_velvet_preliminaire_hors_inventory(reg):
    v = reg["velvet"]
    assert v.status == IDENTITY_PRELIMINARY
    assert v.evidence_hash is None                            # recu LI.FI pas encore archive+hashe
    assert contract_same(v) is False                          # adresses base != bsc
    assert not eligible_for_inventory_research(v)             # plancher : aucun gate
    assert not eligible_for_paper_trading(v)


def test_cbbtc_contract_same(reg):
    assert reg["cbbtc"].status == CONTRACT_SAME
    assert contract_same(reg["cbbtc"]) is True


# --- 4. La validation REFUSE un statut sans la preuve correspondante ----------------------------

def test_load_refuse_contract_same_sans_meme_adresse(tmp_path):
    p = _write(tmp_path, _mk_raw(status=CONTRACT_SAME, addrs={"base": _A1, "bsc": _A2},
                                 evidence_url=None, evidence_hash=None))
    with pytest.raises(ValueError, match="CONTRACT_SAME"):
        load_registry(str(p))


def test_load_refuse_economique_sans_hash(tmp_path):
    # evidence_url present mais PAS de evidence_hash => un pointeur n'est pas une preuve => refus
    p = _write(tmp_path, _mk_raw(status=ECONOMIC_IDENTITY_CONFIRMED, addrs={"base": _A1, "bsc": _A2},
                                 evidence_url="https://bridge.doc/officiel", evidence_hash=None))
    with pytest.raises(ValueError, match="evidence_hash"):
        load_registry(str(p))


def test_load_accepte_economique_avec_hash(tmp_path):
    p = _write(tmp_path, _mk_raw(status=ECONOMIC_IDENTITY_CONFIRMED, addrs={"base": _A1, "bsc": _A2},
                                 evidence_url="https://bridge.doc/officiel", evidence_hash="a" * 64))
    reg = load_registry(str(p))
    assert reg["t"].status == ECONOMIC_IDENTITY_CONFIRMED
    assert eligible_for_inventory_research(reg["t"])          # palier + recu hashe => gate ouvert


def test_load_accepte_identity_preliminary_mais_hors_gate(tmp_path):
    # plancher honnete : se charge sans preuve, mais n'ouvre aucun gate
    p = _write(tmp_path, _mk_raw(status=IDENTITY_PRELIMINARY, addrs={"base": _A1, "bsc": _A2},
                                 evidence_url="https://live/observe", evidence_hash=None))
    reg = load_registry(str(p))
    assert reg["t"].status == IDENTITY_PRELIMINARY
    assert not eligible_for_inventory_research(reg["t"])


def test_load_refuse_statut_inconnu(tmp_path):
    p = _write(tmp_path, _mk_raw(status="VALIDE", addrs={"bsc": _SAME, "eth": _SAME}))
    with pytest.raises(ValueError, match="invalide"):
        load_registry(str(p))


def test_canonical_from_registry(reg):
    table = canonical_from_registry(reg)
    assert table["ctm"]["bsc"] == _SAME.lower()


# --- helpers ------------------------------------------------------------------------------------

_SAME = "0xc8fb80fcc03f699c70ff0cc08c09106288888888"
_A1 = "0xbf927b841994731c573bdf09ceb0c6b0aa887cdd"
_A2 = "0x8b194370825e37b33373e74a41009161808c1488"


def _mk_raw(status, addrs, evidence_url="x", evidence_hash=None):
    return {
        "economic_asset_id": "t", "project": "T", "token_addresses": addrs,
        "contract_verification_source": "test", "bridge_route": "test",
        "source_chain": list(addrs)[0], "destination_chain": list(addrs)[1],
        "bridge_fee_bps": None, "min_usd": None, "max_usd": None, "delay": "", "limits": "",
        "risks": "", "verified_utc": "2026-06-23", "evidence_url": evidence_url,
        "evidence_hash": evidence_hash, "status": status, "next_measure": "", "notes": "",
    }


def _mk(status, addrs):
    return EconomicAsset(**_mk_raw(status, addrs))


def _write(tmp_path, rec):
    p = tmp_path / "reg.json"
    p.write_text(json.dumps({"version": 1, "assets": {"t": rec}}), encoding="utf-8")
    return p
