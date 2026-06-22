"""Tests de la porte de validation pool/token (PURE) — Phase 2 integrite."""
from sim.validate import judge_pool

T0 = "0x0b3e328455c4059EEb9e3f84b5543F74E24e7E1b"   # exemple token0 (adresse plus basse)
T1 = "0x4200000000000000000000000000000000000006"   # WETH (token1)


def test_pool_uniV2_ok_fee_verifie():
    ok, reasons, meta = judge_pool(T0, T1, T0, T1, is_aero=False, stable_flag=None, fee=0.0030, fee_canonical=True)
    assert ok and not reasons
    assert meta["type_verified"] is True and meta["fee_verified"] is True


def test_orientation_inversee_rejetee():
    ok, reasons, meta = judge_pool(T0, T1, T1, T0, is_aero=False, stable_flag=None, fee=0.0030, fee_canonical=True)
    assert not ok and any("orientation" in r for r in reasons)


def test_aerodrome_stable_rejete():
    ok, reasons, _ = judge_pool(T0, T1, T0, T1, is_aero=True, stable_flag=True, fee=0.0030, fee_canonical=False)
    assert not ok and any("STABLE" in r for r in reasons)


def test_aerodrome_volatile_ok_fee_onchain():
    ok, reasons, meta = judge_pool(T0, T1, T0, T1, is_aero=True, stable_flag=False, fee=0.0005, fee_canonical=False)
    assert ok and meta["fee_verified"] is True   # aero -> frais lus on-chain


def test_baseswap_fee_non_verifie_mais_inclus():
    ok, reasons, meta = judge_pool(T0, T1, T0, T1, is_aero=False, stable_flag=None, fee=0.0030, fee_canonical=False)
    assert ok and meta["fee_verified"] is False   # inclus mais marque "frais non garantis"


def test_frais_illisibles_rejete():
    ok, reasons, _ = judge_pool(T0, T1, T0, T1, is_aero=False, stable_flag=None, fee=None, fee_canonical=True)
    assert not ok and any("frais" in r for r in reasons)


def test_token_illisible_rejete():
    ok, reasons, _ = judge_pool(T0, T1, None, None, is_aero=False, stable_flag=None, fee=0.0030, fee_canonical=True)
    assert not ok and any("illisible" in r for r in reasons)
